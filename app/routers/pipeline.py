"""管线操作端点。"""

import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from openai import OpenAI

from app.config import (
    REPO_ROOT, get_project_path, get_prompt_path, get_script_path,
    get_llm_config, get_image_config, get_video_config,
)
from app.utils.io import (
    read_json, write_json, read_project_meta, get_total_episodes,
    ensure_episode_dirs, ensure_scene_dirs, build_episode_index,
    extract_scene_blocks, validate_analysis_structure, download_file, to_data_url,
)
from app.utils.text import (
    as_text, extract_json_object, normalize_payload, normalize_characters,
    parse_scene_num, sanitize_filename, normalize_gender, as_int, parse_shot_sort_key,
    normalize_style_tags, sanitize_prompt, build_character_description,
    normalize_character, CHARACTER_VISUAL_FIELDS,
)
from app.db import (
    init_db, project_exists, create_project as db_create_project,
    update_project, upsert_episodes, get_episode_id_map,
    upsert_scenes, get_scene_id_map, update_scene,
    upsert_shots, update_shot_video,
    upsert_characters, update_character_image,
)

router = APIRouter(tags=["pipeline"])

# 默认模型从 .env 读取，若未配置则使用内置兜底
_DEFAULT_LLM_MODEL = get_llm_config().model or "deepseek-v4-flash"
_DEFAULT_IMAGE_MODEL = get_image_config().model or "nano-banana-fast"
_DEFAULT_VIDEO_MODEL = get_video_config().model or "doubao-seedance-2-0-250528"

# ── 辅助函数 ──────────────────────────────────────────────────────

def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: int) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url=url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="ignore")
    return extract_json_object(raw)


def _extract_image_url(result: dict[str, Any]) -> str:
    candidates: list[dict[str, Any]] = []
    if isinstance(result.get("results"), list):
        candidates = result["results"]
    elif isinstance(result.get("data"), dict) and isinstance(result["data"].get("results"), list):
        candidates = result["data"]["results"]
    if candidates and isinstance(candidates[0], dict):
        return as_text(candidates[0].get("url"))
    return ""


def _request_image_url(api_key: str, prompt: str, image_model: str,
                       aspect_ratio: str, image_size: str,
                       timeout_sec: int, retries: int) -> str:
    img_config = get_image_config()
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
            result = _post_json(img_config.base_url, payload, headers, timeout=timeout_sec)
            status = as_text(result.get("status")) or as_text(result.get("data", {}).get("status"))
            failure_reason = as_text(result.get("failure_reason")) or as_text(result.get("data", {}).get("failure_reason"))
            image_url = _extract_image_url(result)
            if image_url:
                return image_url
            if status == "failed":
                last_error = failure_reason or "生图任务失败"
            else:
                last_error = as_text(result.get("msg")) or "未拿到图片链接"
        except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            last_error = str(exc)
    raise RuntimeError(f"生图失败: {last_error}")


def _load_prompt_text(relative_path: str) -> str:
    path = get_prompt_path(relative_path)
    if not path.exists():
        raise FileNotFoundError(f"提示词文件不存在: {path}")
    return path.read_text(encoding="utf-8")


def _load_script_text(script_file: str) -> str:
    path = get_script_path(script_file)
    if not path.exists():
        raise FileNotFoundError(f"剧本文件不存在: {path}")
    return path.read_text(encoding="utf-8")


def _create_llm_client() -> OpenAI:
    llm = get_llm_config()
    if not llm.api_key:
        raise HTTPException(status_code=500, detail="未配置 LLM_API_KEY")
    return OpenAI(api_key=llm.api_key, base_url=llm.base_url)


def _update_scene_image_db(project_name: str, episode_id: str, scene_id: str) -> None:
    """更新场景图片状态。"""
    ep_map = get_episode_id_map(project_name)
    ep_db_id = ep_map.get(episode_id)
    if ep_db_id:
        sc_map = get_scene_id_map(ep_db_id)
        sc_db_id = sc_map.get(scene_id)
        if sc_db_id:
            update_scene(sc_db_id, has_image=1)


def _update_shot_video_db(project_name: str, episode_id: str, scene_id: str,
                          shot_id: str, task_id: str = "", has_video: int = 1) -> None:
    """更新镜头视频状态。"""
    ep_map = get_episode_id_map(project_name)
    ep_db_id = ep_map.get(episode_id)
    if ep_db_id:
        sc_map = get_scene_id_map(ep_db_id)
        sc_db_id = sc_map.get(scene_id)
        if sc_db_id:
            update_shot_video(sc_db_id, shot_id, task_id=task_id, has_video=has_video)


def _llm_json(client: OpenAI, model: str, system_prompt: str, user_prompt: str) -> dict[str, Any]:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        stream=False,
        response_format={"type": "json_object"},
    )
    return extract_json_object(response.choices[0].message.content or "{}")


# ── 步骤1：剧本拆解 ──────────────────────────────────────────────

