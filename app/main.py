from contextlib import asynccontextmanager
import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.demo_mode:
        from scripts.seed_demo import run_seed
        await run_seed()
        from scripts.seed_rich_demo import run_rich_seed
        await run_rich_seed()
    # 启动后台定时任务（每日 + 5分钟扫描）
    from app.tasks import run_scheduler, run_5min_scanner
    task_daily = asyncio.create_task(run_scheduler())
    task_scan = asyncio.create_task(run_5min_scanner())
    yield
    task_daily.cancel()
    task_scan.cancel()
    for t in [task_daily, task_scan]:
        try:
            await t
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="中医慢病与治未病平台",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url=None,
    lifespan=lifespan,
)

# CORS — 来源列表由 settings.cors_origins 控制（见 config.py / .env CORS_ORIGINS）
# 注意：allow_origins=["*"] 与 allow_credentials=True 不兼容，必须明确列出来源
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Jinja2 templates (shared instance for all routers to import)
templates = Jinja2Templates(directory="app/templates")


@app.get("/healthz", tags=["system"])
async def healthz():
    return JSONResponse({"status": "ok", "version": "1.0.0"})


# ── Tools layer (JSON API) ──
from app.tools import router as tools_router  # noqa: E402
from app.tools.response import register_exception_handlers  # noqa: E402

register_exception_handlers(app)
app.include_router(tools_router)

# ── GUI layer (Jinja2 SSR) ──
from app.gui.auth_pages import router as auth_router  # noqa: E402
from app.gui.h5_pages import router as h5_router  # noqa: E402
from app.gui.admin_pages import router as admin_router  # noqa: E402
from app.gui.his_pages import router as his_router  # noqa: E402

app.include_router(auth_router)
app.include_router(h5_router)
app.include_router(admin_router)
app.include_router(his_router)
