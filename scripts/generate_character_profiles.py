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


def as_int(value: Any, default: int) -> int:
    if isinstance(value, int):
        return value
    text = as_text(value)
    if text.isdigit():
        return int(text)
    return default


def normalize_gender(value: Any) -> str:
    text = as_text(value)
    if text in {"男", "女", "未知"}:
        return text
    if "男" in text:
        return "男"
    if "女" in text:
        return "女"
    return "未知"


def sanitize_filename(name: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|]", "_", name).strip()
    return cleaned or "未命名角色"


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


def normalize_characters(payload: dict[str, Any], max_characters: int) -> list[dict[str, Any]]:
    raw_characters = payload.get("characters", [])
    if not isinstance(raw_characters, list):
        raw_characters = []

    normalized: list[dict[str, Any]] = []
    for item in raw_characters:
        if not isinstance(item, dict):
            continue
        name = as_text(item.get("name"))
        if not name:
            continue
        age = as_int(item.get("age"), 25)
        gender = normalize_gender(item.get("gender"))
        height = as_int(item.get("height"), 170)
        weight = as_int(item.get("weight"), 60)
        description = as_text(item.get("description"))
        if not description:
            description = f"{name}是剧中的核心角色，具有鲜明的外貌与气质特征。"

        normalized.append(
            {
                "name": name,
                "age": age,
                "gender": gender,
                "height": height,
                "weight": weight,
                "description": description,
            }
        )
        if len(normalized) >= max_characters:
            break

    if not normalized:
        normalized = [
            {
                "name": "主角",
                "age": 25,
                "gender": "未知",
                "height": 170,
                "weight": 60,
                "description": "主角是剧中的核心人物，外形与气质待根据剧情补充。",
            }
        ]

    return normalized


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def get_total_episodes(project_meta: dict[str, Any]) -> int:
    value = project_meta.get("total_episodes", 1)
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.isdigit() and int(value) > 0:
        return int(value)
    return 1


def validate_analysis_structure(project_root: Path, analysis_dir: str) -> None:
    analysis_root = (project_root / analysis_dir).resolve()
    project_meta_path = analysis_root / "project_meta.json"
    if not project_meta_path.exists():
        raise FileNotFoundError(f"缺少项目元信息文件: {project_meta_path}")

    project_meta = read_json(project_meta_path)
    if not isinstance(project_meta, dict):
        raise ValueError(f"project_meta.json 格式错误: {project_meta_path}")

    total_episodes = get_total_episodes(project_meta)
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


def render_system_prompt(template: str, max_characters: int) -> str:
    return template.replace("{{MAX_CHARACTERS}}", str(max_characters))


def main() -> None:
    parser = argparse.ArgumentParser(description="读取剧本并生成核心角色信息到项目角色目录")
    parser.add_argument(
        "--project-root",
        default="test-project",
        help="短剧项目目录（默认：test-project）",
    )
    parser.add_argument(
        "--script-file",
        default="测试剧本.txt",
        help="剧本文件路径（相对仓库根目录，默认：测试剧本.txt）",
    )
    parser.add_argument(
        "--characters-dir",
        default="assets/characters/base",
        help="角色输出目录（相对 project-root，默认：assets/characters/base）",
    )
    parser.add_argument(
        "--analysis-dir",
        default="script_analysis",
        help="分析目录（相对 project-root，默认：script_analysis）",
    )
    parser.add_argument(
        "--max-characters",
        type=int,
        default=1,
        help="输出角色数量上限（默认：1，仅主角）",
    )
    parser.add_argument(
        "--env-file",
        default=".env",
        help="环境变量文件（相对仓库根目录，默认：.env）",
    )
    parser.add_argument(
        "--system-prompt",
        default="prompts/character_profile_system_prompt.txt",
        help="系统提示词文件（相对仓库根目录）",
    )
    parser.add_argument(
        "--model",
        default="deepseek-v4-flash",
        help="模型名称（默认：deepseek-v4-flash）",
    )
    parser.add_argument(
        "--skip-structure-check",
        action="store_true",
        help="跳过 script_analysis 目录结构校验",
    )
    args = parser.parse_args()

    repo_root = Path.cwd()
    project_root = (repo_root / args.project_root).resolve()
    script_path = (repo_root / args.script_file).resolve()
    characters_dir = (project_root / args.characters_dir).resolve()
    env_path = (repo_root / args.env_file).resolve()
    prompt_path = (repo_root / args.system_prompt).resolve()

    load_env_file(env_path)
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("未读取到 DEEPSEEK_API_KEY，请检查 .env")
    if not script_path.exists():
        raise FileNotFoundError(f"剧本文件不存在: {script_path}")
    if not prompt_path.exists():
        raise FileNotFoundError(f"系统提示词文件不存在: {prompt_path}")
    if not args.skip_structure_check:
        validate_analysis_structure(project_root=project_root, analysis_dir=args.analysis_dir)

    max_characters = max(1, args.max_characters)
    script_text = script_path.read_text(encoding="utf-8")
    system_prompt_template = prompt_path.read_text(encoding="utf-8")
    system_prompt = render_system_prompt(system_prompt_template, max_characters=max_characters)
    user_prompt = f"目标角色数量: {max_characters}\n\n剧本文本如下：\n{script_text}"

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
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
    characters = normalize_characters(payload, max_characters=max_characters)

    characters_dir.mkdir(parents=True, exist_ok=True)
    for character in characters:
        file_name = f"{sanitize_filename(character['name'])}.json"
        output_path = characters_dir / file_name
        output_path.write_text(json.dumps(character, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已覆盖写入: {output_path}")


if __name__ == "__main__":
    main()
