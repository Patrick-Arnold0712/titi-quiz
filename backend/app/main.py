from __future__ import annotations

import base64
import hmac
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app.api import api_router
from app.core.config import get_settings
from app.core.db import SessionLocal, init_db
from app.seeds import seed_all

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with SessionLocal() as db:
        seed_all(db)
    yield


settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)


# 公网隧道只应暴露给知道口令的人。默认不启用，本地/测试完全不受影响；
# 启动公网实例时设置 TTK_BASIC_AUTH=用户名:密码 即可给所有页面和 API 加一道 Basic Auth。
_BASIC_AUTH = os.getenv("TTK_BASIC_AUTH", "").strip()


@app.middleware("http")
async def basic_auth_middleware(request: Request, call_next):
    if _BASIC_AUTH:
        expected = "Basic " + base64.b64encode(_BASIC_AUTH.encode("utf-8")).decode("ascii")
        supplied = request.headers.get("authorization", "")
        if not hmac.compare_digest(supplied, expected):
            return Response(
                "需要登录才能访问题题的库",
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="ttk"'},
            )
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)


@app.get("/")
def index():
    f = STATIC_DIR / "index.html"
    if f.exists():
        return FileResponse(str(f))
    return {"app": settings.app_name, "docs": "/docs", "health": "/api/health"}


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
