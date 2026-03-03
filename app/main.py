from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.demo_mode:
        from scripts.seed_demo import run_seed
        await run_seed()
    yield


app = FastAPI(
    title="中医慢病与治未病平台",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url=None,
    lifespan=lifespan,
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

app.include_router(auth_router)
app.include_router(h5_router)
app.include_router(admin_router)
