"""The «Generate» tab: new backgrounds for the design, 1–4 in one press (factory ``editor_generation``).

One press = one job ``text.background`` (group "image") with a row per picture in
``text_backgrounds``. The prompt is what the person typed, plus the «no letters» block when
that switch is on; the current background goes along as a picture only when «use the current
picture» is on. The model and the size are the frame's own (studio settings), the proportions
are the work's. Every picture is one gateway call in the journal (refs: the design, the frame,
the chat). A ready picture becomes the background only when the person presses «Use»; the
layers stay where they are.
"""

from __future__ import annotations

import asyncio
from typing import Any

from vf.core import db, files, google, jobs, prompts
from vf.core.errors import AppError
from vf.core.google import GoogleCallError
from vf.modules import library
from vf.modules.studio import works as W
from vf.modules.text import common as C
from vf.modules.text import store as S

ACTIVE = ("queued", "running")


def public(row: dict) -> dict:
    file_id = row.get("file_id")
    return {"id": row["id"], "job_id": row.get("job_id"), "n": row["n"], "status": row["status"],
            "prompt": row["prompt"], "use_current": bool(row["use_current"]),
            "file_id": file_id, "url": files.url(file_id) if file_id else None,
            "thumb_url": files.url(file_id, w=480) if file_id else None,
            "model_id": row.get("model_id"), "cost_usd": round(row.get("cost_usd") or 0, 6),
            "error_code": row.get("error_code"), "error": row.get("error"), "created_at": row["created_at"]}


def heal(design_id: int) -> None:
    """Rows still «waiting» whose job is over (stopped before it started, from the jobs screen too)."""
    job_status = "(SELECT status FROM jobs WHERE jobs.id = text_backgrounds.job_id)"
    db.execute(
        f"UPDATE text_backgrounds SET status = CASE WHEN {job_status} = 'cancelled' THEN 'cancelled' ELSE 'error' END,"
        f" error_code = CASE WHEN {job_status} = 'cancelled' THEN NULL ELSE 'interrupted' END, updated_at = ?"
        f" WHERE design_id = ? AND status IN ('queued', 'running') AND job_id IS NOT NULL"
        f" AND COALESCE({job_status}, 'gone') NOT IN ('queued', 'running')",
        (db.now(), design_id))


def list_for(design_id: int) -> list[dict]:
    heal(design_id)
    rows = db.fetch_all("SELECT * FROM text_backgrounds WHERE design_id = ? ORDER BY id DESC LIMIT 40",
                        (design_id,))
    return [public(r) for r in rows]


def settings_for(design: dict) -> dict:
    """The model, size and proportions the frame is drawn with (raises when the model can't be used)."""
    frame = S.frame_of(design)
    work = S.work_of(frame)
    eff = W.effective(work, frame)
    return {"model_id": eff["model_id"], "image_size": eff.get("image_size"), "aspect": work["aspect"]}


def request(design: dict, body: dict) -> dict:
    """What one press sends: ``{prompt, use_current, count}``."""
    typed = C.clean_block(body.get("prompt"), C.MAX_PROMPT)
    parts = [typed] if typed else []
    if C.flag(body, "no_lettering"):
        parts.append(library.render_layer("PROMPT_BLOCK_NO_LETTERING", {}).strip())
    prompt = "\n\n".join(parts)
    if not typed:
        raise AppError("empty_prompt", 400, "Describe the picture you want")
    use_current = C.flag(body, "use_current")
    if use_current and not design.get("background_file_id"):
        raise AppError("no_picture", 409, "There is no current picture to send")
    return {"prompt": prompt, "use_current": use_current,
            "count": C.count(body.get("count", 1), high=C.MAX_BACKGROUNDS)}


def start(design_id: int, body: Any) -> dict:
    """``{prompt, count 1..4, no_lettering, use_current, preview}`` → ``{job_id, backgrounds}``."""
    body = body if isinstance(body, dict) else {}
    design = S.design_row(design_id)
    req = request(design, body)
    conf = settings_for(design)       # every check before money is spent
    if C.flag(body, "preview"):
        return {"system": "", "text": prompts.render(C.PROMPT_BACKGROUND, prompt=req["prompt"]).text,
                "images": 1 if req["use_current"] else 0, "count": req["count"], "model_id": conf["model_id"]}
    busy = db.fetch_value("SELECT COUNT(*) FROM text_backgrounds WHERE design_id = ? AND status IN ('queued',"
                          " 'running')", (design_id,), 0)
    if busy:
        raise AppError("busy", 409, "New backgrounds are being drawn; wait or stop them")
    now = db.now()
    with db.tx():
        ids = [db.insert("text_backgrounds", {
            "design_id": design_id, "n": n, "prompt": req["prompt"], "use_current": int(req["use_current"]),
            "status": "queued", "model_id": conf["model_id"], "created_at": now, "updated_at": now,
        }) for n in range(req["count"])]
        frame = S.frame_of(design)
        job_id = jobs.enqueue(C.JOB_BACKGROUND, {"design_id": design_id, "ids": ids}, ref_type=C.REF_DESIGN,
                              ref_id=design_id, title=f"{req['count']} × background · {frame['position'] + 1}")
        db.execute(f"UPDATE text_backgrounds SET job_id = ? WHERE id IN ({','.join('?' * len(ids))})",
                   (job_id, *ids))
    C.publish(design_id, backgrounds=True)
    return {"job_id": job_id, "backgrounds": list_for(design_id)}


def _set(row_id: int, values: dict) -> None:
    db.update("text_backgrounds", row_id, {**values, "updated_at": db.now()})