@router.post("/projects/{name}/pipeline/analyze-script")
async def analyze_script(
    name: str,
    script_file: str = "测试剧本.txt",
    model: str = _DEFAULT_LLM_MODEL,
):
    """步骤1：调用 LLM 将剧本拆解为集和场景。"""
    project_root = get_project_path(name)
    script_text = _load_script_text(script_file)
    system_prompt = _load_prompt_text("prompts/script_analysis_system_prompt.txt")

    client = _create_llm_client()
    payload = _llm_json(client, model, system_prompt, script_text)
    episodes, scenes_by_episode = normalize_payload(payload)

    output_root = project_root / "script_analysis"
    output_root.mkdir(parents=True, exist_ok=True)

    project_meta_path = output_root / "project_meta.json"
    project_meta = read_project_meta(project_meta_path)
    total_episodes = get_total_episodes(project_meta)
    ensure_episode_dirs(output_root, total_episodes)

    indexed_episodes = build_episode_index(episodes)

    root_episodes_path = output_root / "episodes.json"
    if root_episodes_path.exists():
        root_episodes_path.unlink()

    written: list[str] = []
    max_episode_num = max(total_episodes, max(indexed_episodes.keys(), default=0))
    for episode_num in range(1, max_episode_num + 1):
        episode = indexed_episodes.get(
            episode_num,
            {"episode_id": f"EP{episode_num:02d}", "title": f"第{episode_num}集", "scenes": []},
        )
        episode_id = as_text(episode.get("episode_id")) or f"EP{episode_num:02d}"
        ep_dir = output_root / f"ep_{episode_num:02d}"
        ep_dir.mkdir(parents=True, exist_ok=True)

        episode_meta_path = ep_dir / f"episodes_{episode_num:02d}.json"
        write_json(episode_meta_path, episode)
        written.append(str(episode_meta_path))

        scenes_path = ep_dir / "scenes.json"
        scenes = scenes_by_episode.get(episode_id, [])
        write_json(scenes_path, scenes)
        written.append(str(scenes_path))
        ensure_scene_dirs(ep_dir, scenes)

    # 同步到 DB
    init_db()
    if not project_exists(name):
        db_create_project(name, script_content=script_text)
    update_project(name, total_episodes=max_episode_num, status="analyzed")
    upsert_episodes(name, [
        {"episode_id": f"EP{num:02d}", "title": f"第{num}集", "index_num": num}
        for num in range(1, max_episode_num + 1)
    ])
    ep_map = get_episode_id_map(name)
    for episode_num in range(1, max_episode_num + 1):
        episode_id = f"EP{episode_num:02d}"
        ep_db_id = ep_map.get(episode_id)
        if ep_db_id:
            scenes = scenes_by_episode.get(episode_id, [])
            if scenes:
                upsert_scenes(ep_db_id, scenes)

    return {"success": True, "data": {"total_episodes": total_episodes, "max_episode_num": max_episode_num, "written_files": written}, "error": None}


# ── 步骤2：结构校验 ──────────────────────────────────────────────

@router.post("/projects/{name}/pipeline/validate")
async def validate_structure(name: str):
    """步骤2：校验项目 script_analysis 结构完整性。"""
    project_root = get_project_path(name)
    if not project_root.exists():
        raise HTTPException(status_code=404, detail=f"项目不存在: {name}")
    try:
        result = validate_analysis_structure(project_root)
        return {"success": True, "data": result, "error": None}
    except Exception as exc:
        return {"success": False, "data": None, "error": str(exc)}


# ── 步骤3：场次拆镜头 ────────────────────────────────────────────

@router.post("/projects/{name}/pipeline/scene-shots")
async def generate_scene_shots(
    name: str,
    episode: int = 0,
    scene_id: str = "",
    script_file: str = "测试剧本.txt",
    model: str = _DEFAULT_LLM_MODEL,
    max_shots: int = 12,
):
    """步骤3：将场景拆解为镜头。"""
    project_root = get_project_path(name)
    analysis_root = project_root / "script_analysis"

    project_meta_path = analysis_root / "project_meta.json"
    if not project_meta_path.exists():
        raise HTTPException(status_code=404, detail="缺少 project_meta.json，请先执行 analyze-script")

    project_meta = read_json(project_meta_path)
    total_episodes = get_total_episodes(project_meta)
    script_text = _load_script_text(script_file)
    system_prompt = _load_prompt_text("prompts/scene_shots_system_prompt.txt")
    scene_blocks = extract_scene_blocks(script_text)
    client = _create_llm_client()
    max_shots = max(1, max_shots)

    written: list[str] = []
    for ep_index in range(1, total_episodes + 1):
        if episode and ep_index != episode:
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
            sid = as_text(scene.get("scene_id"))
            if not sid:
                continue
            if scene_id and sid != scene_id:
                continue

            sc_num = parse_scene_num(sid)
            scene_excerpt = scene_blocks.get((ep_index, sc_num), "")
            scene_dir = ep_dir / f"scene_{sid}"
            scene_dir.mkdir(parents=True, exist_ok=True)

            source_path = scene_dir / "scene_source.txt"
            source_path.write_text(scene_excerpt, encoding="utf-8")

            user_prompt = (
                f"目标集: {episode_id}\n目标场: {json.dumps(scene, ensure_ascii=False)}\n"
                f"镜头数量上限: {max_shots}\n\n【本集完整剧本】\n{script_text}\n\n"
                f"【当前场原文片段】\n{scene_excerpt}\n"
            )
            payload = _llm_json(client, model, system_prompt, user_prompt)

            raw = payload.get("shots", [])
            if not isinstance(raw, list):
                raw = []

            allowed_chars = normalize_characters(scene.get("characters"))
            allowed_set = set(allowed_chars)
            normalized_shots: list[dict[str, Any]] = []
            for idx, item in enumerate(raw, start=1):
                if not isinstance(item, dict):
                    continue
                shot_id = f"{sid}_SH{idx:02d}"
                shot_type = as_text(item.get("type")) or "中景"
                action = as_text(item.get("action"))
                if not action:
                    continue
                chars = normalize_characters(item.get("characters"))
                if allowed_set:
                    chars = [c for c in chars if c in allowed_set]
                normalized_shots.append({"shot_id": shot_id, "type": shot_type, "action": action, "characters": chars})
                if len(normalized_shots) >= max_shots:
                    break

            shots_path = scene_dir / "shots.json"
            write_json(shots_path, normalized_shots)
            written.append(str(shots_path))

            # 同步镜头到 DB
            ep_map = get_episode_id_map(name)
            ep_db_id = ep_map.get(episode_id)
            if ep_db_id:
                sc_map = get_scene_id_map(ep_db_id)
                sc_db_id = sc_map.get(sid)
                if sc_db_id:
                    upsert_shots(sc_db_id, normalized_shots)

    return {"success": True, "data": {"written_files": written}, "error": None}


