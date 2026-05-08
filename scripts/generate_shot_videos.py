import argparse
import base64
import json
import mimetypes
import os
import re
import time
import urllib.request
from pathlib import Path
from typing import Any

from openai import OpenAI


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
    raise ValueError("LLM 返回内容不是有效 JSON 对象")


def sanitize_prompt(text: str) -> str:
    replacements = {
        "血迹": "磨损痕迹",
        "鲜血": "污渍",
        "尸体": "残留物",
        "追杀": "追逐",
        "斩杀": "对抗",
    }
    result = text
    for src, dst in replacements.items():
        result = result.replace(src, dst)
    return result


def build_shot_user_prompt(
    episode_id: str,
    scene_meta: dict[str, Any],
    shot: dict[str, Any],
    script_text: str,
    scene_image_exists: bool,
    character_image_names: list[str],
    has_previous_last_frame: bool,
) -> str:
    return (
        f"目标集: {episode_id}\n"
        f"目标场: {json.dumps(scene_meta, ensure_ascii=False)}\n"
        f"目标镜头: {json.dumps(shot, ensure_ascii=False)}\n"
        f"可用场景参考图: {'有' if scene_image_exists else '无'}\n"
        f"可用角色参考图: {character_image_names}\n"
        f"是否有上一镜头尾帧: {'是' if has_previous_last_frame else '否'}\n\n"
        "【本集完整剧本】\n"
        f"{script_text}\n"
    )


