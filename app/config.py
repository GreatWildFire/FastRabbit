"""应用配置：路径、模型供应商管理。"""

import os
from dataclasses import dataclass
from pathlib import Path

from app.utils.io import load_env_file

REPO_ROOT = Path(__file__).resolve().parent.parent


def init_config(env_file: str = ".env") -> None:
    """加载 .env 文件到环境变量。"""
    env_path = (REPO_ROOT / env_file).resolve()
    load_env_file(env_path)


@dataclass
class ProviderConfig:
    provider: str      # 供应商标识，如 deepseek / openai / nano-banana / ark
    api_key: str
    base_url: str
    model: str


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


# ── LLM 配置（剧本拆解、角色提取、提示词生成）──────────────────

def get_llm_config() -> ProviderConfig:
    """获取 LLM 供应商配置，支持向后兼容旧变量名 DEEPSEEK_API_KEY。"""
    return ProviderConfig(
        provider=_env("LLM_PROVIDER", "deepseek"),
        api_key=_env("LLM_API_KEY") or _env("DEEPSEEK_API_KEY"),
        base_url=_env("LLM_BASE_URL", "https://api.deepseek.com"),
        model=_env("LLM_MODEL", "deepseek-v4-flash"),
    )


# ── 生图配置（角色图、场景图）────────────────────────────────────

def get_image_config() -> ProviderConfig:
    """获取生图供应商配置，支持向后兼容旧变量名 NANO_BANANA_API_KEY。"""
    return ProviderConfig(
        provider=_env("IMAGE_PROVIDER", "nano-banana"),
        api_key=_env("IMAGE_API_KEY") or _env("NANO_BANANA_API_KEY"),
        base_url=_env("IMAGE_BASE_URL", "https://grsai.dakka.com.cn/v1/draw/nano-banana"),
        model=_env("IMAGE_MODEL", "nano-banana-fast"),
    )


# ── 视频生成配置（镜头视频）──────────────────────────────────────

def get_video_config() -> ProviderConfig:
    """获取视频生成供应商配置，支持向后兼容旧变量名 ARK_API_KEY。"""
    return ProviderConfig(
        provider=_env("VIDEO_PROVIDER", "ark"),
        api_key=_env("VIDEO_API_KEY") or _env("ARK_API_KEY"),
        base_url=_env("VIDEO_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
        model=_env("VIDEO_MODEL", "doubao-seedance-2-0-250528"),
    )


# ── 便捷方法 ─────────────────────────────────────────────────────

def get_api_key(name: str) -> str:
    """直接获取某个环境变量（兼容旧代码）。"""
    return _env(name)


def get_prompt_path(relative_path: str) -> Path:
    """返回 prompt 文件的绝对路径。"""
    return (REPO_ROOT / relative_path).resolve()


def get_script_path(relative_path: str) -> Path:
    """返回剧本文件的绝对路径。"""
    return (REPO_ROOT / relative_path).resolve()


def get_project_path(name: str) -> Path:
    """返回项目目录的绝对路径，拒绝路径穿越。"""
    sanitized = name.lstrip("/").replace("\\", "/").strip()
    if not sanitized or ".." in sanitized or sanitized.startswith("/") or sanitized.startswith("~"):
        raise ValueError(f"非法项目名称: {name}")
    resolved = (REPO_ROOT / sanitized).resolve()
    if not str(resolved).startswith(str(REPO_ROOT.resolve())):
        raise ValueError(f"项目路径越权: {name}")
    return resolved