# ── 步骤4：角色卡 ──────────────────────────────────────────────────

@router.post("/projects/{name}/pipeline/character-profiles")
async def generate_character_profiles(
    name: str,
    script_file: str = "测试剧本.txt",
    model: str = _DEFAULT_LLM_MODEL,
    max_characters: int = 4,
):
    """步骤4：LLM 提取核心角色信息。"""
    project_root = get_project_path(name)
    characters_dir = project_root / "assets" / "characters" / "base"

    script_text = _load_script_text(script_file)
    system_prompt_template = _load_prompt_text("prompts/character_profile_system_prompt.txt")
    max_characters = max(1, max_characters)
    system_prompt = system_prompt_template.replace("{{MAX_CHARACTERS}}", str(max_characters))

    client = _create_llm_client()
    payload = _llm_json(client, model, system_prompt,
                        f"目标角色数量: {max_characters}\n\n剧本文本如下：\n{script_text}")

    raw_characters = payload.get("characters", [])
    if not isinstance(raw_characters, list):
        raw_characters = []

    characters: list[dict[str, Any]] = []
    for item in raw_characters:
        if not isinstance(item, dict):
            continue
        char = normalize_character(item)
        if not char:
            continue
        characters.append(char)
        if len(characters) >= max_characters:
            break

    if not characters:
        characters = [{"name": "主角", "age": 25, "gender": "未知", "height": 170, "weight": 60,
                        "description": "主角是剧中的核心人物。",
                        "hairstyle": "待补充", "face": "待补充", "clothing": "待补充",
                        "accessories": "待补充", "build": "待补充", "expression": "待补充"}]

    characters_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for char in characters:
        file_name = f"{sanitize_filename(char['name'])}.json"
        output_path = characters_dir / file_name
        write_json(output_path, char)
        written.append(str(output_path))

    # 同步到 DB
    init_db()
    upsert_characters(name, characters)
    update_project(name, status="characters_created")

    return {"success": True, "data": {"characters": characters, "written_files": written}, "error": None}


# ── 步骤5：角色图 ──────────────────────────────────────────────────

