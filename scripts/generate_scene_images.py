import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


def as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def get_total_episodes(project_meta: dict[str, Any]) -> int:
    value = project_meta.get("total_episodes", 1)
    if isinstance(value, int) and value > 0:
        return value
    text = as_text(value)
    if text.isdigit() and int(text) > 0:
        return int(text)
    return 1


def extract_json_object(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        parsed = json.loads(text[start : end + 1])
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("响应内容中未找到合法 JSON 对象")


def normalize_style_tags(value: Any) -> list[str]:
    if isinstance(value, list):
        return [as_text(item) for item in value if as_text(item)]
    if isinstance(value, str):
        text = value.replace("，", ",")
        return [item.strip() for item in text.split(",") if item.strip()]
    return []


def compose_image_prompt(scene_prompt_data: dict[str, Any], scene_meta: dict[str, Any]) -> str:
    scene_prompt = as_text(scene_prompt_data.get("scene_prompt"))
    if not scene_prompt:
        scene_prompt = f"{as_text(scene_meta.get('location'))}，{as_text(scene_meta.get('time'))}，{as_text(scene_meta.get('description'))}"

    style_tags = normalize_style_tags(scene_prompt_data.get("style_tags"))
    negative_prompt = as_text(scene_prompt_data.get("negative_prompt"))

    parts = [scene_prompt]
    if style_tags:
        parts.append("风格标签：" + "，".join(style_tags))
    if negative_prompt:
        parts.append("避免：" + negative_prompt)
    return sanitize_scene_prompt("。".join([p for p in parts if p]))


def sanitize_scene_prompt(text: str) -> str:
    replacements = {
        "血迹": "磨损痕迹",
        "鲜血": "污渍",
        "诡异": "未知生物",
        "追杀": "追逐",
        "尸体": "残留物",
        "战火纷飞": "紧张氛围",
        "炮口对准": "重型设备陈列",
        "斩杀": "对抗",
        "压抑": "肃穆",
    }
    safe_text = text
    for src, dst in replacements.items():
        safe_text = safe_text.replace(src, dst)
    return safe_text


def build_neutral_fallback_prompt(scene_meta: dict[str, Any]) -> str:
    location = as_text(scene_meta.get("location")) or "城市街道"
    time_text = as_text(scene_meta.get("time")) or "日外"
    return (
        f"{location}，{time_text}，无人环境场景，二次元动漫背景风格，赛璐璐质感，高细节材质，"
        "建筑与街道空间关系清晰，色彩分层明确，氛围肃穆，干净画面，无角色主体。"
    )


def post_json(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: int) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url=url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="ignore")
    return extract_json_object(raw)


def extract_image_url(result: dict[str, Any]) -> str:
    candidates: list[dict[str, Any]] = []
    if isinstance(result.get("results"), list):
        candidates = result["results"]
    elif isinstance(result.get("data"), dict) and isinstance(result["data"].get("results"), list):
        candidates = result["data"]["results"]

    if candidates and isinstance(candidates[0], dict):
        return as_text(candidates[0].get("url"))
    return ""


def request_image_url(
    api_key: str,
    prompt: str,
    image_model: str,
    aspect_ratio: str,
    image_size: str,
    timeout_sec: int,
    retries: int,
) -> str:
    endpoint = "https://grsai.dakka.com.cn/v1/draw/nano-banana"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "model": image_model,
        "prompt": prompt,
        "aspectRatio": aspect_ratio,
        "imageSize": image_size,
        "shutProgress": True,
    }

    last_error = ""
    for _ in range(max(1, retries + 1)):
        try:
            result = post_json(endpoint, payload, headers, timeout=timeout_sec)
            image_url = extract_image_url(result)
            if image_url:
                return image_url
            last_error = as_text(result.get("msg")) or as_text(result.get("error")) or "未拿到图片链接"
        except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            last_error = str(exc)
    raise RuntimeError(f"生图失败: {last_error}")


