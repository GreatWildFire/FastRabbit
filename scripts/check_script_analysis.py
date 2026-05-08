import argparse
import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def parse_episode_num(episode_id: str) -> int:
    if isinstance(episode_id, str) and episode_id.startswith("EP") and episode_id[2:].isdigit():
        return int(episode_id[2:])
    return 0


def parse_scene_num(scene_id: str) -> int:
    if isinstance(scene_id, str) and scene_id.startswith("S") and scene_id[1:].isdigit():
        return int(scene_id[1:])
    return 0


def as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def as_character_text(value: Any) -> str:
    if isinstance(value, list):
        return ",".join([as_text(v) for v in value if as_text(v)])
    if isinstance(value, str):
        return value.replace("，", ",").strip()
    return ""


def get_total_episodes(project_meta: dict[str, Any]) -> int:
    value = project_meta.get("total_episodes", 1)
    if isinstance(value, int) and value > 0:
        return value
    text = as_text(value)
    if text.isdigit() and int(text) > 0:
        return int(text)
    return 1


def find_episode_meta_files(analysis_root: Path) -> list[Path]:
    files: list[Path] = []
    for ep_dir in sorted([p for p in analysis_root.glob("ep_*") if p.is_dir()]):
        suffix = ep_dir.name.split("_")[-1]
        meta_path = ep_dir / f"episodes_{suffix}.json"
        if meta_path.exists():
            files.append(meta_path)
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description="检测并打印短剧 script_analysis 结构摘要")
    parser.add_argument(
        "--project-root",
        default="test-project",
        help="短剧项目目录（默认：test-project）",
    )
    parser.add_argument(
        "--analysis-dir",
        default="script_analysis",
        help="分析目录（相对 project-root，默认：script_analysis）",
    )
    args = parser.parse_args()

    repo_root = Path.cwd()
    analysis_root = (repo_root / args.project_root / args.analysis_dir).resolve()
    project_meta_path = analysis_root / "project_meta.json"
    if not project_meta_path.exists():
        raise FileNotFoundError(f"缺少项目元信息文件: {project_meta_path}")
    project_meta = read_json(project_meta_path)
    if not isinstance(project_meta, dict):
        raise ValueError(f"project_meta.json 格式错误: {project_meta_path}")
    total_episodes = get_total_episodes(project_meta)

    print("检测到如下集数：")
    for index in range(1, total_episodes + 1):
        ep_dir = analysis_root / f"ep_{index:02d}"
        meta_file = ep_dir / f"episodes_{index:02d}.json"
        if not ep_dir.exists():
            raise FileNotFoundError(f"缺少分集目录: {ep_dir}")
        if not meta_file.exists():
            raise FileNotFoundError(f"缺少分集元信息文件: {meta_file}")
        ep = read_json(meta_file)
        if not isinstance(ep, dict):
            raise ValueError(f"分集元信息格式错误: {meta_file}")
        episode_id = as_text(ep.get("episode_id")) or "EP00"
        title = as_text(ep.get("title")) or "未命名"
        ep_num = parse_episode_num(episode_id)
        if ep_num != index:
            raise ValueError(
                f"分集编号不一致: 目录为 EP{index:02d}，但 {meta_file} 中 episode_id={episode_id}"
            )

        scenes_path = ep_dir / "scenes.json"
        if not scenes_path.exists():
            raise FileNotFoundError(f"缺少场景文件: {scenes_path}")

        scenes = read_json(scenes_path)
        if not isinstance(scenes, list):
            scenes = []

        print(f" {episode_id} {title} - 包含{len(scenes)}场")

        scenes = sorted(
            [scene for scene in scenes if isinstance(scene, dict)],
            key=lambda x: parse_scene_num(as_text(x.get("scene_id"))),
        )
        for scene in scenes:
            scene_id = as_text(scene.get("scene_id")) or "S00"
            location = as_text(scene.get("location")) or "未知地点"
            time_text = as_text(scene.get("time")) or "未知时间"
            characters = as_character_text(scene.get("characters")) or "无角色"
            print(f"   {scene_id}: {location} {time_text} {characters}")


if __name__ == "__main__":
    main()
