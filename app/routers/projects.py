"""项目查询 + 管理端点。"""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import REPO_ROOT, get_project_path
from app.db import (
    get_project_by_name, list_projects as db_list_projects,
    create_project as db_create_project, update_project, delete_project,
    project_exists, get_project_stats, get_episodes, get_scenes, get_shots,
    sync_project_from_files, init_db,
)
from app.utils.io import discover_projects

router = APIRouter(tags=["projects"])


class CreateProjectBody(BaseModel):
    name: str
    script_text: str = ""


class UploadScriptBody(BaseModel):
    script_text: str


# ── 项目列表 ────────────────────────────────────────────────────

@router.get("/projects")
async def list_projects():
    """列出所有项目（DB + 文件系统发现）。"""
    # 确保 DB 已初始化
    init_db()

    db_projects = db_list_projects()
    db_names = {p["name"] for p in db_projects}

    # 合并文件系统项目
    fs_projects = discover_projects(REPO_ROOT)
    result = list(db_projects)
    for fp in fs_projects:
        if fp["name"] not in db_names:
            result.append({
                "id": None,
                "name": fp["name"],
                "script_content": "",
                "script_filename": "",
                "total_episodes": fp["total_episodes"],
                "status": "filesystem_only",
                "created_at": None,
                "updated_at": None,
            })

    return {"success": True, "data": result, "error": None}


# ── 创建项目 ────────────────────────────────────────────────────

@router.post("/projects")
async def create_project(body: CreateProjectBody):
    """创建新项目。"""
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="项目名不能为空")

    init_db()
    try:
        proj = db_create_project(name, script_content=body.script_text)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    # 创建项目目录
    project_root = get_project_path(name)
    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / "script_analysis").mkdir(parents=True, exist_ok=True)
    (project_root / "assets" / "characters" / "base").mkdir(parents=True, exist_ok=True)
    (project_root / "assets" / "scenes" / "base").mkdir(parents=True, exist_ok=True)
    (project_root / "assets" / "shots").mkdir(parents=True, exist_ok=True)

    # 写入 script.txt 文件
    if body.script_text:
        script_path = project_root / "script.txt"
        script_path.write_text(body.script_text, encoding="utf-8")

    return {"success": True, "data": proj, "error": None}


# ── 删除项目 ────────────────────────────────────────────────────

@router.delete("/projects/{name}")
async def delete_project_endpoint(name: str):
    """删除项目（仅从 DB 删除，不删除文件）。"""
    init_db()
    if not project_exists(name):
        raise HTTPException(status_code=404, detail=f"项目不存在: {name}")
    delete_project(name)
    return {"success": True, "data": None, "error": None}


# ── 上传剧本 ────────────────────────────────────────────────────

@router.post("/projects/{name}/upload-script")
async def upload_script(name: str, body: UploadScriptBody):
    """上传/替换项目剧本。"""
    init_db()

    # 如果项目不存在于 DB，先创建
    if not project_exists(name):
        project_root = get_project_path(name)
        if project_root.exists():
            db_create_project(name)
        else:
            raise HTTPException(status_code=404, detail=f"项目不存在: {name}")

    update_project(name, script_content=body.script_text, script_filename="script.txt")

    # 同时写入文件
    project_root = get_project_path(name)
    project_root.mkdir(parents=True, exist_ok=True)
    script_path = project_root / "script.txt"
    script_path.write_text(body.script_text, encoding="utf-8")

    return {"success": True, "data": {"filename": str(script_path), "size": len(body.script_text)}, "error": None}


# ── 获取剧本 ────────────────────────────────────────────────────

@router.get("/projects/{name}/script")
async def get_script(name: str):
    """获取项目剧本内容。"""
    init_db()
    proj = get_project_by_name(name)
    script_text = ""
    if proj and proj.get("script_content"):
        script_text = proj["script_content"]
    else:
        # 尝试从文件读取
        project_root = get_project_path(name)
        for fname in ("script.txt", "测试剧本.txt"):
            sp = project_root / fname
            if not sp.exists():
                sp = REPO_ROOT / fname
            if sp.exists():
                script_text = sp.read_text(encoding="utf-8")
                break

    return {"success": True, "data": {"content": script_text}, "error": None}