def download_file(url: str, output_path: Path, timeout_sec: int) -> None:
    req = urllib.request.Request(url=url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
        data = resp.read()
    output_path.write_bytes(data)


def main() -> None:
    parser = argparse.ArgumentParser(description="读取 scene_prompt.json 并生成场景基础图到 assets/scenes/base")
    parser.add_argument("--project-root", default="test-project", help="短剧项目目录")
    parser.add_argument("--analysis-dir", default="script_analysis", help="分析目录（相对 project-root）")
    parser.add_argument("--output-dir", default="assets/scenes/base", help="场景图输出目录（相对 project-root）")
    parser.add_argument("--env-file", default=".env", help="环境变量文件（相对仓库根目录）")
    parser.add_argument("--episode", type=int, default=0, help="仅处理指定集（如 1），默认 0 表示全部")
    parser.add_argument("--scene-id", default="", help="仅处理指定场（如 S01），默认全部")
    parser.add_argument("--image-model", default="nano-banana-fast", help="生图模型名")
    parser.add_argument("--aspect-ratio", default="16:9", help="生图比例，默认 16:9")
    parser.add_argument("--image-size", default="1K", help="生图尺寸，默认 1K")
    parser.add_argument("--image-ext", default="png", help="图片扩展名，默认 png")
    parser.add_argument("--timeout-sec", type=int, default=150, help="请求超时秒数")
    parser.add_argument("--retries", type=int, default=1, help="生图失败重试次数")
    parser.add_argument(
        "--allow-partial-success",
        action="store_true",
        help="允许部分场景生图失败时仍返回成功退出码",
    )
    args = parser.parse_args()

    repo_root = Path.cwd()
    project_root = (repo_root / args.project_root).resolve()
    analysis_root = (project_root / args.analysis_dir).resolve()
    output_root = (project_root / args.output_dir).resolve()
    env_path = (repo_root / args.env_file).resolve()

    load_env_file(env_path)
    banana_api_key = as_text(os.environ.get("NANO_BANANA_API_KEY"))
    if not banana_api_key:
        raise RuntimeError("未读取到 NANO_BANANA_API_KEY，请检查 .env")

    project_meta_path = analysis_root / "project_meta.json"
    if not project_meta_path.exists():
        raise FileNotFoundError(f"缺少项目元信息文件: {project_meta_path}")
    project_meta = read_json(project_meta_path)
    if not isinstance(project_meta, dict):
        raise ValueError(f"project_meta.json 格式错误: {project_meta_path}")

    total_episodes = get_total_episodes(project_meta)
    output_root.mkdir(parents=True, exist_ok=True)

    success_count = 0
    failed: list[str] = []

    for ep_index in range(1, total_episodes + 1):
        if args.episode and ep_index != args.episode:
            continue

        ep_dir = analysis_root / f"ep_{ep_index:02d}"
        episode_meta_path = ep_dir / f"episodes_{ep_index:02d}.json"
        scenes_path = ep_dir / "scenes.json"
        if not episode_meta_path.exists() or not scenes_path.exists():
            continue

        episode_meta = read_json(episode_meta_path)
        episode_id = as_text(episode_meta.get("episode_id")) or f"EP{ep_index:02d}"
        scenes = read_json(scenes_path)
        if not isinstance(scenes, list):
            continue

        for scene in scenes:
            if not isinstance(scene, dict):
                continue
            scene_id = as_text(scene.get("scene_id"))
            if not scene_id:
                continue
            if args.scene_id and scene_id != args.scene_id:
                continue

            scene_dir = ep_dir / f"scene_{scene_id}"
            prompt_path = scene_dir / "scene_prompt.json"
            if prompt_path.exists():
                scene_prompt_data = read_json(prompt_path)
                if not isinstance(scene_prompt_data, dict):
                    scene_prompt_data = {}
            else:
                scene_prompt_data = {}

            final_prompt = compose_image_prompt(scene_prompt_data=scene_prompt_data, scene_meta=scene)
            try:
                image_url = request_image_url(
                    api_key=banana_api_key,
                    prompt=final_prompt,
                    image_model=args.image_model,
                    aspect_ratio=args.aspect_ratio,
                    image_size=args.image_size,
                    timeout_sec=args.timeout_sec,
                    retries=args.retries,
                )
                file_name = f"{episode_id}_{scene_id}.{args.image_ext.strip('.')}"
                output_path = output_root / file_name
                download_file(image_url, output_path, timeout_sec=args.timeout_sec)
                print(f"已覆盖写入: {output_path}")
                success_count += 1
            except Exception as exc:
                err_text = str(exc)
                if "violate our policies" in err_text.lower():
                    try:
                        neutral_prompt = build_neutral_fallback_prompt(scene)
                        image_url = request_image_url(
                            api_key=banana_api_key,
                            prompt=neutral_prompt,
                            image_model=args.image_model,
                            aspect_ratio=args.aspect_ratio,
                            image_size=args.image_size,
                            timeout_sec=args.timeout_sec,
                            retries=args.retries,
                        )
                        file_name = f"{episode_id}_{scene_id}.{args.image_ext.strip('.')}"
                        output_path = output_root / file_name
                        download_file(image_url, output_path, timeout_sec=args.timeout_sec)
                        print(f"已覆盖写入(降级提示词): {output_path}")
                        success_count += 1
                        continue
                    except Exception as retry_exc:
                        failed.append(f"{episode_id}-{scene_id}: {retry_exc}")
                        continue
                failed.append(f"{episode_id}-{scene_id}: {exc}")

    print(f"完成。成功 {success_count}，失败 {len(failed)}")
    if failed:
        for item in failed:
            print(f"失败 - {item}")
        if not args.allow_partial_success:
            raise RuntimeError("存在场景生图失败，任务未完全成功")


if __name__ == "__main__":
    main()
