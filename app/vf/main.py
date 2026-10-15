"""The app process: API + the built frontend, background jobs and scheduler."""

from __future__ import annotations

import asyncio
import importlib
import logging
import pkgutil
import sys
from contextlib import asynccontextmanager
from types import ModuleType

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from vf.core import db, errors, events, jobs, logs, migrations, models_registry, prompts
from vf.core.config import Config, get_config, set_config
from vf.core.google import journal
from vf.core.routes import router as core_router
from vf.core.routes import spa_fallback
from vf.core.scheduler import scheduler

log = logging.getLogger("vf")

NOT_BUILT = """<!doctype html><html><head><meta charset="utf-8"><title>Vertex AI Factory</title></head>
<body style="font-family:sans-serif;padding:2rem"><h1>Vertex AI Factory</h1>
<p>The API is running, but the web interface is not built into this image.</p></body></html>"""


def discover_modules() -> list[ModuleType]:
    """Import every package under ``vf.modules``. Importing registers job handlers,
    settings, scheduler hooks and chat modes; a ``router`` attribute adds routes."""
    import vf.modules as pkg

    found = []
    for info in sorted(pkgutil.iter_modules(pkg.__path__), key=lambda i: i.name):
        if info.name.startswith("_"):
            continue
        found.append(importlib.import_module(f"vf.modules.{info.name}"))
    return found


def prepare_storage(cfg: Config) -> None:
    for path in (cfg.data_dir, cfg.files_dir, cfg.secrets_dir, cfg.cache_dir, cfg.tmp_dir, cfg.backups_dir,
                 cfg.data_dir / "models", cfg.data_dir / "fonts", cfg.data_dir / "update"):
        path.mkdir(parents=True, exist_ok=True)
    cfg.secrets_dir.chmod(0o700)


def startup_sync(cfg: Config) -> None:
    """Everything before the loop starts serving: storage, database, seed, checks."""
    prepare_storage(cfg)
    database = db.init(cfg.db_path)
    applied = migrations.apply_all(database)
    if applied:
        log.info("applied migrations: %s", ", ".join(applied))
    counts = models_registry.seed()
    log.info("model registry: %s", counts)
    closed = journal.recover()
    if closed:
        log.warning("closed %d Google calls interrupted by a restart", closed)
    problems = prompts.check_all()
    for problem in problems:
        log.error("prompt problem: %s", problem)


def create_app(config: Config | None = None, *, run_background: bool = True) -> FastAPI:
    if config is not None:
        set_config(config)
    cfg = get_config()
    modules = discover_modules()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        startup_sync(cfg)
        events.bind_loop(asyncio.get_running_loop())
        for mod in modules:
            hook = getattr(mod, "on_startup", None)
            if hook:
                await hook()
        if run_background:
            await jobs.runner.start()
            await scheduler.start()
        log.info("Vertex AI Factory %s ready (google: %s)", cfg.version, cfg.google_mode)
        try:
            yield
        finally:
            if run_background:
                await scheduler.stop()
                await jobs.runner.stop()
            for mod in modules:
                hook = getattr(mod, "on_shutdown", None)
                if hook:
                    try:
                        await hook()
                    except Exception:
                        log.exception("shutdown hook of %s failed", mod.__name__)
            db.close()

    app = FastAPI(title="Vertex AI Factory", version=cfg.version, lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
    errors.install(app)
    app.include_router(core_router)
    for mod in modules:
        router = getattr(mod, "router", None)
        if router is not None:
            app.include_router(router)

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str, request: Request):
        if path.startswith(("api/", "files/")) or path in ("api", "files"):
            return JSONResponse({"error": {"code": "not_found", "message": "not found", "details": {}}},
                                status_code=404)
        target = spa_fallback(request)
        if target is None:
            return HTMLResponse(NOT_BUILT)
        headers = {"Cache-Control": "no-cache"} if target.name == "index.html" else {
            "Cache-Control": "public, max-age=31536000, immutable"} if "/_nuxt/" in str(target) else {}
        return FileResponse(target, headers=headers)

    return app


def make_server(app: FastAPI, *, host: str = "0.0.0.0", port: int = 8787):
    """uvicorn server that ends the open event streams as soon as shutdown starts.
    Docker sends SIGTERM and kills the container 30 s later (``stop_grace_period``);
    without this an open browser tab would hold the exit for the 10 s graceful timeout."""
    import uvicorn

    class Server(uvicorn.Server):
        def handle_exit(self, sig, frame) -> None:
            events.close_streams_soon()
            super().handle_exit(sig, frame)

    config = uvicorn.Config(app, host=host, port=port, log_config=None, proxy_headers=False,
                            timeout_graceful_shutdown=10)
    return Server(config)


def run() -> None:
    logs.configure()
    server = make_server(create_app())
    try:
        server.run()
    except KeyboardInterrupt:
        pass
    if not server.started:
        sys.exit(3)  # what uvicorn.run does when startup fails


if __name__ == "__main__":
    run()
