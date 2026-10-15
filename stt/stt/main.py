"""HTTP API of the stt service. See README.md for the contract."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, StrictBool, StrictStr
from starlette.exceptions import HTTPException as StarletteHTTPException

from .audio import Decoder, decode_audio
from .config import Settings
from .engine import ModelFactory, WhisperEngine
from .errors import Cancelled, ServiceError, error_body
from .models import ModelStore
from .paths import resolve_input
from .registry import DEFAULT_MODEL
from .service import LANGUAGES, Job, SttService

log = logging.getLogger("stt")

# How often a running /transcribe checks whether its client is still there.
DISCONNECT_POLL_S = 0.5


class DownloadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: StrictStr


class TranscribeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input: StrictStr
    model: StrictStr = DEFAULT_MODEL
    language: StrictStr = "auto"
    word_timestamps: StrictBool = True


def _validation_message(exc: RequestValidationError) -> str:
    parts = []
    for err in exc.errors():
        loc = ".".join(str(x) for x in err.get("loc", ()) if x != "body")
        parts.append(f"{loc}: {err.get('msg')}" if loc else str(err.get("msg")))
    return "; ".join(parts) or "invalid request"


def create_app(
    settings: Settings | None = None,
    *,
    model_factory: ModelFactory | None = None,
    decoder: Decoder | None = None,
    store_options: dict | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    store = ModelStore(
        settings.models_dir, settings.registry, settings.hf_endpoint, **(store_options or {})
    )
    engine = WhisperEngine(
        settings.effective_cpu_threads, settings.idle_unload_s, factory=model_factory
    )
    service = SttService(store, engine, decoder or decode_audio)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        store.cleanup_stale()
        log.info(
            "stt %s: data=%s threads=%d idle_unload=%ss models=%s",
            settings.version,
            settings.data_dir,
            settings.effective_cpu_threads,
            settings.idle_unload_s,
            ",".join(settings.registry),
        )
        yield
        engine.close()

    app = FastAPI(
        title="vf-stt",
        version=settings.version,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings
    app.state.service = service

    @app.exception_handler(ServiceError)
    async def _service_error(_: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse(exc.to_body(), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(error_body("bad_request", _validation_message(exc)), status_code=400)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "not_found" if exc.status_code == 404 else "bad_request"
        status = exc.status_code if exc.status_code < 500 else 500
        if status >= 500:
            code = "internal_error"
        return JSONResponse(error_body(code, str(exc.detail)), status_code=status)

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error")
        return JSONResponse(error_body("internal_error", str(exc) or "internal error"), 500)

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "version": settings.version, "busy": service.busy}

    @app.get("/models")
    def list_models() -> list[dict]:
        return store.statuses()

    @app.post("/models/download")
    def download_model(body: DownloadRequest) -> JSONResponse:
        accepted, status = store.start_download(body.name)
        return JSONResponse(status, status_code=202 if accepted else 200)

    @app.delete("/models/{name}")
    def delete_model(name: str) -> dict:
        return service.delete_model(name)

    @app.get("/progress")
    def progress() -> dict:
        return service.progress()

    @app.post("/transcribe")
    async def transcribe(body: TranscribeRequest, request: Request) -> Response:
        if body.language not in LANGUAGES:
            raise ServiceError("bad_request", f"language must be one of: {', '.join(LANGUAGES)}")
        store.spec(body.model)
        path = resolve_input(settings.data_dir, body.input)
        if not service.try_begin(body.model):
            raise ServiceError("busy", "another transcription is running")

        job = Job(
            path=path,
            model=body.model,
            language=body.language,
            word_timestamps=body.word_timestamps,
        )
        stop = threading.Event()
        try:
            future = asyncio.get_running_loop().run_in_executor(None, service.run, job, stop)
        except BaseException:
            service.abort_begin()
            raise
        log.info("transcribe %s with %s (%s)", body.input, body.model, body.language)

        try:
            while not future.done():
                await asyncio.wait({future}, timeout=DISCONNECT_POLL_S)
                if not future.done() and not stop.is_set() and await request.is_disconnected():
                    stop.set()
        except asyncio.CancelledError:
            stop.set()
            raise
        try:
            return JSONResponse(future.result())
        except Cancelled:
            # Nobody is listening any more; the status code is only for logs.
            return Response(status_code=499)

    return app


def _configure_logging() -> None:
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
        )


def __getattr__(name: str):  # lazy module attribute so tests can import without env
    if name == "app":
        _configure_logging()
        application = create_app()
        globals()["app"] = application
        return application
    raise AttributeError(name)