def generate_video_prompt(
    llm_client: OpenAI,
    llm_model: str,
    system_prompt: str,
    episode_id: str,
    scene_meta: dict[str, Any],
    shot: dict[str, Any],
    script_text: str,
    scene_image_exists: bool,
    character_image_names: list[str],
    has_previous_last_frame: bool,
) -> dict[str, Any]:
    user_prompt = build_shot_user_prompt(
        episode_id=episode_id,
        scene_meta=scene_meta,
        shot=shot,
        script_text=script_text,
        scene_image_exists=scene_image_exists,
        character_image_names=character_image_names,
        has_previous_last_frame=has_previous_last_frame,
    )
    response = llm_client.chat.completions.create(
        model=llm_model,
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        stream=False,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content or "{}"
    payload = extract_json_object(content)

    prompt = as_text(payload.get("video_prompt"))
    if not prompt:
        prompt = f"{as_text(shot.get('type'))}镜头，{as_text(shot.get('action'))}，电影感，写实风格。"
    prompt = sanitize_prompt(prompt)

    negative_prompt = as_text(payload.get("negative_prompt"))
    if not negative_prompt:
        negative_prompt = "低清晰度，模糊，畸变，过度抖动，文字水印。"

    duration = payload.get("duration", 5)
    if not isinstance(duration, int) or duration < 4 or duration > 8:
        duration = 5

    ratio = as_text(payload.get("ratio")) or "16:9"
    if ratio not in {"16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "adaptive"}:
        ratio = "16:9"

    return {"video_prompt": prompt, "negative_prompt": negative_prompt, "duration": duration, "ratio": ratio}


def create_ark_client(ark_api_key: str):
    try:
        from volcenginesdkarkruntime import Ark  # type: ignore
    except ImportError as exc:
        raise RuntimeError("缺少 volcengine ark sdk，请先安装: pip install 'volcengine-python-sdk[ark]'") from exc
    return Ark(base_url="https://ark.cn-beijing.volces.com/api/v3", api_key=ark_api_key)


def download_file(url: str, output_path: Path) -> None:
    req = urllib.request.Request(url=url, method="GET")
    with urllib.request.urlopen(req, timeout=180) as resp:
        output_path.write_bytes(resp.read())


def to_data_url(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    if not mime:
        mime = "image/png"
    raw = path.read_bytes()
    encoded = base64.b64encode(raw).decode("utf-8")
    return f"data:{mime};base64,{encoded}"


def normalize_characters(value: Any) -> list[str]:
    if isinstance(value, list):
        return [as_text(v) for v in value if as_text(v)]
    if isinstance(value, str):
        text = value.replace("，", ",")
        return [item.strip() for item in text.split(",") if item.strip()]
    return []


def parse_shot_sort_key(shot_id: str) -> tuple[int, int]:
    m = re.match(r"^S(\d+)_SH(\d+)$", shot_id)
    if not m:
        return (10**9, 10**9)
    return (int(m.group(1)), int(m.group(2)))


def build_reference_content_items(
    scene_image_path: Path | None,
    character_image_paths: list[Path],
    previous_last_frame_url: str,
    use_last_frame_chain: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    content_items: list[dict[str, Any]] = []
    refs: list[dict[str, str]] = []

    if use_last_frame_chain and previous_last_frame_url:
        content_items.append(
            {
                "type": "image_url",
                "image_url": {"url": previous_last_frame_url},
                "role": "reference_image",
            }
        )
        refs.append({"type": "last_frame_url", "value": previous_last_frame_url})

    if scene_image_path and scene_image_path.exists():
        scene_data_url = to_data_url(scene_image_path)
        content_items.append(
            {
                "type": "image_url",
                "image_url": {"url": scene_data_url},
                "role": "reference_image",
            }
        )
        refs.append({"type": "scene_image", "value": str(scene_image_path)})

    for char_path in character_image_paths:
        if not char_path.exists():
            continue
        char_data_url = to_data_url(char_path)
        content_items.append(
            {
                "type": "image_url",
                "image_url": {"url": char_data_url},
                "role": "reference_image",
            }
        )
        refs.append({"type": "character_image", "value": str(char_path)})

    return content_items, refs


def resolve_scene_image_path(project_root: Path, episode_id: str, scene_id: str) -> Path:
    return project_root / "assets" / "scenes" / "base" / f"{episode_id}_{scene_id}.png"


def resolve_character_image_paths(project_root: Path, shot: dict[str, Any], max_refs: int) -> list[Path]:
    base_dir = project_root / "assets" / "characters" / "base"
    names = normalize_characters(shot.get("characters"))
    paths: list[Path] = []
    for name in names:
        path = base_dir / f"{name}.png"
        if path.exists():
            paths.append(path)
        if len(paths) >= max_refs:
            break
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="根据 shots 生成镜头视频并写入 assets/shots/{shot_id}")
    parser.add_argument("--project-root", default="test-project", help="短剧项目目录")
    parser.add_argument("--analysis-dir", default="script_analysis", help="分析目录（相对 project-root）")
    parser.add_argument("--shots-output-dir", default="assets/shots", help="镜头资产输出目录（相对 project-root）")
    parser.add_argument("--script-file", default="测试剧本.txt", help="剧本文件（相对仓库根目录）")
    parser.add_argument("--env-file", default=".env", help="环境变量文件（相对仓库根目录）")
    parser.add_argument("--prompt-file", default="prompts/shot_video_prompt_system.txt", help="镜头视频提示词系统文件")
    parser.add_argument("--llm-model", default="deepseek-v4-flash", help="用于整理提示词的 LLM")
    parser.add_argument("--video-model", default="doubao-seedance-2-0-250528", help="视频模型 ID")
    parser.add_argument("--episode", type=int, default=0, help="只处理指定集，0 表示全部")
    parser.add_argument("--scene-id", default="", help="只处理指定场，如 S01")
    parser.add_argument("--shot-id", default="", help="只处理指定镜头，如 S01_SH01")
    parser.add_argument("--poll-interval", type=int, default=10, help="轮询间隔秒")
    parser.add_argument("--max-wait-sec", type=int, default=900, help="单镜头最长等待秒数")
    parser.add_argument("--max-character-refs", type=int, default=2, help="每镜头最多使用多少个角色参考图")
    parser.add_argument("--disable-last-frame-chain", action="store_true", help="禁用同场景尾帧衔接")
    parser.add_argument("--dry-run", action="store_true", help="仅生成提示词和资产计划，不调用视频 API")
    parser.add_argument("--allow-partial-success", action="store_true", help="允许部分镜头失败仍返回成功退出码")
    args = parser.parse_args()

    repo_root = Path.cwd()
    project_root = (repo_root / args.project_root).resolve()
    analysis_root = (project_root / args.analysis_dir).resolve()
    shots_root = (project_root / args.shots_output_dir).resolve()
    script_path = (repo_root / args.script_file).resolve()
    env_path = (repo_root / args.env_file).resolve()
    prompt_path = (repo_root / args.prompt_file).resolve()

    load_env_file(env_path)
    deepseek_key = as_text(os.environ.get("DEEPSEEK_API_KEY"))
    ark_key = as_text(os.environ.get("ARK_API_KEY"))
    if not deepseek_key:
        raise RuntimeError("未读取到 DEEPSEEK_API_KEY，请检查 .env")
    if not ark_key and not args.dry_run:
        raise RuntimeError("未读取到 ARK_API_KEY，请检查 .env")
    if not script_path.exists():
        raise FileNotFoundError(f"剧本文件不存在: {script_path}")
    if not prompt_path.exists():
        raise FileNotFoundError(f"提示词文件不存在: {prompt_path}")

    project_meta_path = analysis_root / "project_meta.json"
    if not project_meta_path.exists():
        raise FileNotFoundError(f"缺少项目元信息文件: {project_meta_path}")
    project_meta = read_json(project_meta_path)
    if not isinstance(project_meta, dict):
        raise ValueError(f"project_meta.json 格式错误: {project_meta_path}")
    total_episodes = get_total_episodes(project_meta)

    script_text = script_path.read_text(encoding="utf-8")
    system_prompt = prompt_path.read_text(encoding="utf-8")
    shots_root.mkdir(parents=True, exist_ok=True)

    llm_client = OpenAI(api_key=deepseek_key, base_url="https://api.deepseek.com")
    ark_client = create_ark_client(ark_key) if not args.dry_run else None

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

        scene_map: dict[str, dict[str, Any]] = {}
        for scene in scenes:
            if isinstance(scene, dict):
                sid = as_text(scene.get("scene_id"))
                if sid:
                    scene_map[sid] = scene

        for scene_id, scene_meta in scene_map.items():
            if args.scene_id and scene_id != args.scene_id:
                continue

            shots_path = ep_dir / f"scene_{scene_id}" / "shots.json"
            if not shots_path.exists():
                continue
            shots = read_json(shots_path)
            if not isinstance(shots, list):
                continue
            valid_shots = [s for s in shots if isinstance(s, dict) and as_text(s.get("shot_id"))]
            valid_shots.sort(key=lambda s: parse_shot_sort_key(as_text(s.get("shot_id"))))

            previous_last_frame_url = ""
            scene_image_path = resolve_scene_image_path(project_root=project_root, episode_id=episode_id, scene_id=scene_id)

            for shot in valid_shots:
                shot_id = as_text(shot.get("shot_id"))
                if args.shot_id and shot_id != args.shot_id:
                    continue

                shot_dir = shots_root / shot_id
                shot_dir.mkdir(parents=True, exist_ok=True)

                character_paths = resolve_character_image_paths(
                    project_root=project_root,
                    shot=shot,
                    max_refs=max(0, args.max_character_refs),
                )
                character_names = [p.stem for p in character_paths]

                try:
                    prompt_data = generate_video_prompt(
                        llm_client=llm_client,
                        llm_model=args.llm_model,
                        system_prompt=system_prompt,
                        episode_id=episode_id,
                        scene_meta=scene_meta,
                        shot=shot,
                        script_text=script_text,
                        scene_image_exists=scene_image_path.exists(),
                        character_image_names=character_names,
                        has_previous_last_frame=bool(previous_last_frame_url),
                    )

                    content_items: list[dict[str, Any]] = [
                        {"type": "text", "text": f"{prompt_data['video_prompt']}。避免：{prompt_data['negative_prompt']}"}
                    ]
                    ref_items, ref_plan = build_reference_content_items(
                        scene_image_path=scene_image_path if scene_image_path.exists() else None,
                        character_image_paths=character_paths,
                        previous_last_frame_url=previous_last_frame_url,
                        use_last_frame_chain=not args.disable_last_frame_chain,
                    )
                    content_items.extend(ref_items)

                    prompt_json_path = shot_dir / "video_prompt.json"
                    prompt_json_path.write_text(json.dumps(prompt_data, ensure_ascii=False, indent=2), encoding="utf-8")
                    print(f"已覆盖写入: {prompt_json_path}")

                    asset_plan_path = shot_dir / "asset_plan.json"
                    asset_plan_path.write_text(
                        json.dumps(
                            {
                                "episode_id": episode_id,
                                "scene_id": scene_id,
                                "shot_id": shot_id,
                                "references": ref_plan,
                                "ratio": prompt_data["ratio"],
                                "duration": prompt_data["duration"],
                                "use_last_frame_chain": not args.disable_last_frame_chain,
                            },
                            ensure_ascii=False,
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                    print(f"已覆盖写入: {asset_plan_path}")

                    if args.dry_run:
                        success_count += 1
                        continue

                    create_result = ark_client.content_generation.tasks.create(
                        model=args.video_model,
                        content=content_items,
                        ratio=prompt_data["ratio"],
                        duration=prompt_data["duration"],
                        generate_audio=False,
                        watermark=False,
                        return_last_frame=not args.disable_last_frame_chain,
                    )
                    task_id = as_text(getattr(create_result, "id", ""))
                    if not task_id:
                        raise RuntimeError("视频任务创建失败，未返回 task id")

                    task_meta_path = shot_dir / "video_task.json"
                    task_meta_path.write_text(
                        json.dumps(
                            {
                                "task_id": task_id,
                                "model": args.video_model,
                                "ratio": prompt_data["ratio"],
                                "duration": prompt_data["duration"],
                            },
                            ensure_ascii=False,
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                    print(f"已覆盖写入: {task_meta_path}")

                    started = time.time()
                    video_url = ""
                    last_frame_url = ""
                    while True:
                        result = ark_client.content_generation.tasks.get(task_id=task_id)
                        status = as_text(getattr(result, "status", ""))
                        if status == "succeeded":
                            content_obj = getattr(result, "content", None)
                            video_url = as_text(getattr(content_obj, "video_url", "")) if content_obj else ""
                            last_frame_url = as_text(getattr(content_obj, "last_frame_url", "")) if content_obj else ""
                            break
                        if status in {"failed", "expired"}:
                            error = as_text(getattr(result, "error", "unknown error"))
                            raise RuntimeError(f"任务状态 {status}: {error}")
                        if time.time() - started > args.max_wait_sec:
                            raise RuntimeError("视频任务轮询超时")
                        time.sleep(max(1, args.poll_interval))

                    if not video_url:
                        raise RuntimeError("任务成功但未返回 video_url")

                    output_video_path = shot_dir / f"{shot_id}.mp4"
                    download_file(video_url, output_video_path)
                    print(f"已覆盖写入: {output_video_path}")

                    if last_frame_url:
                        previous_last_frame_url = last_frame_url
                        last_frame_meta = shot_dir / "last_frame.json"
                        last_frame_meta.write_text(
                            json.dumps({"last_frame_url": last_frame_url}, ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
                        print(f"已覆盖写入: {last_frame_meta}")

                    success_count += 1
                except Exception as exc:
                    failed.append(f"{episode_id}-{scene_id}-{shot_id}: {exc}")

    print(f"完成。成功 {success_count}，失败 {len(failed)}")
    if failed:
        for item in failed:
            print(f"失败 - {item}")
        if not args.allow_partial_success:
            raise RuntimeError("存在镜头视频生成失败，任务未完全成功")


if __name__ == "__main__":
    main()
