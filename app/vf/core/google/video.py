"""Video from Google: Veo (long operations in ``us-central1``) and Gemini Omni
(the Interactions API in ``global``).

Every request is a row in the spend journal, like ``gateway.generate``:

- **Veo** answers with an operation name at once and the clip minutes later.
  The name goes to the journal row (``operation_name``) and to the caller
  (``on_submitted``) before the first poll, so after a restart the same
  operation is waited for again (``wait_veo``) and nothing is paid twice.
  The operation is polled once a minute, up to ``google.video_wait_minutes``.
  Failed polls are journaled as ``video_poll`` rows at $0 with Google's text.
  Veo cannot be stopped: a clip stopped after submit is closed as ``cancelled``
  at its full price, because Google finishes and bills it anyway.
- **Omni** is one HTTP request that returns the clip inline. ``extend=True``
  asks it to continue the attached video. If Vertex rejects the
  ``generation_config`` key, the request is sent again without it (a new
  journal row, not a spent attempt).

Stub mode (``VF_GOOGLE_MODE=stub``) never calls Google: the clip is
``stub.video_fixture(aspect)``; ``[stub:blocked]``, ``[stub:refused]`` and
``[stub:error=<code>]`` in the prompt simulate failures.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from vf.core import settings
from vf.core.config import get_config
from vf.core.google import credentials, gateway, journal, stub
from vf.core.google.errors import GoogleCallError, classify
from vf.core.google.gateway import Blob, PromptInfo
from vf.core.google.limiter import limiter

log = logging.getLogger("vf.google.video")

POLL_SECONDS = 60.0
OMNI_TIMEOUT = 600.0
INTERACTIONS_URL = "https://aiplatform.googleapis.com/v1beta1/projects/{project}/locations/global/interactions"
SAFETY_MARKERS = ("responsible ai", "safety", "blocked", "prohibited content", "content policy")
CANCEL_AFTER_SUBMIT = ("Stopped after Google had started the clip. Veo cannot be stopped: "
                       "Google finishes the clip and bills it.")


@dataclass
class VideoAnswer:
    """A finished clip and what it cost."""

    data: bytes
    mime: str
    model_id: str
    call_ids: list[int] = field(default_factory=list)
    cost_usd: float = 0.0
    operation_name: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    stub: bool = False


# ── shared helpers ──────────────────────────────────────────────────────────


def _cancelled(cancel: Callable[[], bool] | None) -> bool:
    try:
        return bool(cancel and cancel())
    except Exception:
        return False


def _fail(err: GoogleCallError, call_ids: list[int]) -> GoogleCallError:
    err.call_ids = list(call_ids)
    err.details["call_ids"] = list(call_ids)
    return err


def _pause(err: GoogleCallError, errors_used: int) -> float:
    if err.code == "rate_limited":
        return max(err.retry_after or 0.0, gateway.RATE_LIMIT_PAUSE)
    return min(gateway.BASE_BACKOFF * (2 ** (errors_used - 1)), gateway.MAX_BACKOFF)


def _stub_error(exc: stub.StubFailure) -> GoogleCallError:
    return GoogleCallError(exc.code, f"[stub] simulated {exc.code}",
                           retryable=exc.code in ("rate_limited", "server_error", "network", "timeout"))


def _start_checks(model: dict) -> bool:
    is_stub = get_config().stub
    if not is_stub and not credentials.has_key():
        raise GoogleCallError("no_key", "No Google key is connected")
    gateway._check_daily_cap()
    if model.get("kind") != "video":
        raise ValueError(f"{model.get('id')} is not a video model")
    return is_stub


def _attachments(first_frame: Blob | None, last_frame: Blob | None, references: Sequence[Blob],
                 input_video: Blob | None = None) -> list[dict] | None:
    out: list[dict] = []
    for role, blob in (("input_video", input_video), ("first_frame", first_frame), ("last_frame", last_frame)):
        if blob is not None:
            out.append({**blob.summary(), "role": role})
    out += [{**b.summary(), "role": "reference"} for b in references]
    return out or None


def _fixture(aspect: str | None) -> tuple[bytes, str]:
    return stub.video_fixture(aspect).read_bytes(), "video/mp4"


def _sum_cost(call_ids: list[int]) -> float:
    return round(gateway._sum_cost(call_ids), 6)


# ── Veo ─────────────────────────────────────────────────────────────────────


async def generate_veo(*, model: dict, prompt: str, seconds: int, resolution: str, aspect: str,
                       first_frame: Blob | None = None, last_frame: Blob | None = None,
                       references: Sequence[Blob] = (), sound: bool = True, negative_prompt: str | None = None,
                       purpose: str = "video_take", prompt_info: PromptInfo | None = None,
                       refs: Sequence[tuple[str, int]] = (), cancel: Callable[[], bool] | None = None,
                       on_submitted: Callable[[int, str], None] | None = None) -> VideoAnswer:
    """Submit a Veo clip (with retries), report the operation, wait for the file."""
    is_stub = _start_checks(model)
    caps = model.get("caps") or {}
    region = model.get("region") or "us-central1"
    resolution = str(resolution).lower()
    if last_frame is not None and first_frame is None:
        last_frame = None  # Veo walks to a closing frame only from an opening one
    if first_frame is not None and caps.get("frame_shadows_references"):
        references = ()
    max_refs = int(caps.get("max_asset_references") or 0)
    references = list(references)[:max_refs]
    request = {
        "model": model["id"], "region": region, "seconds": int(seconds), "resolution": resolution,
        "aspect_ratio": aspect, "generate_audio": bool(sound) if caps.get("supports_audio_switch") else None,
        "negative_prompt": negative_prompt if caps.get("supports_negative_prompt") else None,
        "first_frame": first_frame is not None, "last_frame": last_frame is not None,
        "references": len(references),
    }
    request = {k: v for k, v in request.items() if v is not None}
    attachments = _attachments(first_frame, last_frame, references)

    max_attempts = int(settings.get("google.max_attempts"))
    errors_used = 0
    attempt = 0
    call_ids: list[int] = []
    while True:
        attempt += 1
        if _cancelled(cancel):
            raise _fail(GoogleCallError("cancelled", "Cancelled before the request"), call_ids)
        call_id = journal.start_call(
            kind="video", purpose=purpose, model=model, region=region,
            prompt_code=prompt_info.code if prompt_info else None,
            prompt_version=prompt_info.version if prompt_info else None, prompt_text=prompt, request=request,
            attachments=attachments, attempt=attempt, refs=refs, stub=is_stub, video_seconds=float(seconds),
            video_resolution=resolution,
        )
        call_ids.append(call_id)
        try:
            async with limiter.slot():
                if is_stub:
                    await asyncio.sleep(stub.delay())
                    marker = stub._marker(prompt)
                    if marker and marker not in ("blocked", "refused"):
                        raise stub.StubFailure(marker)
                    operation_name = f"stub-op-{uuid.uuid4().hex}"
                else:
                    operation_name = await _veo_submit(model, region, prompt, int(seconds), resolution, aspect,
                                                       first_frame, last_frame, references, sound,
                                                       negative_prompt)
        except asyncio.CancelledError:
            journal.finish_call(call_id, status="cancelled", error_code="cancelled", cost_usd=0,
                                error_text="Cancelled while sending the request; Veo may still have started it.")
            raise
        except Exception as exc:  # noqa: BLE001 - every failure is journaled, then sorted
            err = _stub_error(exc) if isinstance(exc, stub.StubFailure) else classify(exc)
            journal.finish_call(call_id, status="error", error_code=err.code, error_text=err.raw,
                                http_status=err.http_status, cost_usd=0)
            log.warning("Veo submit failed (attempt %d, %s): %s", attempt, err.code, err.raw[:300])
            errors_used += 1
            if not err.retryable or errors_used >= max_attempts:
                raise _fail(err, call_ids) from exc
            await gateway._sleep(_pause(err, errors_used), cancel)
            continue
        journal.update_call(call_id, operation_name=operation_name)
        if on_submitted:
            on_submitted(call_id, operation_name)
        try:
            answer = await wait_veo(call_id, cancel=cancel)
        except GoogleCallError as err:
            raise _fail(err, call_ids) from None
        answer.call_ids = list(call_ids)
        answer.cost_usd = _sum_cost(call_ids)
        return answer


async def _veo_submit(model: dict, region: str, prompt: str, seconds: int, resolution: str, aspect: str,
                      first_frame: Blob | None, last_frame: Blob | None, references: Sequence[Blob],
                      sound: bool, negative_prompt: str | None) -> str:
    from google.genai import types

    from vf.core.google.client import get_client

    caps = model.get("caps") or {}
    cfg: dict[str, Any] = {"number_of_videos": 1, "duration_seconds": seconds, "aspect_ratio": aspect,
                           "resolution": resolution, "person_generation": "allow_adult"}
    if caps.get("supports_audio_switch"):
        cfg["generate_audio"] = bool(sound)
    if negative_prompt and caps.get("supports_negative_prompt"):
        cfg["negative_prompt"] = negative_prompt
    if first_frame is not None and last_frame is not None:
        cfg["last_frame"] = types.Image(image_bytes=last_frame.data, mime_type=last_frame.mime)
    if references:
        cfg["reference_images"] = [
            types.VideoGenerationReferenceImage(
                image=types.Image(image_bytes=b.data, mime_type=b.mime),
                reference_type=types.VideoGenerationReferenceType.ASSET)
            for b in references
        ]
    image = types.Image(image_bytes=first_frame.data, mime_type=first_frame.mime) if first_frame else None
    client = get_client(region)
    timeout = int(settings.get("google.timeout_seconds")) + 15
    operation = await asyncio.wait_for(
        client.aio.models.generate_videos(model=model["id"], prompt=prompt, image=image,
                                          config=types.GenerateVideosConfig(**cfg)),
        timeout=timeout,
    )
    name = getattr(operation, "name", None)
    if not name:
        raise RuntimeError("Veo did not return an operation name")
    return str(name)


@dataclass
class _VeoState:
    done: bool = False
    error: str = ""
    data: bytes = b""
    mime: str = "video/mp4"
    filtered: str = ""
    empty: str = ""


async def _veo_poll(region: str, operation_name: str, prompt: str, aspect: str | None) -> _VeoState:
    if operation_name.startswith("stub-op-"):
        await asyncio.sleep(stub.delay())
        marker = stub._marker(prompt or "")
        if marker == "blocked":
            return _VeoState(done=True, filtered="[stub] Veo filtered the clip")
        if marker == "refused":
            return _VeoState(done=True, empty="[stub] Veo returned no clip")
        data, mime = _fixture(aspect)
        return _VeoState(done=True, data=data, mime=mime)

    from google.genai import types

    from vf.core.google.client import get_client

    client = get_client(region)
    timeout = int(settings.get("google.timeout_seconds")) + 15
    op = await asyncio.wait_for(
        client.aio.operations.get(types.GenerateVideosOperation(name=operation_name)), timeout=timeout)
    if not getattr(op, "done", False):
        return _VeoState()
    error = getattr(op, "error", None)
    if error:
        message = error.get("message") if isinstance(error, dict) else getattr(error, "message", None)
        return _VeoState(done=True, error=str(message or error))
    response = getattr(op, "response", None) or getattr(op, "result", None)
    filtered = int(getattr(response, "rai_media_filtered_count", 0) or 0)
    if filtered:
        reasons = getattr(response, "rai_media_filtered_reasons", None) or []
        return _VeoState(done=True, filtered="Veo refused the request: " + ("; ".join(map(str, reasons))
                                                                             or "filtered"))
    for item in getattr(response, "generated_videos", None) or []:
        video = getattr(item, "video", None)
        data = getattr(video, "video_bytes", None)
        if data:
            return _VeoState(done=True, data=data, mime=getattr(video, "mime_type", None) or "video/mp4")
        if getattr(video, "uri", None):
            return _VeoState(done=True, error=f"Veo returned a link instead of the file: {video.uri}")
    return _VeoState(done=True, empty="Veo finished without a clip")


async def wait_veo(call_id: int, *, cancel: Callable[[], bool] | None = None) -> VideoAnswer:
    """Poll the operation of an open journal row until the clip is there.

    Used right after submit and again after a restart (the row stays ``running``
    with its ``operation_name``). Closes the row; raises ``GoogleCallError``.
    """
    row = journal.get_call(call_id)
    if row is None or not row.get("operation_name"):
        raise GoogleCallError("unknown", f"No Veo operation for call {call_id}")
    if row["status"] != "running":
        raise GoogleCallError("unknown", f"Call {call_id} is already closed ({row['status']})")
    journal.resume_call(call_id)
    operation_name = row["operation_name"]
    region = row.get("region") or "us-central1"
    request = row.get("request_json") or {}
    aspect = request.get("aspect_ratio")
    prompt = row.get("prompt_text") or ""
    is_stub = bool(row.get("stub"))
    wait_seconds = float(settings.get("google.video_wait_minutes")) * 60
    started = time.monotonic()
    poll_errors = 0
    max_poll_errors = max(3, int(settings.get("google.max_attempts")))
    try:
        while True:
            if _cancelled(cancel):
                raise GoogleCallError("cancelled", CANCEL_AFTER_SUBMIT)
            try:
                state = await _veo_poll(region, operation_name, prompt, aspect)
                poll_errors = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                err = classify(exc)
                poll_errors += 1
                poll_id = journal.start_call(kind="video_poll", purpose=row.get("purpose") or "video",
                                             model_id=row.get("model_id"), region=region,
                                             request={"operation_name": operation_name, "call_id": call_id},
                                             attempt=poll_errors, refs=journal.refs_of(call_id), stub=is_stub)
                journal.finish_call(poll_id, status="error", error_code=err.code, error_text=err.raw,
                                    http_status=err.http_status, cost_usd=0)
                if not err.retryable or poll_errors >= max_poll_errors:
                    journal.finish_call(call_id, status="error", error_code=err.code, cost_usd=0,
                                        error_text=f"Lost the Veo operation: {err.raw}", http_status=err.http_status)
                    raise err from exc
                state = None
            if state is not None and state.done:
                break
            if time.monotonic() - started > wait_seconds:
                text = (f"Veo did not finish in {int(wait_seconds // 60)} minutes; "
                        "Google may still finish and bill the clip.")
                journal.finish_call(call_id, status="error", error_code="timeout", error_text=text)
                raise GoogleCallError("timeout", text)
            await gateway._sleep(stub.delay() if is_stub else POLL_SECONDS, cancel)
    except asyncio.CancelledError:
        if _cancelled(cancel):
            journal.finish_call(call_id, status="cancelled", error_code="cancelled", error_text=CANCEL_AFTER_SUBMIT)
        # Otherwise the app is stopping: the row stays running and is resumed on the next start.
        raise
    except GoogleCallError as err:
        if err.code == "cancelled":
            journal.finish_call(call_id, status="cancelled", error_code="cancelled", error_text=CANCEL_AFTER_SUBMIT)
        raise _fail(err, [call_id]) from None

    response = {"operation_name": operation_name}
    if state.filtered:
        journal.finish_call(call_id, status="blocked", error_code="safety_blocked", error_text=state.filtered,
                            response=response)
        raise _fail(GoogleCallError("safety_blocked", state.filtered, blocked=True), [call_id])
    if state.error or state.empty:
        code = "refused" if state.empty else "server_error"
        text = state.empty or state.error
        journal.finish_call(call_id, status="error", error_code=code, error_text=text, response=response,
                            cost_usd=0)
        raise _fail(GoogleCallError(code, text), [call_id])
    response.update({"mime": state.mime, "size": len(state.data)})
    finished = journal.finish_call(call_id, status="success", response=response)
    return VideoAnswer(data=state.data, mime=state.mime, model_id=row.get("model_id") or "", call_ids=[call_id],
                       cost_usd=float(finished.get("cost_usd") or 0), operation_name=operation_name,
                       stub=is_stub)


# ── Omni ────────────────────────────────────────────────────────────────────


def omni_parts(prompt: str, *, first_frame: Blob | None = None, references: Sequence[Blob] = (),
               input_video: Blob | None = None) -> list[dict]:
    """The turn as Interactions wants it: media parts, then the text with the roles declared
    (``<VIDEO_REF_0>@Video1``, ``<FIRST_FRAME>@Image1``, ``<IMAGE_REF_0>@Image2``)."""
    parts: list[dict] = []
    counts = {"image": 0, "video": 0}
    sources: list[str] = []
    tags: list[str] = []

    def attach(blob: Blob | None, kind: str) -> int:
        if blob is None or not blob.data:
            return 0
        parts.append({"type": kind, "data": base64.b64encode(blob.data).decode("ascii"),
                      "mime_type": blob.mime or ("video/mp4" if kind == "video" else "image/png")})
        counts[kind] += 1
        return counts[kind]

    clip = attach(input_video, "video")
    if clip:
        tags.append(f"<VIDEO_REF_{clip - 1}>@Video{clip}")
    opening = attach(first_frame, "image")
    if opening:
        sources.append(f"<FIRST_FRAME>@Image{opening}")
    pictures = 0
    for blob in references:
        index = attach(blob, "image")
        if index:
            tags.append(f"<IMAGE_REF_{pictures}>@Image{index}")
            pictures += 1
    declaration = ""
    if sources:
        declaration += "[# Sources " + " ".join(sources) + "] "
    if tags:
        declaration += "[# References " + " ".join(tags) + "] "
    parts.append({"type": "text", "text": declaration + (prompt or "")})
    return parts


def omni_payload(model: dict, parts: list[dict], *, seconds: int, resolution: str, aspect: str | None,
                 extend: bool, with_config: bool = True) -> dict:
    fmt: dict[str, Any] = {"type": "video", "duration": f"{int(seconds)}s", "delivery": "inline",
                           "resolution": str(resolution).lower()}
    if aspect and not extend:
        fmt["aspect_ratio"] = aspect  # an extension keeps the shape of the clip it continues
    payload: dict[str, Any] = {"model": model["id"], "input": parts, "response_format": fmt}
    if extend and with_config:
        payload["generation_config"] = {"video_config": {"task": "extend"}}
    return payload


def omni_extract(body: dict) -> tuple[bytes, str] | None:
    """The clip of an interaction (``output_video`` or a video item in ``steps[].content``)."""
    candidates: list[dict] = []
    if isinstance(body.get("output_video"), dict):
        candidates.append(body["output_video"])
    for step in body.get("steps") or []:
        if isinstance(step, dict):
            candidates += [c for c in step.get("content") or [] if isinstance(c, dict)]
    for item in candidates:
        mime = item.get("mime_type") or ""
        if item.get("type") != "video" and not mime.startswith("video/"):
            continue
        if item.get("data"):
            return base64.b64decode(item["data"]), mime or "video/mp4"
    return None


def omni_said(body: dict) -> str:
    said = [body.get("output_text") or ""]
    for step in body.get("steps") or []:
        if isinstance(step, dict):
            said += [c.get("text") or "" for c in step.get("content") or []
                     if isinstance(c, dict) and c.get("type") == "text"]
    return " ".join(s.strip() for s in said if s and s.strip())[:300]


def omni_usage(body: dict) -> tuple[int, int]:
    usage = body.get("usage") or {}
    try:
        return int(usage.get("total_input_tokens") or 0), int(usage.get("total_output_tokens") or 0)
    except (TypeError, ValueError):
        return 0, 0


def rejects_video_config(message: str) -> bool:
    """Did Vertex refuse the ``generation_config.video_config`` key rather than the shot?"""
    text = (message or "").lower()
    if not any(n in text for n in ("video_config", "videoconfig", "generation_config", "generationconfig")):
        return False
    return any(m in text for m in ("unknown name", "cannot find field", "invalid json payload", "unsupported",
                                   "not supported", "unexpected"))


def is_content_block(message: str) -> bool:
    text = (message or "").lower()
    return any(marker in text for marker in SAFETY_MARKERS)


class OmniHttpError(Exception):
    """A non-2xx answer of Interactions; ``status_code`` lets ``classify`` sort it."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