@router.post("/projects/{name}/pipeline/character-images")
async def generate_character_images(
    name: str,
    character_names: str = "",
    character_files: str = "",
    llm_model: str = _DEFAULT_LLM_MODEL,
    image_model: str = _DEFAULT_IMAGE_MODEL,
    aspect_ratio: str = "3:4",
    image_size: str = "1K",
    image_ext: str = "png",
    timeout_sec: int = 120,
    retries: int = 1,
    allow_partial: bool = False,
):
    """步骤5：读取角色卡并通过 LLM + Nano Banana 生成角色图。"""
    project_root = get_project_path(name)
    character_dir = project_root / "assets" / "characters" / "base"

    img_config = get_image_config()
    banana_key = img_config.api_key
    if not banana_key:
        raise HTTPException(status_code=500, detail="未配置 IMAGE_API_KEY")

    system_prompt = _load_prompt_text("prompts/character_image_prompt_system.txt")
    cards = sorted([p for p in character_dir.glob("*.json") if p.is_file()])
    if not cards:
        raise HTTPException(status_code=404, detail=f"未找到角色卡 JSON: {character_dir}")

    # 过滤角色
    target_names = [n.strip() for n in character_names.split(",") if n.strip()]
    target_files = [f.strip() for f in character_files.split(",") if f.strip()]
    if target_names or target_files:
        allowed_files = set()
        for item in target_files:
            allowed_files.add(item if item.endswith(".json") else f"{item}.json")
        cards = [c for c in cards if c.stem in target_names or c.name in allowed_files]
        if not cards:
            raise HTTPException(status_code=404, detail="未匹配到任何角色卡")

    llm_client = _create_llm_client()
    success_count = 0
    failed: list[str] = []

    for card_path in cards:
        try:
            character = read_json(card_path)
            if not isinstance(character, dict):
                raise ValueError("角色卡内容不是 JSON 对象")
            name = as_text(character.get("name")) or card_path.stem

            # LLM 生成生图提示词
            llm_payload = _llm_json(llm_client, llm_model, system_prompt,
                                     json.dumps(character, ensure_ascii=False))
            prompt = as_text(llm_payload.get("prompt"))
            if not prompt:
                prompt = build_character_description(character)

            # 生图
            image_url = _request_image_url(banana_key, prompt, image_model,
                                           aspect_ratio, image_size, timeout_sec, retries)

            file_name = f"{sanitize_filename(name)}.{image_ext.strip('.')}"
            output_path = card_path.parent / file_name
            download_file(image_url, output_path, timeout_sec=timeout_sec)
            # 更新 DB
            update_character_image(name, name, has_image=1)
            success_count += 1
        except Exception as exc:
            failed.append(f"{card_path.name}: {exc}")

    result = {"success_count": success_count, "failed_count": len(failed), "failed": failed}
    if failed and not allow_partial:
        raise HTTPException(status_code=500, detail=f"部分角色生图失败: {failed}")
    return {"success": True, "data": result, "error": None}


# ── 步骤6：场景提示词 ─────────────────────────────────────────────

@router.post("/projects/{name}/pipeline/scene-prompts")
async def generate_scene_prompts(
    name: str,
    episode: int = 0,
    scene_id: str = "",
    script_file: str = "测试剧本.txt",
    model: str = _DEFAULT_LLM_MODEL,
):
    """步骤6：为每个场景生成生图提示词。"""
    project_root = get_project_path(name)
    analysis_root = project_root / "script_analysis"

    project_meta_path = analysis_root / "project_meta.json"
    if not project_meta_path.exists():
        raise HTTPException(status_code=404, detail="缺少 project_meta.json，请先执行 analyze-script")

    project_meta = read_json(project_meta_path)
    total_episodes = get_total_episodes(project_meta)
    script_text = _load_script_text(script_file)
    system_prompt = _load_prompt_text("prompts/scene_image_prompt_system.txt")
    scene_blocks = extract_scene_blocks(script_text)
    client = _create_llm_client()

    written: list[str] = []
    for ep_index in range(1, total_episodes + 1):
        if episode and ep_index != episode:
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
            sid = as_text(scene.get("scene_id"))
            if not sid or (scene_id and sid != scene_id):
                continue

            sc_num = parse_scene_num(sid)
            scene_excerpt = scene_blocks.get((ep_index, sc_num), "")
            user_prompt = (
                f"目标集: {episode_id}\n目标场: {json.dumps(scene, ensure_ascii=False)}\n\n"
                f"【本集完整剧本】\n{script_text}\n\n【当前场原文片段】\n{scene_excerpt}\n"
            )
            payload = _llm_json(client, model, system_prompt, user_prompt)

            location = as_text(scene.get("location"))
            time_text = as_text(scene.get("time"))
            desc = as_text(scene.get("description"))
            scene_characters = normalize_characters(scene.get("characters"))

            scene_prompt = as_text(payload.get("scene_prompt"))
            if not scene_prompt:
                scene_prompt = f"{location}，{time_text}，{desc}，二次元动漫背景风格，色彩分层清晰，干净构图。"
            # 移除角色名字
            for cn in scene_characters:
                if cn:
                    scene_prompt = scene_prompt.replace(cn, "")
            scene_prompt = re.sub(r"[，,\s]{2,}", "，", scene_prompt).strip("，, 。")
            if not scene_prompt:
                scene_prompt = f"{location}，{time_text}，环境空间建立镜头，二次元动漫背景风格，高细节，干净构图。"

            negative_prompt = as_text(payload.get("negative_prompt"))
            if not negative_prompt:
                negative_prompt = "低清晰度，模糊，畸变，多余人物，主要角色入镜，错位光影，水印，文字。"
            else:
                for cn in scene_characters:
                    if cn:
                        negative_prompt = negative_prompt.replace(cn, "")
                if "主要角色入镜" not in negative_prompt:
                    negative_prompt = f"{negative_prompt}，主要角色入镜".strip("，")

            style_tags = normalize_style_tags(payload.get("style_tags"))
            if not style_tags:
                style_tags = ["动漫风格", "二次元背景", "高细节"]

            normalized = {"scene_prompt": scene_prompt, "negative_prompt": negative_prompt, "style_tags": style_tags}
            scene_dir = ep_dir / f"scene_{sid}"
            scene_dir.mkdir(parents=True, exist_ok=True)
            prompt_path_out = scene_dir / "scene_prompt.json"
            write_json(prompt_path_out, normalized)
            written.append(str(prompt_path_out))

            # 同步场景提示词到 DB
            ep_map = get_episode_id_map(name)
            ep_db_id = ep_map.get(episode_id)
            if ep_db_id:
                sc_map = get_scene_id_map(ep_db_id)
                sc_db_id = sc_map.get(sid)
                if sc_db_id:
                    update_scene(sc_db_id, scene_prompt=scene_prompt)

    return {"success": True, "data": {"written_files": written}, "error": None}


