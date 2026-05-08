import argparse
import json
import os
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


def normalize_episode_id(value: str, index: int) -> str:
    if isinstance(value, str) and value.startswith("EP") and len(value) == 4 and value[2:].isdigit():
        return value
    return f"EP{index:02d}"


def normalize_scene_id(value: str, index: int) -> str:
    if isinstance(value, str) and value.startswith("S") and len(value) == 3 and value[1:].isdigit():
        return value
    return f"S{index:02d}"


def as_string(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if value is None:
        return ""
    return str(value).strip()


def as_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [as_string(item) for item in value if as_string(item)]
    if isinstance(value, str):
        text = value.replace("，", ",")
        return [item.strip() for item in text.split(",") if item.strip()]
    return []


def normalize_payload(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    raw_episodes = payload.get("episodes", [])
    raw_scenes_by_episode = payload.get("scenes_by_episode", {})

    if not isinstance(raw_episodes, list):
        raw_episodes = []
    if not isinstance(raw_scenes_by_episode, dict):
        raw_scenes_by_episode = {}

    episodes: list[dict[str, Any]] = []
    scenes_by_episode: dict[str, list[dict[str, Any]]] = {}

    for ep_index, item in enumerate(raw_episodes, start=1):
        if not isinstance(item, dict):
            continue
        episode_id = normalize_episode_id(as_string(item.get("episode_id")), ep_index)
        title = as_string(item.get("title")) or f"第{ep_index}集"

        raw_scenes = raw_scenes_by_episode.get(episode_id, [])
        if not isinstance(raw_scenes, list):
            raw_scenes = []

        normalized_scenes: list[dict[str, Any]] = []
        scene_ids: list[str] = []
        for sc_index, scene in enumerate(raw_scenes, start=1):
            if not isinstance(scene, dict):
                continue
            scene_id = normalize_scene_id(as_string(scene.get("scene_id")), sc_index)
            scene_ids.append(scene_id)
            normalized_scenes.append(
                {
                    "scene_id": scene_id,
                    "location": as_string(scene.get("location")),
                    "time": as_string(scene.get("time")),
                    "characters": as_string_list(scene.get("characters")),
                    "description": as_string(scene.get("description")),
                }
            )

        episodes.append(
            {
                "episode_id": episode_id,
                "title": title,
                "scenes": scene_ids,
            }
        )
        scenes_by_episode[episode_id] = normalized_scenes

    if not episodes:
        episodes = [{"episode_id": "EP01", "title": "第一集", "scenes": []}]
        scenes_by_episode = {"EP01": []}

    return episodes, scenes_by_episode


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
        candidate = text[start : end + 1]
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("LLM 返回内容不是有效 JSON 对象")


def read_project_meta(project_meta_path: Path) -> dict[str, Any]:
    if not project_meta_path.exists():
        return {}
    try:
        data = json.loads(project_meta_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        return {}
    return {}


def get_total_episodes(project_meta: dict[str, Any]) -> int:
    value = project_meta.get("total_episodes", 1)
    if isinstance(value, int) and value > 0:
        return value
    text = as_string(value)
    if text.isdigit():
        parsed = int(text)
        if parsed > 0:
            return parsed
    return 1


def ensure_episode_dirs(output_root: Path, total_episodes: int) -> None:
    for index in range(1, total_episodes + 1):
        (output_root / f"ep_{index:02d}").mkdir(parents=True, exist_ok=True)


def scene_shots_template() -> list[dict[str, Any]]:
    return []


def ensure_scene_dirs(ep_dir: Path, scenes: list[dict[str, Any]]) -> None:
    for scene in scenes:
        scene_id = as_string(scene.get("scene_id"))
        if not scene_id:
            continue
        scene_dir = ep_dir / f"scene_{scene_id}"
        scene_dir.mkdir(parents=True, exist_ok=True)
        shots_path = scene_dir / "shots.json"
        if not shots_path.exists():
            shots_path.write_text(json.dumps(scene_shots_template(), ensure_ascii=False, indent=2), encoding="utf-8")


def parse_episode_num(episode_id: str) -> int:
    if isinstance(episode_id, str) and episode_id.startswith("EP") and episode_id[2:].isdigit():
        return int(episode_id[2:])
    return 0


def build_episode_index(episodes: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    index_map: dict[int, dict[str, Any]] = {}
    for item in episodes:
        if not isinstance(item, dict):
            continue
        episode_num = parse_episode_num(as_string(item.get("episode_id")))
        if episode_num > 0:
            index_map[episode_num] = item
    return index_map


def main() -> None:
    parser = argparse.ArgumentParser(description="基于剧本生成分集元数据与场景数据（通用脚本）")
    parser.add_argument(
        "--project-root",
        default=".",
        help="短剧项目目录（默认当前目录）",
    )
    parser.add_argument(
        "--input",
        default="测试剧本.txt",
        help="输入剧本文件（相对 project-root，默认：测试剧本.txt）",
    )
    parser.add_argument(
        "--output-root",
        default="script_analysis",
        help="输出目录（相对 project-root，默认：script_analysis）",
    )
    parser.add_argument(
        "--project-meta",
        default="project_meta.json",
        help="项目元信息文件（相对 output-root，默认：project_meta.json）",
    )
    parser.add_argument(
        "--env-file",
        default=".env",
        help="环境变量文件（相对仓库根目录，默认：.env）",
    )
    parser.add_argument(
        "--system-prompt",
        default="prompts/script_analysis_system_prompt.txt",
        help="系统提示词文件（相对仓库根目录，默认：prompts/script_analysis_system_prompt.txt）",
    )
    parser.add_argument(
        "--model",
        default="deepseek-v4-flash",
        help="模型名称（默认：deepseek-v4-flash）",
    )
    args = parser.parse_args()

    repo_root = Path.cwd()
    project_root = (repo_root / args.project_root).resolve()
    input_path = (project_root / args.input).resolve()
    output_root = (project_root / args.output_root).resolve()
    project_meta_path = (output_root / args.project_meta).resolve()
    env_path = (repo_root / args.env_file).resolve()
    prompt_path = (repo_root / args.system_prompt).resolve()

    load_env_file(env_path)
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("未读取到 DEEPSEEK_API_KEY，请检查 .env")

    if not input_path.exists():
        raise FileNotFoundError(f"输入文件不存在: {input_path}")
    if not prompt_path.exists():
        raise FileNotFoundError(f"系统提示词文件不存在: {prompt_path}")

    script_text = input_path.read_text(encoding="utf-8")
    system_prompt = prompt_path.read_text(encoding="utf-8")

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    response = client.chat.completions.create(
        model=args.model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": script_text},
        ],
        stream=False,
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content or "{}"
    payload = extract_json_object(content)
    episodes, scenes_by_episode = normalize_payload(payload)

    output_root.mkdir(parents=True, exist_ok=True)
    project_meta = read_project_meta(project_meta_path)
    total_episodes = get_total_episodes(project_meta)
    ensure_episode_dirs(output_root, total_episodes)
    indexed_episodes = build_episode_index(episodes)

    root_episodes_path = output_root / "episodes.json"
    if root_episodes_path.exists():
        root_episodes_path.unlink()

    max_episode_num = max(total_episodes, max(indexed_episodes.keys(), default=0))
    for episode_num in range(1, max_episode_num + 1):
        episode = indexed_episodes.get(
            episode_num,
            {
                "episode_id": f"EP{episode_num:02d}",
                "title": f"第{episode_num}集",
                "scenes": [],
            },
        )
        episode_id = as_string(episode.get("episode_id")) or f"EP{episode_num:02d}"
        ep_dir = output_root / f"ep_{episode_num:02d}"
        ep_dir.mkdir(parents=True, exist_ok=True)

        episode_meta_path = ep_dir / f"episodes_{episode_num:02d}.json"
        episode_meta_path.write_text(json.dumps(episode, ensure_ascii=False, indent=2), encoding="utf-8")

        scenes_path = ep_dir / "scenes.json"
        scenes = scenes_by_episode.get(episode_id, [])
        scenes_path.write_text(json.dumps(scenes, ensure_ascii=False, indent=2), encoding="utf-8")
        ensure_scene_dirs(ep_dir, scenes)

        print(f"已覆盖写入: {episode_meta_path}")
        print(f"已覆盖写入: {scenes_path}")

    for index in range(1, total_episodes + 1):
        ep_dir = output_root / f"ep_{index:02d}"
        print(f"已检查目录: {ep_dir}")


if __name__ == "__main__":
    main()
