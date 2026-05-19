"""文本处理公共函数，从 scripts/ 中抽取。"""

import json
import re
from typing import Any


def as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def as_int(value: Any, default: int = 0) -> int:
    if isinstance(value, int):
        return value
    text = as_text(value)
    if text.isdigit():
        return int(text)
    return default


def as_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [as_text(item) for item in value if as_text(item)]
    if isinstance(value, str):
        text = value.replace("，", ",")
        return [item.strip() for item in text.split(",") if item.strip()]
    return []


def normalize_characters(value: Any) -> list[str]:
    return as_string_list(value)


def normalize_style_tags(value: Any) -> list[str]:
    return as_string_list(value)


def normalize_gender(value: Any) -> str:
    text = as_text(value)
    if text in {"男", "女", "未知"}:
        return text
    if "男" in text:
        return "男"
    if "女" in text:
        return "女"
    return "未知"


def parse_episode_num(episode_id: str) -> int:
    if isinstance(episode_id, str) and episode_id.startswith("EP") and episode_id[2:].isdigit():
        return int(episode_id[2:])
    return 0


def parse_scene_num(scene_id: str) -> int:
    if isinstance(scene_id, str) and scene_id.startswith("S") and scene_id[1:].isdigit():
        return int(scene_id[1:])
    return 0


def parse_shot_sort_key(shot_id: str) -> tuple[int, int]:
    m = re.match(r"^S(\d+)_SH(\d+)$", shot_id)
    if not m:
        return (10**9, 10**9)
    return (int(m.group(1)), int(m.group(2)))


def normalize_episode_id(value: str, index: int) -> str:
    if isinstance(value, str) and value.startswith("EP") and len(value) == 4 and value[2:].isdigit():
        return value
    return f"EP{index:02d}"


def normalize_scene_id(value: str, index: int) -> str:
    if isinstance(value, str) and value.startswith("S") and len(value) == 3 and value[1:].isdigit():
        return value
    return f"S{index:02d}"


def sanitize_filename(name: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|]", "_", name).strip()
    return cleaned or "未命名"


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
    raise ValueError("响应内容中未找到合法 JSON 对象")


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
        episode_id = normalize_episode_id(as_text(item.get("episode_id")), ep_index)
        title = as_text(item.get("title")) or f"第{ep_index}集"

        raw_scenes = raw_scenes_by_episode.get(episode_id, [])
        if not isinstance(raw_scenes, list):
            raw_scenes = []

        normalized_scenes: list[dict[str, Any]] = []
        scene_ids: list[str] = []
        for sc_index, scene in enumerate(raw_scenes, start=1):
            if not isinstance(scene, dict):
                continue
            scene_id = normalize_scene_id(as_text(scene.get("scene_id")), sc_index)
            scene_ids.append(scene_id)
            normalized_scenes.append(
                {
                    "scene_id": scene_id,
                    "location": as_text(scene.get("location")),
                    "time": as_text(scene.get("time")),
                    "characters": as_string_list(scene.get("characters")),
                    "description": as_text(scene.get("description")),
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


def build_character_description(character: dict[str, Any]) -> str:
    """从角色卡构建生图回退提示词。"""
    name = as_text(character.get("name")) or "主角"
    age = as_text(character.get("age")) or "25"
    gender = as_text(character.get("gender")) or "未知"
    height = as_text(character.get("height")) or "170"
    weight = as_text(character.get("weight")) or "60"
    description = as_text(character.get("description")) or "角色形象鲜明，适合二次元动漫风格人物立绘。"
    return (
        f"{name}，{gender}，约{age}岁，身高约{height}cm，体重约{weight}kg，"
        f"{description}，单人半身肖像，二次元动漫风格，anime style，cel shading，"
        "clean lineart，detailed illustration，soft lighting，干净背景。"
    )


# 角色卡的视觉字段名列表
CHARACTER_VISUAL_FIELDS = ["hairstyle", "face", "clothing", "accessories", "build", "expression"]


def normalize_character(item: dict[str, Any]) -> dict[str, Any]:
    """将 LLM 返回的角色数据标准化，补全缺失字段。"""
    name = as_text(item.get("name"))
    if not name:
        return {}

    char: dict[str, Any] = {
        "name": name,
        "age": as_int(item.get("age"), 25),
        "gender": normalize_gender(item.get("gender")),
        "height": as_int(item.get("height"), 170),
        "weight": as_int(item.get("weight"), 60),
        "description": as_text(item.get("description")) or f"{name}是剧中的核心角色。",
    }

    # 新视觉字段：保留 LLM 输出，若缺失则从 description 提取或填空
    for field in CHARACTER_VISUAL_FIELDS:
        value = as_text(item.get(field))
        char[field] = value if value else "待补充"

    return char


def character_to_human_prompt(char: dict[str, Any]) -> str:
    """将结构化角色卡转为人类可读的视觉描述文本（用于 LLM 输入）。"""
    parts = []
    name = as_text(char.get("name")) or "角色"
    parts.append(f"角色名称：{name}")

    for field in CHARACTER_VISUAL_FIELDS:
        value = as_text(char.get(field))
        if value and value != "待补充":
            label = {"hairstyle": "发型", "face": "面部", "clothing": "服装",
                     "accessories": "配饰", "build": "体型", "expression": "表情"}.get(field, field)
            parts.append(f"{label}：{value}")

    desc = as_text(char.get("description"))
    if desc:
        parts.append(f"综合描述：{desc}")

    return "\n".join(parts)