async def _omni_post(payload: dict) -> dict:
    import httpx

    from vf.core.google import token

    bearer = await asyncio.get_running_loop().run_in_executor(None, token.bearer_token)
    url = INTERACTIONS_URL.format(project=credentials.project_id())
    async with httpx.AsyncClient(timeout=OMNI_TIMEOUT) as client:
        response = await client.post(url, json=payload, headers={"Authorization": f"Bearer {bearer}",
                                                                 "Content-Type": "application/json"})
    if response.status_code >= 400:
        detail = response.text or ""
        try:
            error = response.json().get("error")
            if isinstance(error, dict):
                detail = error.get("message") or detail
            elif isinstance(error, str):
                detail = error
        except (ValueError, AttributeError):
            pass
        raise OmniHttpError(response.status_code, f"Interactions {response.status_code}: {str(detail)[:2000]}")
    return response.json()


def _omni_stub(prompt: str, aspect: str | None, model: dict, seconds: float, input_seconds: float,
               images: int) -> dict:
    marker = stub._marker(prompt)
    if marker == "blocked":
        raise OmniHttpError(400, "Interactions 400: [stub] The prompt was blocked by Responsible AI practices.")
    if marker == "refused":
        return {"status": "completed", "output_text": "[stub] I can't make that video."}
    if marker:
        raise stub.StubFailure(marker)
    tps = float((model.get("price") or {}).get("output_tokens_per_second") or 0)
    data, mime = _fixture(aspect)
    return {"status": "completed",
            "output_video": {"type": "video", "mime_type": mime, "data": base64.b64encode(data).decode("ascii")},
            "usage": {"total_input_tokens": int(tps * input_seconds) + len(prompt) // 4 + images * 560,
                      "total_output_tokens": int(tps * seconds)}}