async def _draw_one(ctx: jobs.JobContext, design: dict, row: dict, conf: dict, image: google.Blob | None) -> float:
    _set(row["id"], {"status": "running"})
    C.publish(design["id"], backgrounds=True)
    try:
        result = await prompts.run_prompt(
            C.PROMPT_BACKGROUND, {"prompt": row["prompt"]}, purpose=C.PURPOSE_BACKGROUND,
            images=[image] if image is not None else (), model_id=conf["model_id"],
            aspect_ratio=conf["aspect"], image_size=conf["image_size"], refs=S.refs_of(design),
            cancel=lambda: ctx.cancel_requested)
    except GoogleCallError as exc:
        status = "cancelled" if exc.code == "cancelled" and ctx.cancel_requested else "error"
        _set(row["id"], {"status": status, "error_code": exc.code, "error": (exc.raw or exc.message or "")[:4000]})
        raise
    data, mime = result.images[0]
    saved = files.save_bytes(data, mime=mime, name=f"background-{design['id']}-{row['n'] + 1}.png",
                             origin="generated", title=f"Background · {row['n'] + 1}",
                             source_type=C.SOURCE_BACKGROUND, source_id=design["id"],
                             meta={"design_id": design["id"], "frame_id": design["frame_id"],
                                   "model_id": result.model_id, "prompt": row["prompt"]})
    _set(row["id"], {"status": "done", "file_id": saved["id"], "model_id": result.model_id,
                     "cost_usd": round(result.cost_usd or 0, 6), "error_code": None, "error": None})
    S.add_cost(design["id"], result.cost_usd)
    C.publish(design["id"], backgrounds=True)
    return result.cost_usd or 0


@jobs.handler(C.JOB_BACKGROUND, group="image", recover="interrupt")
async def run_backgrounds(ctx: jobs.JobContext) -> dict | None:
    design_id = int(ctx.payload["design_id"])
    ids = [int(i) for i in ctx.payload.get("ids") or []]
    design = db.get("text_designs", design_id)
    if design is None:
        return {"skipped": "design_gone"}
    rows = [r for r in (db.get("text_backgrounds", i) for i in ids) if r and r["status"] in ACTIVE]
    try:
        conf = settings_for(design)
        image = None
        if any(r["use_current"] for r in rows) and design.get("background_file_id"):
            image = await asyncio.to_thread(google.blob_from_file, design["background_file_id"])
        ctx.progress(0.05, force=True)
        results = await asyncio.gather(*[_draw_one(ctx, design, r, conf, image if r["use_current"] else None)
                                         for r in rows], return_exceptions=True)
    except (asyncio.CancelledError, jobs.JobCancelled):
        _close(ids, "cancelled" if ctx.cancel_requested else "error", "interrupted")
        raise
    except AppError as exc:
        _close(ids, "error", exc.code, exc.message)
        raise
    finally:
        C.publish(design_id, backgrounds=True)
    done = [r for r in results if not isinstance(r, BaseException)]
    errors = [r for r in results if isinstance(r, BaseException)]
    if ctx.cancel_requested and not done:
        _close(ids, "cancelled", "cancelled")
        raise jobs.JobCancelled()
    if errors and not done:
        raise errors[0]
    # where the jobs page «Open» leads: the chat message the tool was opened from
    return {"done": len(done), "errors": len(errors), "cost_usd": round(sum(done), 6),
            "design_id": design_id, "chat_id": design.get("chat_id"), "message_id": design.get("message_id")}


def _close(ids: list[int], status: str, code: str, text: str | None = None) -> None:
    """Rows of a press still waiting get a final status (stop, crash, a check that failed)."""
    if not ids:
        return
    marks = ",".join("?" * len(ids))
    db.execute(f"UPDATE text_backgrounds SET status = ?, error_code = ?, error = ?, updated_at = ?"
               f" WHERE id IN ({marks}) AND status IN ('queued', 'running')",
               (status, code if status != "cancelled" else None, text, db.now(), *ids))


def cancel(design_id: int) -> list[dict]:
    """«Stop»: a running job is asked to stop, a queued one ends now (its rows with it)."""
    for job_id in active_jobs(design_id):
        try:
            jobs.cancel(job_id)
        except AppError:
            pass
    C.publish(design_id, backgrounds=True)
    return list_for(design_id)


def active_jobs(design_id: int) -> list[int]:
    """Jobs still drawing backgrounds for the design (the «Stop» button cancels them)."""
    rows = db.fetch_all("SELECT DISTINCT job_id FROM text_backgrounds WHERE design_id = ? AND job_id IS NOT NULL"
                        " AND status IN ('queued', 'running')", (design_id,))
    return [int(r["job_id"]) for r in rows]


def use(design_id: int, background_id: Any) -> dict:
    """The picked picture becomes the design's background; the layers stay."""
    from vf.modules.text import designs as D

    row = db.get("text_backgrounds", S.int_or_none(background_id) or 0)
    if row is None or row["design_id"] != int(design_id):
        raise AppError("not_found", 404, "There is no such background", what="text_background")
    if row["status"] != "done" or not row.get("file_id"):
        raise AppError("not_ready", 409, "The picture is not ready")
    return D.patch(design_id, {"background_file_id": row["file_id"]})


def sweep() -> int:
    """At start: rows of a press whose job did not survive the stop of the app get ``interrupted``.

    Runs before the job runner starts, so only a queued job is still alive."""
    rows = db.fetch_all(
        "SELECT b.id FROM text_backgrounds b LEFT JOIN jobs j ON j.id = b.job_id"
        " WHERE b.status IN ('queued', 'running') AND (j.id IS NULL OR j.status <> 'queued')")
    _close([r["id"] for r in rows], "error", "interrupted")
    return len(rows)


__all__ = ["active_jobs", "cancel", "heal", "list_for", "request", "run_backgrounds", "settings_for", "start", "sweep", "use"]
