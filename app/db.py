"""SQLite 数据库模块 — 短剧项目元数据管理。"""

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

DB_DIR = Path(__file__).resolve().parent / "data"
DB_PATH = DB_DIR / "fastrabbit.db"

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    script_content TEXT DEFAULT '',
    script_filename TEXT DEFAULT '',
    total_episodes INTEGER DEFAULT 1,
    status TEXT DEFAULT 'created',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    episode_id TEXT NOT NULL,
    title TEXT DEFAULT '',
    index_num INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project_id, episode_id)
);

CREATE TABLE IF NOT EXISTS scenes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id INTEGER NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    scene_id TEXT NOT NULL,
    location TEXT DEFAULT '',
    time_text TEXT DEFAULT '',
    characters TEXT DEFAULT '[]',
    description TEXT DEFAULT '',
    scene_prompt TEXT DEFAULT '',
    has_image INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(episode_id, scene_id)
);

CREATE TABLE IF NOT EXISTS shots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scene_id INTEGER NOT NULL REFERENCES scenes(id) ON DELETE CASCADE,
    shot_id TEXT NOT NULL,
    type TEXT DEFAULT '',
    action TEXT DEFAULT '',
    characters TEXT DEFAULT '[]',
    has_video INTEGER DEFAULT 0,
    video_task_id TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(scene_id, shot_id)
);

CREATE TABLE IF NOT EXISTS characters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    age INTEGER DEFAULT 25,
    gender TEXT DEFAULT '未知',
    height INTEGER DEFAULT 170,
    weight INTEGER DEFAULT 60,
    description TEXT DEFAULT '',
    has_image INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project_id, name)
);

