"""FastAPI 应用装配：CORS、路由、以及构建好的前端静态文件（若有）。

开发时前端跑 Vite（5173），通过 ``VITE_API_BASE`` 指向本服务；
生产时 ``web/dist`` 存在就挂到 ``/``，一个进程同时提供 API 与页面。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from skylens import __version__
from skylens.api.routes import router

REPO_ROOT = Path(__file__).resolve().parents[3]
WEB_DIST = REPO_ROOT / "web" / "dist"


def create_app() -> FastAPI:
    app = FastAPI(
        title="天镜 SkyLens API",
        version=__version__,
        summary="多源天气事实包与可溯源解释（个人非商用，不发布预报）",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    app.include_router(router)
    if WEB_DIST.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
    return app


app = create_app()