# ── 从文件同步 ──────────────────────────────────────────────────

@router.post("/projects/{name}/sync")
async def sync_project(name: str):
    """从文件系统同步项目数据到数据库。"""
    project_root = get_project_path(name)
    if not project_root.exists():
        raise HTTPException(status_code=404, detail=f"项目目录不存在: {project_root}")

    init_db()
    try:
        sync_project_from_files(project_root, name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"同步失败: {e}")

    stats = get_project_stats(name)
    return {"success": True, "data": stats, "error": None}


# ── 项目详情 ────────────────────────────────────────────────────

@router.get("/projects/{name}")
async def get_project(name: str):
    """获取项目概览（DB 优先，自动同步文件系统项目）。"""
    project_root = get_project_path(name)
    if not project_root.exists() and not project_exists(name):
        raise HTTPException(status_code=404, detail=f"项目不存在: {name}")

    init_db()

    # 如果 DB 中不存在，自动从文件同步
    if not project_exists(name):
        try:
            sync_project_from_files(project_root, name)
        except Exception:
            pass

    stats = get_project_stats(name)
    if not stats:
        # 如果同步后仍为空，说明没有文件数据
        if project_exists(name):
            proj = get_project_by_name(name)
            if proj:
                stats = {
                    "name": name, "total_episodes": proj.get("total_episodes", 1),
                    "status": proj.get("status", "created"), "script_filename": "",
                    "character_count": 0, "character_names": [],
                    "scene_image_count": 0, "shot_video_count": 0,
                    "episodes": [], "episode_count": 0, "scene_count": 0, "shot_count": 0,
                    "created_at": proj.get("created_at"), "updated_at": proj.get("updated_at"),
                }

    return {"success": True, "data": stats or {}, "error": None}


# ── 集列表 ──────────────────────────────────────────────────────

@router.get("/projects/{name}/episodes")
async def list_episodes(name: str):
    """获取项目的所有集。"""
    init_db()
    episodes = get_episodes(name)

    # DB 回退到文件系统
    if not episodes:
        from app.utils.io import read_json
        from app.utils.text import as_text
        project_root = get_project_path(name)
        analysis_root = project_root / "script_analysis"
        for ep_idx in range(1, 10):
            ep_dir = analysis_root / f"ep_{ep_idx:02d}"
            scenes_path = ep_dir / "scenes.json"
            if scenes_path.exists():
                try:
                    scenes = read_json(scenes_path)
                    episode_id = f"EP{ep_idx:02d}"
                    title = f"第{ep_idx}集"
                    episodes.append({
                        "id": None, "project_id": None, "episode_id": episode_id,
                        "title": title, "index_num": ep_idx,
                        "scenes": [{
                            "scene_id": as_text(s.get("scene_id", "")),
                            "location": as_text(s.get("location", "")),
                            "time": as_text(s.get("time", "")),
                            "characters": s.get("characters", []),
                        } for s in (scenes if isinstance(scenes, list) else []) if isinstance(s, dict)],
                    })
                except Exception:
                    pass

    return {"success": True, "data": episodes, "error": None}


# ── 场景列表 ────────────────────────────────────────────────────

@router.get("/projects/{name}/episodes/{ep}/scenes")
async def list_scenes(name: str, ep: int):
    """获取指定集的场景列表。"""
    init_db()
    episode_id = f"EP{ep:02d}"
    scenes = get_scenes(name, episode_id)
    return {"success": True, "data": scenes, "error": None}


# ── 镜头列表 ────────────────────────────────────────────────────

@router.get("/projects/{name}/episodes/{ep}/scenes/{scene_id}/shots")
async def list_shots(name: str, ep: int, scene_id: str):
    """获取指定场景的镜头列表。"""
    init_db()
    episode_id = f"EP{ep:02d}"
    shots = get_shots(name, episode_id, scene_id)
    return {"success": True, "data": shots, "error": None}
