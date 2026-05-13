"""IO 公共函数，从 scripts/ 中抽取。"""

import base64
import json
import mimetypes
import os
import re
import urllib.request
from pathlib import Path
from typing import Any

from .text import as_text, parse_episode_num


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


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_project_meta(project_meta_path: Path) -> dict[str, Any]:
    if not project_meta_path.exists():
        return {}
    try:
        data = read_json(project_meta_path)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        return {}
    return {}


def get_total_episodes(project_meta: dict[str, Any]) -> int:
    value = project_meta.get("total_episodes", 1)
    if isinstance(value, int) and value > 0:
        return value
    text = as_text(value)
    if text.isdigit():
        parsed = int(text)
        if parsed > 0:
            return parsed
    return 1


def ensure_episode_dirs(output_root: Path, total_episodes: int) -> None:
    for index in range(1, total_episodes + 1):
        (output_root / f"ep_{index:02d}").mkdir(parents=True, exist_ok=True)


def ensure_scene_dirs(ep_dir: Path, scenes: list[dict[str, Any]]) -> None:
    for scene in scenes:
        scene_id = as_text(scene.get("scene_id"))
        if not scene_id:
            continue
        scene_dir = ep_dir / f"scene_{scene_id}"
        scene_dir.mkdir(parents=True, exist_ok=True)
        shots_path = scene_dir / "shots.json"
        if not shots_path.exists():
            shots_path.write_text(
                json.dumps([], ensure_ascii=False, indent=2), encoding="utf-8"
            )


def build_episode_index(episodes: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    index_map: dict[int, dict[str, Any]] = {}
    for item in episodes:
        if not isinstance(item, dict):
            continue
        episode_num = parse_episode_num(as_text(item.get("episode_id")))
        if episode_num > 0:
            index_map[episode_num] = item
    return index_map


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


def validate_analysis_structure(project_root: Path, analysis_dir: str = "script_analysis") -> dict[str, Any]:
    """校验 script_analysis 目录结构，返回校验结果。"""
    analysis_root = (project_root / analysis_dir).resolve()
    project_meta_path = analysis_root / "project_meta.json"
    if not project_meta_path.exists():
        raise FileNotFoundError(f"缺少项目元信息文件: {project_meta_path}")

    project_meta = read_json(project_meta_path)
    if not isinstance(project_meta, dict):
        raise ValueError(f"project_meta.json 格式错误: {project_meta_path}")

    total_episodes = get_total_episodes(project_meta)
    episodes_info: list[dict[str, Any]] = []

    for index in range(1, total_episodes + 1):
        ep_dir = analysis_root / f"ep_{index:02d}"
        if not ep_dir.exists():
            raise FileNotFoundError(f"缺少分集目录: {ep_dir}")

        episode_meta_path = ep_dir / f"episodes_{index:02d}.json"
        if not episode_meta_path.exists():
            raise FileNotFoundError(f"缺少分集元信息文件: {episode_meta_path}")

        scenes_path = ep_dir / "scenes.json"
        if not scenes_path.exists():
            raise FileNotFoundError(f"缺少场景文件: {scenes_path}")

        episode_meta = read_json(episode_meta_path)
        scenes = read_json(scenes_path)
        if not isinstance(scenes, list):
            scenes = []

        episode_id = as_text(episode_meta.get("episode_id")) or f"EP{index:02d}"
        ep_num = parse_episode_num(episode_id)
        if ep_num != index:
            raise ValueError(
                f"分集编号不一致: 目录为 EP{index:02d}，但文件中 episode_id={episode_id}"
            )

        scene_list: list[dict[str, Any]] = []
        for scene in scenes:
            if not isinstance(scene, dict):
                continue
            scene_id = as_text(scene.get("scene_id")) or "S00"
            location = as_text(scene.get("location")) or "未知地点"
            time_text = as_text(scene.get("time")) or "未知时间"
            characters = scene.get("characters", [])
            if isinstance(characters, list):
                characters = ",".join([as_text(c) for c in characters if as_text(c)])
            elif isinstance(characters, str):
                characters = characters.replace("，", ",")
            else:
                characters = ""
            scene_list.append({
                "scene_id": scene_id,
                "location": location,
                "time": time_text,
                "characters": characters,
            })

        episodes_info.append({
            "episode_id": episode_id,
            "title": as_text(episode_meta.get("title")) or f"第{index}集",
            "scene_count": len(scenes),
            "scenes": scene_list,
        })

    return {
        "total_episodes": total_episodes,
        "episodes": episodes_info,
    }


def download_file(url: str, output_path: Path, timeout_sec: int = 180) -> None:
    req = urllib.request.Request(url=url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
        output_path.write_bytes(resp.read())


def to_data_url(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    if not mime:
        mime = "image/png"
    raw = path.read_bytes()
    encoded = base64.b64encode(raw).decode("utf-8")
    return f"data:{mime};base64,{encoded}"


def discover_projects(repo_root: Path) -> list[dict[str, Any]]:
    """发现仓库根目录下的短剧项目目录。"""
    projects: list[dict[str, Any]] = []
    exclude = {".git", "__pycache__", "app", "API-Reference", "prompts", "scripts", "project-template"}

    for entry in sorted(repo_root.iterdir()):
        if not entry.is_dir() or entry.name.startswith(".") or entry.name in exclude:
            continue
        # 判断是否为短剧项目目录
        analysis_dir = entry / "script_analysis"
        assets_dir = entry / "assets"
        if analysis_dir.exists() or assets_dir.exists():
            meta_path = analysis_dir / "project_meta.json"
            total_episodes = 1
            if meta_path.exists():
                meta = read_project_meta(meta_path)
                total_episodes = get_total_episodes(meta)

            has_script = (entry.parent / "测试剧本.txt").exists() or (entry / "script.txt").exists()

            projects.append({
                "name": entry.name,
                "path": str(entry),
                "has_analysis": analysis_dir.exists(),
                "has_assets": assets_dir.exists(),
                "total_episodes": total_episodes if meta_path.exists() else 0,
                "has_script": has_script,
            })

    return projects
