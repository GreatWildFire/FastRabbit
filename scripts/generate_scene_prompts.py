import argparse
import json
import os
import re
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


def parse_scene_num(scene_id: str) -> int:
    if isinstance(scene_id, str) and scene_id.startswith("S") and scene_id[1:].isdigit():
        return int(scene_id[1:])
    return 0


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


def extract_scene_blocks(script_text: str) -> dict[tuple[int, int], str]:
    lines = script_text.splitlines()
    pattern = re.compile(r"^\s*(\d+)-(\d+)[：:]\s*(.*)$")
    headers: list[tuple[int, int, int]] = []
    for idx, line in enumerate(lines):
        match = pattern.match(line)
        if not match:
            continue
        headers.append((int(match.group(1)), int(match.group(2)), idx))

    blocks: dict[tuple[int, int], str] = {}
    for pos, (ep_num, sc_num, start_idx) in enumerate(headers):
        end_idx = headers[pos + 1][2] if pos + 1 < len(headers) else len(lines)
        blocks[(ep_num, sc_num)] = "\n".join(lines[start_idx:end_idx]).strip()
    return blocks


def normalize_style_tags(value: Any) -> list[str]:
    if isinstance(value, list):
        return [as_text(item) for item in value if as_text(item)]
    if isinstance(value, str):
        text = value.replace("，", ",")
        return [item.strip() for item in text.split(",") if item.strip()]
    return []


def normalize_characters(value: Any) -> list[str]:
    if isinstance(value, list):
        return [as_text(item) for item in value if as_text(item)]
    if isinstance(value, str):
        text = value.replace("，", ",")
        return [item.strip() for item in text.split(",") if item.strip()]
    return []


def remove_character_mentions(text: str, character_names: list[str]) -> str:
    cleaned = text
    for name in character_names:
        if not name:
            continue
        cleaned = cleaned.replace(name, "")
    cleaned = re.sub(r"[，,\s]{2,}", "，", cleaned)
    cleaned = cleaned.strip("，, 。")
    return cleaned


def normalize_prompt_payload(payload: dict[str, Any], scene_meta: dict[str, Any]) -> dict[str, Any]:
    location = as_text(scene_meta.get("location"))
    time_text = as_text(scene_meta.get("time"))
    desc = as_text(scene_meta.get("description"))
    scene_characters = normalize_characters(scene_meta.get("characters"))

    scene_prompt = as_text(payload.get("scene_prompt"))
    if not scene_prompt:
        scene_prompt = f"{location}，{time_text}，{desc}，二次元动漫背景风格，色彩分层清晰，干净构图。"
    scene_prompt = remove_character_mentions(scene_prompt, scene_characters)
    if not scene_prompt:
        scene_prompt = f"{location}，{time_text}，环境空间建立镜头，二次元动漫背景风格，高细节，干净构图。"

    negative_prompt = as_text(payload.get("negative_prompt"))
    if not negative_prompt:
        negative_prompt = "低清晰度，模糊，畸变，多余人物，主要角色入镜，错位光影，水印，文字。"
    else:
        negative_prompt = remove_character_mentions(negative_prompt, scene_characters)
        if "主要角色入镜" not in negative_prompt:
            negative_prompt = f"{negative_prompt}，主要角色入镜".strip("，")

    style_tags = normalize_style_tags(payload.get("style_tags"))
    if not style_tags:
        style_tags = ["动漫风格", "二次元背景", "高细节"]

    return {
        "scene_prompt": scene_prompt,
        "negative_prompt": negative_prompt,
        "style_tags": style_tags,
    }


def build_user_prompt(
    episode_id: str,
    scene_meta: dict[str, Any],
    episode_script_full: str,
    scene_excerpt: str,
) -> str:
    return (
        f"目标集: {episode_id}\n"
        f"目标场: {json.dumps(scene_meta, ensure_ascii=False)}\n\n"
        "【本集完整剧本】\n"
        f"{episode_script_full}\n\n"
        "【当前场原文片段】\n"
        f"{scene_excerpt}\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="为每个 scene 生成场景图提示词并写入 scene 目录")
    parser.add_argument("--project-root", default="test-project", help="短剧项目目录")
    parser.add_argument("--analysis-dir", default="script_analysis", help="分析目录（相对 project-root）")
    parser.add_argument("--script-file", default="测试剧本.txt", help="剧本文件路径（相对仓库根目录）")
    parser.add_argument(
        "--prompt-file",
        default="prompts/scene_image_prompt_system.txt",
        help="系统提示词文件（相对仓库根目录）",
    )
    parser.add_argument("--env-file", default=".env", help="环境变量文件（相对仓库根目录）")
    parser.add_argument("--model", default="deepseek-v4-flash", help="模型名称")
    parser.add_argument("--episode", type=int, default=0, help="仅处理指定集（如 1），默认 0 表示全部")
    parser.add_argument("--scene-id", default="", help="仅处理指定场（如 S01），默认全部")
    args = parser.parse_args()

    repo_root = Path.cwd()
    project_root = (repo_root / args.project_root).resolve()
    analysis_root = (project_root / args.analysis_dir).resolve()
    script_path = (repo_root / args.script_file).resolve()
    prompt_path = (repo_root / args.prompt_file).resolve()
    env_path = (repo_root / args.env_file).resolve()

    load_env_file(env_path)
    api_key = as_text(os.environ.get("DEEPSEEK_API_KEY"))
    if not api_key:
        raise RuntimeError("未读取到 DEEPSEEK_API_KEY，请检查 .env")
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
    scene_blocks = extract_scene_blocks(script_text)
    system_prompt = prompt_path.read_text(encoding="utf-8")
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

    for ep_index in range(1, total_episodes + 1):
        if args.episode and ep_index != args.episode:
            continue

        ep_dir = analysis_root / f"ep_{ep_index:02d}"
        episode_meta_path = ep_dir / f"episodes_{ep_index:02d}.json"
        scenes_path = ep_dir / "scenes.json"
        if not episode_meta_path.exists() or not scenes_path.exists():
            continue

        episode_meta = read_json(episode_meta_path)
        if not isinstance(episode_meta, dict):
            continue
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

            scene_num = parse_scene_num(scene_id)
            scene_excerpt = scene_blocks.get((ep_index, scene_num), "")
            user_prompt = build_user_prompt(
                episode_id=episode_id,
                scene_meta=scene,
                episode_script_full=script_text,
                scene_excerpt=scene_excerpt,
            )
            response = client.chat.completions.create(
                model=args.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                stream=False,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content or "{}"
            payload = extract_json_object(content)
            normalized = normalize_prompt_payload(payload=payload, scene_meta=scene)

            scene_dir = ep_dir / f"scene_{scene_id}"
            scene_dir.mkdir(parents=True, exist_ok=True)
            prompt_path_out = scene_dir / "scene_prompt.json"
            prompt_path_out.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"已覆盖写入: {prompt_path_out}")


if __name__ == "__main__":
    main()