# ── 步骤7：场景图 ──────────────────────────────────────────────────

@router.post("/projects/{name}/pipeline/scene-images")
async def generate_scene_images(
    name: str,
    episode: int = 0,
    scene_id: str = "",
    image_model: str = _DEFAULT_IMAGE_MODEL,
    aspect_ratio: str = "16:9",
    image_size: str = "1K",
    image_ext: str = "png",
    timeout_sec: int = 150,
    retries: int = 1,
    allow_partial: bool = False,
):
    """步骤7：读取 scene_prompt.json 并生成场景背景图。"""
    project_root = get_project_path(name)
    analysis_root = project_root / "script_analysis"
    output_root = project_root / "assets" / "scenes" / "base"

    img_config = get_image_config()
    banana_key = img_config.api_key
    if not banana_key:
        raise HTTPException(status_code=500, detail="未配置 IMAGE_API_KEY")

    project_meta_path = analysis_root / "project_meta.json"
    if not project_meta_path.exists():
        raise HTTPException(status_code=404, detail="缺少 project_meta.json")

    project_meta = read_json(project_meta_path)
    total_episodes = get_total_episodes(project_meta)
    output_root.mkdir(parents=True, exist_ok=True)

    success_count = 0
    failed: list[str] = []

    for ep_index in range(1, total_episodes + 1):
        if episode and ep_index != episode:
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
            sid = as_text(scene.get("scene_id"))
            if not sid or (scene_id and sid != scene_id):
                continue

            scene_dir = ep_dir / f"scene_{sid}"
            prompt_path = scene_dir / "scene_prompt.json"
            if prompt_path.exists():
                prompt_data = read_json(prompt_path)
                if not isinstance(prompt_data, dict):
                    prompt_data = {}
            else:
                prompt_data = {}

            scene_prompt = as_text(prompt_data.get("scene_prompt"))
            if not scene_prompt:
                loc = as_text(scene.get("location")) or "城市街道"
                tm = as_text(scene.get("time")) or "日外"
                scene_prompt = f"{loc}，{tm}，{as_text(scene.get('description'))}"

            style_tags = normalize_style_tags(prompt_data.get("style_tags"))
            negative_prompt = as_text(prompt_data.get("negative_prompt"))
            parts = [scene_prompt]
            if style_tags:
                parts.append("风格标签：" + "，".join(style_tags))
            if negative_prompt:
                parts.append("避免：" + negative_prompt)
            final_prompt = "。".join([p for p in parts if p])

            # 安全过滤
            for src, dst in [("血迹", "磨损痕迹"), ("鲜血", "污渍"), ("诡异", "未知生物"),
                             ("追杀", "追逐"), ("尸体", "残留物"), ("战火纷飞", "紧张氛围"),
                             ("炮口对准", "重型设备陈列"), ("斩杀", "对抗"), ("压抑", "肃穆")]:
                final_prompt = final_prompt.replace(src, dst)

            try:
                image_url = _request_image_url(banana_key, final_prompt, image_model,
                                               aspect_ratio, image_size, timeout_sec, retries)
                file_name = f"{episode_id}_{sid}.{image_ext.strip('.')}"
                output_path = output_root / file_name
                download_file(image_url, output_path, timeout_sec=timeout_sec)
                _update_scene_image_db(name, episode_id, sid)
                success_count += 1
            except Exception as exc:
                err_text = str(exc).lower()
                # 合规拦截降级
                if "violate our policies" in err_text or "moderation" in err_text:
                    try:
                        loc = as_text(scene.get("location")) or "城市街道"
                        tm = as_text(scene.get("time")) or "日外"
                        neutral = (f"{loc}，{tm}，无人环境场景，二次元动漫背景风格，赛璐璐质感，"
                                    "高细节材质，建筑与街道空间关系清晰，色彩分层明确，干净画面，无角色主体。")
                        image_url = _request_image_url(banana_key, neutral, image_model,
                                                       aspect_ratio, image_size, timeout_sec, retries)
                        file_name = f"{episode_id}_{sid}.{image_ext.strip('.')}"
                        output_path = output_root / file_name
                        download_file(image_url, output_path, timeout_sec=timeout_sec)
                        _update_scene_image_db(name, episode_id, sid)
                        success_count += 1
                        continue
                    except Exception as retry_exc:
                        failed.append(f"{episode_id}-{sid}: {retry_exc}")
                        continue
                failed.append(f"{episode_id}-{sid}: {exc}")

    result = {"success_count": success_count, "failed_count": len(failed), "failed": failed}
    if failed and not allow_partial:
        raise HTTPException(status_code=500, detail=f"部分场景生图失败: {failed}")
    return {"success": True, "data": result, "error": None}


# ── 步骤8：镜头视频（异步轮询）────────────────────────────────────