async def generate_omni(*, model: dict, prompt: str, seconds: int, resolution: str, aspect: str | None,
                        first_frame: Blob | None = None, references: Sequence[Blob] = (),
                        input_video: Blob | None = None, input_video_seconds: float = 0.0, extend: bool = False,
                        bill_seconds: float | None = None, purpose: str = "video_take",
                        prompt_info: PromptInfo | None = None, refs: Sequence[tuple[str, int]] = (),
                        cancel: Callable[[], bool] | None = None) -> VideoAnswer:
    """One Omni clip through Interactions (with retries). ``bill_seconds`` is the length of
    the answer used for the cost when Google reports no tokens (an extension returns the
    attached video plus the new seconds)."""
    is_stub = _start_checks(model)
    region = "global"
    caps = model.get("caps") or {}
    references = list(references)[:int(caps.get("max_asset_references") or 0)]
    bill = float(bill_seconds if bill_seconds is not None else seconds)
    parts = [] if is_stub else omni_parts(prompt, first_frame=first_frame, references=references,
                                          input_video=input_video)
    with_config = True
    request = {"model": model["id"], "region": region, "seconds": int(seconds), "resolution": resolution,
               "aspect_ratio": None if extend else aspect, "extend": extend, "first_frame": first_frame is not None,
               "references": len(references), "input_video_seconds": input_video_seconds or None}
    request = {k: v for k, v in request.items() if v not in (None, False, 0)}
    attachments = _attachments(first_frame, None, references, input_video)
    images = len(references) + (1 if first_frame is not None else 0)

    max_attempts = int(settings.get("google.max_attempts"))
    errors_used = 0
    attempt = 0
    call_ids: list[int] = []
    while True:
        attempt += 1
        if _cancelled(cancel):
            raise _fail(GoogleCallError("cancelled", "Cancelled before the request"), call_ids)
        call_id = journal.start_call(
            kind="video", purpose=purpose, model=model, region=region,
            prompt_code=prompt_info.code if prompt_info else None,
            prompt_version=prompt_info.version if prompt_info else None, prompt_text=prompt,
            request={**request, "generation_config": extend and with_config}, attachments=attachments,
            attempt=attempt, refs=refs, stub=is_stub, video_seconds=bill, video_resolution=str(resolution).lower(),
            input_video_seconds=input_video_seconds or None,
        )
        call_ids.append(call_id)
        try:
            async with limiter.slot():
                if is_stub:
                    await asyncio.sleep(stub.delay())
                    body = _omni_stub(prompt, aspect, model, bill, input_video_seconds, images)
                else:
                    payload = omni_payload(model, parts, seconds=seconds, resolution=resolution, aspect=aspect,
                                           extend=extend, with_config=with_config)
                    body = await asyncio.wait_for(_omni_post(payload), timeout=OMNI_TIMEOUT + 15)
        except asyncio.CancelledError:
            journal.finish_call(call_id, status="cancelled", error_code="cancelled", cost_usd=0,
                                error_text="Cancelled while waiting for Google; Google may still bill it.")
            raise
        except Exception as exc:  # noqa: BLE001
            raw = str(exc)
            status = getattr(exc, "status_code", None)
            if status == 400 and extend and with_config and rejects_video_config(raw):
                journal.finish_call(call_id, status="error", error_code="bad_request", error_text=raw,
                                    http_status=status, cost_usd=0)
                with_config = False  # the key is a hint; the prompt already asks to continue
                continue
            if status == 400 and is_content_block(raw):
                journal.finish_call(call_id, status="blocked", error_code="safety_blocked", error_text=raw,
                                    http_status=status)
                raise _fail(GoogleCallError("safety_blocked", raw, http_status=status, blocked=True),
                            call_ids) from exc
            err = _stub_error(exc) if isinstance(exc, stub.StubFailure) else classify(exc)
            journal.finish_call(call_id, status="error", error_code=err.code, error_text=err.raw,
                                http_status=err.http_status, cost_usd=0)
            log.warning("Omni call failed (attempt %d, %s): %s", attempt, err.code, err.raw[:300])
            errors_used += 1
            if not err.retryable or errors_used >= max_attempts:
                raise _fail(err, call_ids) from exc
            await gateway._sleep(_pause(err, errors_used), cancel)
            continue

        tokens_in, tokens_out = omni_usage(body)
        clip = omni_extract(body)
        summary = {"status": body.get("status"), "id": body.get("id"),
                   "video": {"mime": clip[1], "size": len(clip[0])} if clip else None}
        if clip is None:
            said = omni_said(body)
            text = "The video model answered without a clip." + (f" Model said: {said}" if said else "")
            journal.finish_call(call_id, status="error", error_code="refused", error_text=text,
                                tokens_in=tokens_in or None, tokens_out=tokens_out or None,
                                response={**summary, "text": said}, cost_usd=None if tokens_out else 0)
            raise _fail(GoogleCallError("refused", text), call_ids)
        finished = journal.finish_call(call_id, status="success", tokens_in=tokens_in or None,
                                       tokens_out=tokens_out or None, output_video_seconds=bill,
                                       response=summary)
        log.info("Omni clip ready (%s, %.4f USD)", model["id"], finished.get("cost_usd") or 0)
        return VideoAnswer(data=clip[0], mime=clip[1], model_id=model["id"], call_ids=list(call_ids),
                           cost_usd=_sum_cost(call_ids), tokens_in=tokens_in, tokens_out=tokens_out, stub=is_stub)


def running_operations(purpose: str | None = None) -> list[dict]:
    """Veo rows still waiting for their operation (to resume after a restart)."""
    return [r for r in journal.resumable_calls(purpose) if r.get("kind") == "video"]


__all__ = [
    "INTERACTIONS_URL", "OmniHttpError", "VideoAnswer", "generate_omni", "generate_veo",
    "is_content_block", "omni_extract", "omni_parts", "omni_payload", "omni_usage", "rejects_video_config",
    "running_operations", "wait_veo",
]