CREATE INDEX IF NOT EXISTS idx_episodes_project ON episodes(project_id);
CREATE INDEX IF NOT EXISTS idx_scenes_episode ON scenes(episode_id);
CREATE INDEX IF NOT EXISTS idx_shots_scene ON shots(scene_id);
CREATE INDEX IF NOT EXISTS idx_characters_project ON characters(project_id);
"""


def _get_conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        DB_DIR.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return _local.conn


def init_db() -> None:
    """初始化数据库表（幂等）。"""
    conn = _get_conn()
    conn.executescript(SCHEMA)
    conn.commit()


def get_db() -> sqlite3.Connection:
    """获取当前线程的数据库连接。"""
    conn = _get_conn()
    init_db()
    return conn


# ── 项目 CRUD ──────────────────────────────────────────────────

def create_project(name: str, script_content: str = "", script_filename: str = "",
                   total_episodes: int = 1) -> dict[str, Any]:
    db = get_db()
    try:
        db.execute(
            "INSERT INTO projects (name, script_content, script_filename, total_episodes) VALUES (?, ?, ?, ?)",
            (name, script_content, script_filename, total_episodes),
        )
        db.commit()
    except sqlite3.IntegrityError:
        raise ValueError(f"项目已存在: {name}")
    return get_project_by_name(name) or {}


def get_project_by_name(name: str) -> dict[str, Any] | None:
    db = get_db()
    row = db.execute("SELECT * FROM projects WHERE name = ?", (name,)).fetchone()
    return dict(row) if row else None


def list_projects() -> list[dict[str, Any]]:
    db = get_db()
    rows = db.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
    return [dict(r) for r in rows]


def update_project(name: str, **kwargs: Any) -> None:
    db = get_db()
    if not kwargs:
        return
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [name]
    db.execute(f"UPDATE projects SET {sets}, updated_at = CURRENT_TIMESTAMP WHERE name = ?", values)
    db.commit()


def delete_project(name: str) -> None:
    db = get_db()
    db.execute("DELETE FROM projects WHERE name = ?", (name,))
    db.commit()


def project_exists(name: str) -> bool:
    db = get_db()
    row = db.execute("SELECT 1 FROM projects WHERE name = ?", (name,)).fetchone()
    return row is not None


# ── 集 CRUD ────────────────────────────────────────────────────

def upsert_episodes(project_name: str, episodes: list[dict[str, Any]]) -> None:
    db = get_db()
    proj = get_project_by_name(project_name)
    if not proj:
        raise ValueError(f"项目不存在: {project_name}")
    proj_id = proj["id"]
    # 删除旧集
    db.execute("DELETE FROM episodes WHERE project_id = ?", (proj_id,))
    for ep in episodes:
        db.execute(
            "INSERT INTO episodes (project_id, episode_id, title, index_num) VALUES (?, ?, ?, ?)",
            (proj_id, ep["episode_id"], ep.get("title", ""), ep.get("index_num", 1)),
        )
    db.commit()


def get_episodes(project_name: str) -> list[dict[str, Any]]:
    db = get_db()
    proj = get_project_by_name(project_name)
    if not proj:
        return []
    rows = db.execute(
        "SELECT * FROM episodes WHERE project_id = ? ORDER BY index_num", (proj["id"],)
    ).fetchall()
    return [dict(r) for r in rows]


def get_episode_id_map(project_name: str) -> dict[str, int]:
    """返回 {episode_id: db_id} 映射。"""
    db = get_db()
    proj = get_project_by_name(project_name)
    if not proj:
        return {}
    rows = db.execute(
        "SELECT id, episode_id FROM episodes WHERE project_id = ?", (proj["id"],)
    ).fetchall()
    return {r["episode_id"]: r["id"] for r in rows}


# ── 场景 CRUD ──────────────────────────────────────────────────

def upsert_scenes(episode_db_id: int, scenes: list[dict[str, Any]]) -> None:
    db = get_db()
    db.execute("DELETE FROM scenes WHERE episode_id = ?", (episode_db_id,))
    for sc in scenes:
        characters = sc.get("characters", [])
        if isinstance(characters, list):
            characters = json.dumps(characters, ensure_ascii=False)
        db.execute(
            "INSERT INTO scenes (episode_id, scene_id, location, time_text, characters, description) VALUES (?, ?, ?, ?, ?, ?)",
            (episode_db_id, sc["scene_id"], sc.get("location", ""), sc.get("time", ""),
             characters, sc.get("description", "")),
        )
    db.commit()


def get_scenes(project_name: str, episode_id: str) -> list[dict[str, Any]]:
    db = get_db()
    ep_map = get_episode_id_map(project_name)
    ep_db_id = ep_map.get(episode_id)
    if not ep_db_id:
        return []
    rows = db.execute(
        "SELECT * FROM scenes WHERE episode_id = ? ORDER BY scene_id", (ep_db_id,)
    ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d["characters"] = json.loads(d["characters"])
        except (json.JSONDecodeError, TypeError):
            d["characters"] = []
        result.append(d)
    return result


def get_scene_id_map(episode_db_id: int) -> dict[str, int]:
    """返回 {scene_id: db_id} 映射。"""
    db = get_db()
    rows = db.execute(
        "SELECT id, scene_id FROM scenes WHERE episode_id = ?", (episode_db_id,)
    ).fetchall()
    return {r["scene_id"]: r["id"] for r in rows}


def update_scene(scene_db_id: int, **kwargs: Any) -> None:
    db = get_db()
    if not kwargs:
        return
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    db.execute(f"UPDATE scenes SET {sets} WHERE id = ?", list(kwargs.values()) + [scene_db_id])
    db.commit()


# ── 镜头 CRUD ──────────────────────────────────────────────────

def upsert_shots(scene_db_id: int, shots: list[dict[str, Any]]) -> None:
    db = get_db()
    db.execute("DELETE FROM shots WHERE scene_id = ?", (scene_db_id,))
    for sh in shots:
        characters = sh.get("characters", [])
        if isinstance(characters, list):
            characters = json.dumps(characters, ensure_ascii=False)
        db.execute(
            "INSERT INTO shots (scene_id, shot_id, type, action, characters) VALUES (?, ?, ?, ?, ?)",
            (scene_db_id, sh["shot_id"], sh.get("type", ""), sh.get("action", ""), characters),
        )
    db.commit()


def get_shots(project_name: str, episode_id: str, scene_id: str) -> list[dict[str, Any]]:
    db = get_db()
    ep_map = get_episode_id_map(project_name)
    ep_db_id = ep_map.get(episode_id)
    if not ep_db_id:
        return []
    sc_map = get_scene_id_map(ep_db_id)
    sc_db_id = sc_map.get(scene_id)
    if not sc_db_id:
        return []
    rows = db.execute(
        "SELECT * FROM shots WHERE scene_id = ? ORDER BY shot_id", (sc_db_id,)
    ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d["characters"] = json.loads(d["characters"])
        except (json.JSONDecodeError, TypeError):
            d["characters"] = []
        result.append(d)
    return result


def update_shot_video(scene_db_id: int, shot_id: str, task_id: str = "", has_video: int = 1) -> None:
    db = get_db()
    db.execute(
        "UPDATE shots SET has_video = ?, video_task_id = ? WHERE scene_id = ? AND shot_id = ?",
        (has_video, task_id, scene_db_id, shot_id),
    )
    db.commit()


# ── 角色 CRUD ──────────────────────────────────────────────────

def upsert_characters(project_name: str, characters: list[dict[str, Any]]) -> None:
    db = get_db()
    proj = get_project_by_name(project_name)
    if not proj:
        raise ValueError(f"项目不存在: {project_name}")
    proj_id = proj["id"]
    db.execute("DELETE FROM characters WHERE project_id = ?", (proj_id,))
    for ch in characters:
        db.execute(
            "INSERT INTO characters (project_id, name, age, gender, height, weight, description) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (proj_id, ch["name"], ch.get("age", 25), ch.get("gender", "未知"),
             ch.get("height", 170), ch.get("weight", 60), ch.get("description", "")),
        )
    db.commit()


def get_characters(project_name: str) -> list[dict[str, Any]]:
    db = get_db()
    proj = get_project_by_name(project_name)
    if not proj:
        return []
    rows = db.execute(
        "SELECT * FROM characters WHERE project_id = ? ORDER BY id", (proj["id"],)
    ).fetchall()
    return [dict(r) for r in rows]


def update_character_image(project_name: str, name: str, has_image: int = 1) -> None:
    db = get_db()
    proj = get_project_by_name(project_name)
    if not proj:
        return
    db.execute(
        "UPDATE characters SET has_image = ? WHERE project_id = ? AND name = ?",
        (has_image, proj["id"], name),
    )
    db.commit()


# ── 项目统计 ──────────────────────────────────────────────────

def get_project_stats(project_name: str) -> dict[str, Any]:
    """获取项目完整统计信息（替代文件扫描）。"""
    db = get_db()
    proj = get_project_by_name(project_name)
    if not proj:
        return {}

    proj_id = proj["id"]
    ep_count = db.execute("SELECT COUNT(*) as c FROM episodes WHERE project_id = ?", (proj_id,)).fetchone()["c"]
    sc_count = db.execute(
        "SELECT COUNT(*) as c FROM scenes WHERE episode_id IN (SELECT id FROM episodes WHERE project_id = ?)", (proj_id,)
    ).fetchone()["c"]
    sh_count = db.execute(
        "SELECT COUNT(*) as c FROM shots WHERE scene_id IN (SELECT s.id FROM scenes s JOIN episodes e ON s.episode_id = e.id WHERE e.project_id = ?)", (proj_id,)
    ).fetchone()["c"]
    ch_count = db.execute("SELECT COUNT(*) as c FROM characters WHERE project_id = ?", (proj_id,)).fetchone()["c"]
    ch_names = [r["name"] for r in db.execute("SELECT name FROM characters WHERE project_id = ?", (proj_id,)).fetchall()]
    scene_img_count = db.execute(
        "SELECT COUNT(*) as c FROM scenes WHERE episode_id IN (SELECT id FROM episodes WHERE project_id = ?) AND has_image = 1", (proj_id,)
    ).fetchone()["c"]
    shot_vid_count = db.execute(
        "SELECT COUNT(*) as c FROM shots WHERE scene_id IN (SELECT s.id FROM scenes s JOIN episodes e ON s.episode_id = e.id WHERE e.project_id = ?) AND has_video = 1", (proj_id,)
    ).fetchone()["c"]

    episodes_list = []
    for ep in get_episodes(project_name):
        ep_scenes = get_scenes(project_name, ep["episode_id"])
        episodes_list.append({
            "episode_id": ep["episode_id"],
            "title": ep["title"],
            "index_num": ep["index_num"],
            "scene_count": len(ep_scenes),
            "scenes": [{
                "scene_id": s["scene_id"],
                "location": s["location"],
                "time": s["time_text"],
                "has_shots": db.execute("SELECT COUNT(*) as c FROM shots WHERE scene_id = ?", (s["id"],)).fetchone()["c"] > 0,
                "has_prompt": bool(s["scene_prompt"]),
            } for s in ep_scenes],
        })

    return {
        "name": proj["name"],
        "total_episodes": proj["total_episodes"],
        "status": proj["status"],
        "script_filename": proj["script_filename"],
        "character_count": ch_count,
        "character_names": ch_names,
        "scene_image_count": scene_img_count,
        "shot_video_count": shot_vid_count,
        "episodes": episodes_list,
        "episode_count": ep_count,
        "scene_count": sc_count,
        "shot_count": sh_count,
        "created_at": proj["created_at"],
        "updated_at": proj["updated_at"],
    }


# ── 文件系统同步（兼容旧项目）─────────────────────────────────

def sync_project_from_files(project_root: Path, project_name: str) -> None:
    """从文件系统的 script_analysis 目录同步元数据到 DB。"""
    from app.utils.io import read_json, read_project_meta, get_total_episodes
    from app.utils.text import as_text

    analysis_dir = project_root / "script_analysis"
    if not analysis_dir.exists():
        return

    meta_path = analysis_dir / "project_meta.json"
    if not meta_path.exists():
        return

    meta = read_project_meta(meta_path)
    total_episodes = get_total_episodes(meta)

    # 读剧本文件
    script_content = ""
    script_path = project_root / "script.txt"
    if not script_path.exists():
        script_path = project_root.parent / "测试剧本.txt"
    if script_path.exists():
        script_content = script_path.read_text(encoding="utf-8")

    # 创建或更新项目
    if not project_exists(project_name):
        create_project(project_name, script_content=script_content, total_episodes=total_episodes)
    else:
        update_project(project_name, script_content=script_content, total_episodes=total_episodes)

    # 同步集和场景
    for ep_idx in range(1, total_episodes + 1):
        ep_dir = analysis_dir / f"ep_{ep_idx:02d}"
        ep_meta_path = ep_dir / f"episodes_{ep_idx:02d}.json"
        scenes_path = ep_dir / "scenes.json"

        if not ep_dir.exists():
            continue

        episode_id = f"EP{ep_idx:02d}"
        title = f"第{ep_idx}集"
        if ep_meta_path.exists():
            ep_meta = read_json(ep_meta_path)
            if isinstance(ep_meta, dict):
                episode_id = as_text(ep_meta.get("episode_id")) or episode_id
                title = as_text(ep_meta.get("title")) or title

        # Upsert episode
        db = get_db()
        proj = get_project_by_name(project_name)
        if not proj:
            return
        proj_id = proj["id"]
        db.execute(
            "INSERT OR REPLACE INTO episodes (id, project_id, episode_id, title, index_num) VALUES ((SELECT id FROM episodes WHERE project_id = ? AND episode_id = ?), ?, ?, ?, ?)",
            (proj_id, episode_id, proj_id, episode_id, title, ep_idx),
        )

        if not scenes_path.exists():
            continue
        scenes = read_json(scenes_path)
        if not isinstance(scenes, list):
            continue

        ep_map = get_episode_id_map(project_name)
        ep_db_id = ep_map.get(episode_id)
        if not ep_db_id:
            continue

        for scene in scenes:
            if not isinstance(scene, dict):
                continue
            sid = as_text(scene.get("scene_id"))
            if not sid:
                continue

            characters = scene.get("characters", [])
            if isinstance(characters, list):
                characters = json.dumps(characters, ensure_ascii=False)

            # 读取 scene_prompt
            scene_dir = ep_dir / f"scene_{sid}"
            prompt_path = scene_dir / "scene_prompt.json"
            scene_prompt = ""
            has_image = 0
            if prompt_path.exists():
                prompt_data = read_json(prompt_path)
                if isinstance(prompt_data, dict):
                    scene_prompt = as_text(prompt_data.get("scene_prompt", ""))
            # 检查是否有场景图
            img_path = project_root / "assets" / "scenes" / "base" / f"{episode_id}_{sid}.png"
            if img_path.exists():
                has_image = 1

            db.execute(
                "INSERT OR REPLACE INTO scenes (id, episode_id, scene_id, location, time_text, characters, description, scene_prompt, has_image) VALUES ((SELECT id FROM scenes WHERE episode_id = ? AND scene_id = ?), ?, ?, ?, ?, ?, ?, ?, ?)",
                (ep_db_id, sid, ep_db_id, sid,
                 as_text(scene.get("location")), as_text(scene.get("time")),
                 characters, as_text(scene.get("description")), scene_prompt, has_image),
            )

            # 同步镜头
            shots_path = scene_dir / "shots.json"
            if not shots_path.exists():
                continue
            shots = read_json(shots_path)
            if not isinstance(shots, list):
                continue

            sc_map = get_scene_id_map(ep_db_id)
            sc_db_id = sc_map.get(sid)
            if not sc_db_id:
                continue

            for shot in shots:
                if not isinstance(shot, dict):
                    continue
                sh_id = as_text(shot.get("shot_id"))
                if not sh_id:
                    continue
                sh_chars = shot.get("characters", [])
                if isinstance(sh_chars, list):
                    sh_chars = json.dumps(sh_chars, ensure_ascii=False)
                has_video = 0
                video_task_id = ""
                shot_dir = project_root / "assets" / "shots" / sh_id
                if shot_dir.exists():
                    if (shot_dir / f"{sh_id}.mp4").exists():
                        has_video = 1
                    task_path = shot_dir / "video_task.json"
                    if task_path.exists():
                        task_data = read_json(task_path)
                        if isinstance(task_data, dict):
                            video_task_id = as_text(task_data.get("task_id", ""))

                db.execute(
                    "INSERT OR REPLACE INTO shots (id, scene_id, shot_id, type, action, characters, has_video, video_task_id) VALUES ((SELECT id FROM shots WHERE scene_id = ? AND shot_id = ?), ?, ?, ?, ?, ?, ?, ?)",
                    (sc_db_id, sh_id, sc_db_id, sh_id,
                     as_text(shot.get("type")), as_text(shot.get("action")),
                     sh_chars, has_video, video_task_id),
                )

    # 同步角色
    char_dir = project_root / "assets" / "characters" / "base"
    if char_dir.exists():
        for char_file in sorted(char_dir.glob("*.json")):
            try:
                char_data = read_json(char_file)
                if not isinstance(char_data, dict):
                    continue
                name = as_text(char_data.get("name"))
                if not name:
                    continue
                has_image = 1 if (char_dir / f"{name}.png").exists() else 0
                db = get_db()
                db.execute(
                    "INSERT OR REPLACE INTO characters (id, project_id, name, age, gender, height, weight, description, has_image) VALUES ((SELECT id FROM characters WHERE project_id = ? AND name = ?), ?, ?, ?, ?, ?, ?, ?, ?)",
                    (proj_id, name, proj_id, name,
                     char_data.get("age", 25), char_data.get("gender", "未知"),
                     char_data.get("height", 170), char_data.get("weight", 60),
                     as_text(char_data.get("description", "")), has_image),
                )
            except Exception:
                pass

    update_project(project_name, status="synced")
    db = get_db()
    db.commit()