# 内存中的视频任务状态（重启丢失，后续可持久化）
_video_tasks: dict[str, dict[str, Any]] = {}


def _create_ark_client(ark_api_key: str):
    try:
        from volcenginesdkarkruntime import Ark
    except ImportError:
        raise HTTPException(status_code=500, detail="缺少 ark SDK: pip install 'volcengine-python-sdk[ark]'")
    video_config = get_video_config()
    return Ark(base_url=video_config.base_url, api_key=ark_api_key)


def _run_video_generation(task_id: str, args: dict[str, Any]) -> None:
    """后台执行视频生成（同步阻塞，在 thread 中运行）。"""
    try:
        project_root = Path(args["project_root"])
        analysis_root = project_root / "script_analysis"
        shots_root = project_root / "assets" / "shots"
        script_text = args["script_text"]
        system_prompt = args["system_prompt"]

        llm_client = _create_llm_client()
        ark_client = _create_ark_client(args["ark_key"])

        total_episodes = args["total_episodes"]
        success_count = 0
        failed: list[str] = []

        for ep_index in range(1, total_episodes + 1):
            if args["episode"] and ep_index != args["episode"]:
                continue
            ep_dir = analysis_root / f"ep_{ep_index:02d}"
            scenes_path = ep_dir / "scenes.json"
            if not scenes_path.exists():
                continue
            scenes = read_json(scenes_path)
            if not isinstance(scenes, list):
                continue

            scene_map: dict[str, dict[str, Any]] = {}
            for scene in scenes:
                if isinstance(scene, dict):
                    sid = as_text(scene.get("scene_id"))
                    if sid:
                        scene_map[sid] = scene

            for scene_id_val, scene_meta in scene_map.items():
                if args["scene_id"] and scene_id_val != args["scene_id"]:
                    continue

                shots_path = ep_dir / f"scene_{scene_id_val}" / "shots.json"
                if not shots_path.exists():
                    continue
                shots = read_json(shots_path)
                if not isinstance(shots, list):
                    continue
                valid_shots = [s for s in shots if isinstance(s, dict) and as_text(s.get("shot_id"))]
                valid_shots.sort(key=lambda s: parse_shot_sort_key(as_text(s.get("shot_id"))))

                episode_meta_path = ep_dir / f"episodes_{ep_index:02d}.json"
                episode_meta = read_json(episode_meta_path) if episode_meta_path.exists() else {}
                episode_id = as_text(episode_meta.get("episode_id")) or f"EP{ep_index:02d}"

                previous_last_frame_url = ""
                scene_image_path = project_root / "assets" / "scenes" / "base" / f"{episode_id}_{scene_id_val}.png"

                for shot in valid_shots:
                    shot_id = as_text(shot.get("shot_id"))
                    if args["shot_id"] and shot_id != args["shot_id"]:
                        continue

                    shot_dir = shots_root / shot_id
                    shot_dir.mkdir(parents=True, exist_ok=True)

                    # 角色参考图 + 视觉描述
                    char_dir = project_root / "assets" / "characters" / "base"
                    char_paths: list[Path] = []
                    char_details: list[str] = []
                    for cname in normalize_characters(shot.get("characters")):
                        cp = char_dir / f"{cname}.png"
                        if cp.exists():
                            char_paths.append(cp)
                        # 读取角色卡 JSON 获取视觉描述
                        cj = char_dir / f"{cname}.json"
                        if cj.exists():
                            try:
                                from app.utils.text import character_to_human_prompt
                                ch_data = read_json(cj)
                                if isinstance(ch_data, dict):
                                    char_details.append(character_to_human_prompt(ch_data))
                            except Exception:
                                pass
                        if len(char_paths) >= max(0, args.get("max_character_refs", 2)):
                            break
                    char_names = [p.stem for p in char_paths]

                    # 读取场景图提示词
                    scene_desc = ""
                    scene_prompt_path = ep_dir / f"scene_{scene_id_val}" / "scene_prompt.json"
                    if scene_prompt_path.exists():
                        try:
                            sp_data = read_json(scene_prompt_path)
                            if isinstance(sp_data, dict):
                                scene_desc = as_text(sp_data.get("scene_prompt", ""))
                        except Exception:
                            pass

                    # 构建角色视觉参考文本
                    char_visual_text = "\n".join(char_details) if char_details else "无详细角色视觉信息"
                    scene_visual_text = scene_desc if scene_desc else (
                        f"{as_text(scene_meta.get('location'))}，{as_text(scene_meta.get('time'))}"
                    )

                    # LLM 生成视频提示词（含丰富视觉上下文）
                    use_last_frame = not args.get("disable_last_frame_chain", False)
                    user_prompt = (
                        f"目标集: {episode_id}\n"
                        f"目标场: {json.dumps(scene_meta, ensure_ascii=False)}\n"
                        f"目标镜头: {json.dumps(shot, ensure_ascii=False)}\n\n"
                        f"━━━ 角色参考（角色外观必须严格遵循）━━━\n{char_visual_text}\n\n"
                        f"━━━ 场景参考（场景环境必须严格遵循）━━━\n{scene_visual_text}\n\n"
                        f"上一镜头尾帧可用: {'是，首帧需从上一镜头末态自然衔接' if (use_last_frame and previous_last_frame_url) else '否'}\n\n"
                        f"【本集完整剧本】\n{script_text}\n"
                    )
                    llm_payload = _llm_json(llm_client, args["llm_model"], system_prompt, user_prompt)

                    video_prompt = as_text(llm_payload.get("video_prompt"))
                    if not video_prompt:
                        video_prompt = f"{as_text(shot.get('type'))}镜头，{as_text(shot.get('action'))}，电影感。"
                    video_prompt = sanitize_prompt(video_prompt)

                    neg_prompt = as_text(llm_payload.get("negative_prompt"))
                    if not neg_prompt:
                        neg_prompt = "低清晰度，模糊，畸变，过度抖动，文字水印。"

                    duration = llm_payload.get("duration", 5)
                    if not isinstance(duration, int) or duration < 4 or duration > 8:
                        duration = 5

                    ratio = as_text(llm_payload.get("ratio")) or "16:9"
                    if ratio not in {"16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "adaptive"}:
                        ratio = "16:9"

                    prompt_data = {"video_prompt": video_prompt, "negative_prompt": neg_prompt,
                                   "duration": duration, "ratio": ratio}
                    write_json(shot_dir / "video_prompt.json", prompt_data)

                    # 构建 content items（参考图 + 参考视频）
                    content_items: list[dict[str, Any]] = [
                        {"type": "text", "text": f"{video_prompt}。避免：{neg_prompt}"}
                    ]
                    ref_plan: list[dict[str, str]] = []

                    # 上一镜头尾帧（首尾帧衔接）
                    if use_last_frame and previous_last_frame_url:
                        content_items.append({
                            "type": "image_url", "image_url": {"url": previous_last_frame_url},
                            "role": "reference_image",
                        })
                        ref_plan.append({"type": "last_frame_url", "value": previous_last_frame_url})

                    # 场景参考图
                    if scene_image_path.exists():
                        scene_data_url = to_data_url(scene_image_path)
                        content_items.append({
                            "type": "image_url", "image_url": {"url": scene_data_url},
                            "role": "reference_image",
                        })
                        ref_plan.append({"type": "scene_image", "value": str(scene_image_path)})

                    # 角色参考图
                    for cp in char_paths:
                        char_data_url = to_data_url(cp)
                        content_items.append({
                            "type": "image_url", "image_url": {"url": char_data_url},
                            "role": "reference_image",
                        })
                        ref_plan.append({"type": "character_image", "value": str(cp)})

                    # 参考视频：上一镜头生成的视频（运动/风格连续性）
                    previous_video_path = None
                    if args.get("use_reference_video", True) and not args.get("disable_last_frame_chain", False):
                        # 找上一个镜头的视频
                        for prev_shot in valid_shots:
                            prev_sid = as_text(prev_shot.get("shot_id"))
                            if prev_sid == shot_id:
                                break
                            prev_video = shots_root / prev_sid / f"{prev_sid}.mp4"
                            if prev_video.exists():
                                previous_video_path = prev_video
                        if previous_video_path:
                            try:
                                video_data_url = to_data_url(previous_video_path)
                                content_items.append({
                                    "type": "video_url", "video_url": {"url": video_data_url},
                                    "role": "reference_video",
                                })
                                ref_plan.append({"type": "reference_video", "value": str(previous_video_path)})
                            except Exception:
                                pass

                    # 全局风格参考视频（从 VIDEO_REFERENCE_URL 环境变量读取，可选）
                    style_ref_url = os.environ.get("VIDEO_REFERENCE_URL", "")
                    if style_ref_url and not previous_video_path:
                        # 检查是否为当前 scene 的第一个镜头
                        shot_ids_in_scene = [as_text(s.get("shot_id")) for s in valid_shots]
                        is_first_shot = (shot_ids_in_scene.index(shot_id) == 0) if shot_id in shot_ids_in_scene else True
                        if is_first_shot:
                            content_items.append({
                                "type": "video_url", "video_url": {"url": style_ref_url},
                                "role": "reference_video",
                            })
                            ref_plan.append({"type": "style_reference_video", "value": style_ref_url})

                    asset_plan = {
                        "episode_id": episode_id, "scene_id": scene_id_val, "shot_id": shot_id,
                        "references": ref_plan, "ratio": ratio, "duration": duration,
                        "use_last_frame_chain": use_last_frame,
                    }
                    write_json(shot_dir / "asset_plan.json", asset_plan)

                    if args.get("dry_run"):
                        success_count += 1
                        continue

                    # 创建 ARK 视频任务
                    create_result = ark_client.content_generation.tasks.create(
                        model=args["video_model"],
                        content=content_items,
                        ratio=ratio,
                        duration=duration,
                        generate_audio=False,
                        watermark=False,
                        return_last_frame=use_last_frame,
                    )
                    ark_task_id = as_text(getattr(create_result, "id", ""))
                    if not ark_task_id:
                        failed.append(f"{episode_id}-{scene_id_val}-{shot_id}: 未返回 task id")
                        continue

                    write_json(shot_dir / "video_task.json",
                               {"task_id": ark_task_id, "model": args["video_model"],
                                "ratio": ratio, "duration": duration})

                    # 轮询等待
                    started = time.time()
                    video_url = ""
                    last_frame_url = ""
                    while True:
                        result = ark_client.content_generation.tasks.get(task_id=ark_task_id)
                        status = as_text(getattr(result, "status", ""))
                        if status == "succeeded":
                            content_obj = getattr(result, "content", None)
                            video_url = as_text(getattr(content_obj, "video_url", "")) if content_obj else ""
                            last_frame_url = as_text(getattr(content_obj, "last_frame_url", "")) if content_obj else ""
                            break
                        if status in {"failed", "expired"}:
                            error = as_text(getattr(result, "error", "unknown error"))
                            raise RuntimeError(f"任务状态 {status}: {error}")
                        if time.time() - started > args["max_wait_sec"]:
                            raise RuntimeError("视频任务轮询超时")
                        # 更新进度
                        _video_tasks[task_id]["current_shot"] = shot_id
                        _video_tasks[task_id]["ark_status"] = status
                        time.sleep(max(1, args["poll_interval"]))

                    if not video_url:
                        raise RuntimeError("任务成功但未返回 video_url")

                    output_video_path = shot_dir / f"{shot_id}.mp4"
                    download_file(video_url, output_video_path)

                    # 同步到 DB
                    try:
                        _update_shot_video_db(name, episode_id, scene_id_val, shot_id,
                                              task_id=ark_task_id, has_video=1)
                    except Exception:
                        pass

                    if last_frame_url:
                        previous_last_frame_url = last_frame_url
                        write_json(shot_dir / "last_frame.json", {"last_frame_url": last_frame_url})

                    success_count += 1

        _video_tasks[task_id] = {
            **args,
            "status": "succeeded",
            "success_count": success_count,
            "failed_count": len(failed),
            "failed": failed,
        }
    except Exception as exc:
        _video_tasks[task_id]["status"] = "failed"
        _video_tasks[task_id]["error"] = str(exc)


@router.post("/projects/{name}/pipeline/shot-videos")
async def start_shot_videos(
    name: str,
    episode: int = 0,
    scene_id: str = "",
    shot_id: str = "",
    script_file: str = "测试剧本.txt",
    llm_model: str = _DEFAULT_LLM_MODEL,
    video_model: str = _DEFAULT_VIDEO_MODEL,
    poll_interval: int = 10,
    max_wait_sec: int = 900,
    max_character_refs: int = 2,
    disable_last_frame_chain: bool = False,
    use_reference_video: bool = True,
    dry_run: bool = False,
):
    """步骤8：生成镜头视频（异步）。返回 task_id，通过 /video-status/{task_id} 轮询。"""
    project_root = get_project_path(name)
    analysis_root = project_root / "script_analysis"

    video_config = get_video_config()
    llm_config = get_llm_config()
    ark_key = video_config.api_key
    if not ark_key and not dry_run:
        raise HTTPException(status_code=500, detail="未配置 VIDEO_API_KEY")
    if not llm_config.api_key:
        raise HTTPException(status_code=500, detail="未配置 LLM_API_KEY")

    project_meta_path = analysis_root / "project_meta.json"
    if not project_meta_path.exists():
        raise HTTPException(status_code=404, detail="缺少 project_meta.json")

    project_meta = read_json(project_meta_path)
    total_episodes = get_total_episodes(project_meta)
    script_text = _load_script_text(script_file)
    system_prompt = _load_prompt_text("prompts/shot_video_prompt_system.txt")

    import uuid
    task_id = str(uuid.uuid4())[:8]

    task_args = {
        "project_root": str(project_root),
        "episode": episode, "scene_id": scene_id, "shot_id": shot_id,
        "script_text": script_text, "system_prompt": system_prompt,
        "llm_model": llm_model, "video_model": video_model,
        "poll_interval": poll_interval, "max_wait_sec": max_wait_sec,
        "max_character_refs": max_character_refs,
        "disable_last_frame_chain": disable_last_frame_chain,
        "use_reference_video": use_reference_video,
        "dry_run": dry_run, "ark_key": ark_key, "deepseek_key": deepseek_key,
        "total_episodes": total_episodes,
    }

    _video_tasks[task_id] = {"status": "running", "current_shot": "", "ark_status": "",
                              "success_count": 0, "failed_count": 0, "failed": []}

    import asyncio
    asyncio.create_task(asyncio.to_thread(_run_video_generation, task_id, task_args))

    return {"success": True, "data": {"task_id": task_id, "status": "running"}, "error": None}


@router.get("/projects/{name}/pipeline/video-status/{task_id}")
async def get_video_status(name: str, task_id: str):
    """轮询视频生成任务状态。"""
    task = _video_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    return {"success": True, "data": {
        "status": task.get("status"),
        "current_shot": task.get("current_shot", ""),
        "ark_status": task.get("ark_status", ""),
        "success_count": task.get("success_count", 0),
        "failed_count": task.get("failed_count", 0),
        "failed": task.get("failed", []),
        "error": task.get("error"),
    }, "error": None}
