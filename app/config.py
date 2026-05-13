"""应用配置：路径、API Key 管理。"""

import os
from pathlib import Path

from app.utils.io import load_env_file

# 仓库根目录 = FastAPI app 的父目录
REPO_ROOT = Path(__file__).resolve().parent.parent


def init_config(env_file: str = ".env") -> None:
    """加载 .env 文件到环境变量。"""
    env_path = (REPO_ROOT / env_file).resolve()
    load_env_file(env_path)


def get_api_key(name: str) -> str:
    """获取 API Key，若缺失返回空字符串。"""
    return os.environ.get(name, "").strip()


def get_prompt_path(relative_path: str) -> Path:
    """返回 prompt 文件的绝对路径。"""
    return (REPO_ROOT / relative_path).resolve()


def get_script_path(relative_path: str) -> Path:
    """返回剧本文件的绝对路径。"""
    return (REPO_ROOT / relative_path).resolve()


def get_project_path(name: str) -> Path:
    """返回项目目录的绝对路径。"""
    return (REPO_ROOT / name).resolve()
