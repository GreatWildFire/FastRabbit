"""FastAPI 应用入口。"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

from app.config import REPO_ROOT, init_config
from app.routers import projects, pipeline

init_config()

app = FastAPI(title="FastRabbit API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router, prefix="/api")
app.include_router(pipeline.router, prefix="/api")


@app.get("/api/health")
async def health():
    return {"status": "ok"}


# 静态文件：/static 路径提供前端 HTML 和产物预览
static_dir = Path(__file__).resolve().parent / "static"
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    """返回首页。"""
    return _serve_html("index.html")


@app.get("/workspace.html", response_class=HTMLResponse)
async def workspace():
    """返回项目工作台页面。"""
    return _serve_html("workspace.html")


def _serve_html(filename: str) -> str:
    path = static_dir / filename
    if path.exists():
        return path.read_text(encoding="utf-8")
    return f"<html><body><h1>404</h1><p>{filename} not found</p></body></html>"
