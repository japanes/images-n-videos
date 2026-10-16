"""Module 11 (video), the Google side: Veo operations and Gemini Omni through the
spend journal (stub mode), resuming a Veo operation after a restart, lost
operations, the Omni ``generation_config`` fallback and the parts of a request."""

import base64
from types import SimpleNamespace

import pytest

from vf.core import db, models_registry, settings
from vf.core.google import GoogleCallError, journal
from vf.core.google import video as gv
from vf.core.google.gateway import Blob
from vf.core.google.limiter import limiter


@pytest.fixture(autouse=True)
def fast(database, no_sleep):
    settings.set("google.max_rpm", 600)
    limiter._starts.clear()
    return no_sleep


def video_model(api: str, *, refs: bool = False) -> dict:
    for m in models_registry.list_models("video", enabled_only=False):
        if m.get("api") == api and (not refs or int((m.get("caps") or {}).get("max_asset_references") or 0) > 0):
            return m
    raise AssertionError(f"no {api} model in the registry")


def rows(purpose: str | None = None, kind: str | None = None) -> list[dict]:
    sql, params = "SELECT * FROM ai_calls WHERE 1 = 1", []
    if purpose:
        sql += " AND purpose = ?"
        params.append(purpose)
    if kind:
        sql += " AND kind = ?"
        params.append(kind)
    return db.fetch_all(sql + " ORDER BY id", params)


def refs_of(call_id: int) -> set[tuple[str, int]]:
    return {(r["ref_type"], r["ref_id"])
            for r in db.fetch_all("SELECT ref_type, ref_id FROM ai_call_refs WHERE call_id = ?", (call_id,))}


PNG = Blob(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, "image/png")


async def test_veo_clip_is_journaled_with_its_operation():
    m = video_model("veo")
    seen = []
    answer = await gv.generate_veo(model=m, prompt="A cat walks", seconds=8, resolution="720p", aspect="16:9",
                                   refs=[("video_run", 7)], on_submitted=lambda cid, op: seen.append((cid, op)))
    assert answer.data and answer.mime == "video/mp4" and answer.stub
    (row,) = rows("video_take")
    assert seen == [(row["id"], row["operation_name"])] and row["operation_name"].startswith("stub-op-")
    assert row["status"] == "success" and row["region"] == "us-central1"
    assert row["cost_usd"] == pytest.approx(answer.cost_usd) and row["cost_usd"] > 0
    assert row["prompt_text"] == "A cat walks"
    assert refs_of(row["id"]) == {("video_run", 7)}


async def test_veo_drops_what_it_cannot_use():
    m = video_model("veo", refs=True)
    await gv.generate_veo(model=m, prompt="x", seconds=4, resolution="720p", aspect="9:16",
                          first_frame=PNG, references=[PNG, PNG])
    await gv.generate_veo(model=m, prompt="y", seconds=4, resolution="720p", aspect="9:16", last_frame=PNG)
    first, second = rows("video_take")
    # With an opening frame Veo ignores references; a closing frame alone is not sent.
    assert first["request_json"]["references"] == 0 and first["request_json"]["first_frame"] is True
    assert [a["role"] for a in first["attachments_json"]] == ["first_frame"]
    assert second["request_json"]["last_frame"] is False and not second["attachments_json"]


async def test_veo_blocked_refused_and_errors_cost_what_google_bills():
    m = video_model("veo")
    with pytest.raises(GoogleCallError) as blocked:
        await gv.generate_veo(model=m, prompt="[stub:blocked] x", seconds=4, resolution="720p", aspect="16:9")
    assert blocked.value.code == "safety_blocked"
    with pytest.raises(GoogleCallError) as refused:
        await gv.generate_veo(model=m, prompt="[stub:refused] x", seconds=4, resolution="720p", aspect="16:9")
    assert refused.value.code == "refused"
    with pytest.raises(GoogleCallError) as failed:
        await gv.generate_veo(model=m, prompt="[stub:error=server_error] x", seconds=4, resolution="720p",
                              aspect="16:9")
    assert failed.value.code == "server_error"
    found = rows("video_take")
    assert found[0]["status"] == "blocked" and found[0]["error_code"] == "safety_blocked"
    assert found[1]["status"] == "error" and found[1]["error_code"] == "refused" and found[1]["cost_usd"] == 0
    retried = found[2:]
    assert len(retried) == int(settings.get("google.max_attempts"))   # every try is a row
    assert all(r["status"] == "error" and r["cost_usd"] == 0 for r in retried)
    assert failed.value.call_ids == [r["id"] for r in retried]


async def test_open_veo_operation_is_waited_again_without_paying_twice():
    m = video_model("veo")
    call_id = journal.start_call(kind="video", purpose="video_take", model=m, region="us-central1",
                                 prompt_text="A boat", request={"aspect_ratio": "16:9"}, stub=True,
                                 video_seconds=6.0, video_resolution="720p", refs=[("video_clip", 3)])
    journal.update_call(call_id, operation_name="stub-op-restart")
    assert [r["id"] for r in gv.running_operations()] == [call_id]

    answer = await gv.wait_veo(call_id)
    assert answer.call_ids == [call_id] and answer.operation_name == "stub-op-restart"
    (row,) = rows()
    assert row["status"] == "success" and row["cost_usd"] > 0
    assert gv.running_operations() == []
    with pytest.raises(GoogleCallError):
        await gv.wait_veo(call_id)                                   # closed rows are not waited again


async def test_lost_veo_operation_closes_the_row_at_zero(monkeypatch):
    m = video_model("veo")
    call_id = journal.start_call(kind="video", purpose="video_take", model=m, prompt_text="A boat",
                                 request={"aspect_ratio": "16:9"}, stub=True, video_seconds=6.0,
                                 video_resolution="720p", refs=[("video_clip", 3)])
    journal.update_call(call_id, operation_name="projects/p/operations/gone")

    async def gone(*_a, **_k):
        raise GoogleCallError("model_not_found", "404 operation not found", http_status=404)

    monkeypatch.setattr(gv, "_veo_poll", gone)
    with pytest.raises(GoogleCallError) as err:
        await gv.wait_veo(call_id)
    assert err.value.code == "model_not_found"
    main = journal.get_call(call_id)
    assert main["status"] == "error" and main["cost_usd"] == 0 and "Lost the Veo operation" in main["error_text"]
    (poll,) = rows(kind="video_poll")
    assert poll["cost_usd"] == 0 and poll["error_text"] == "404 operation not found"
    assert refs_of(poll["id"]) == {("video_clip", 3)}


async def test_veo_that_never_finishes_times_out(monkeypatch):
    m = video_model("veo")
    settings.set("google.video_wait_minutes", 5)
    clock = iter(range(0, 10_000, 200))                          # every look at the clock is 200 s later
    monkeypatch.setattr(gv, "time", SimpleNamespace(monotonic=lambda: next(clock)))
    call_id = journal.start_call(kind="video", purpose="video_take", model=m, prompt_text="slow",
                                 request={}, stub=True, video_seconds=4.0, video_resolution="720p")
    journal.update_call(call_id, operation_name="stub-op-slow")

    async def pending(*_a, **_k):
        return gv._VeoState(done=False)

    monkeypatch.setattr(gv, "_veo_poll", pending)
    with pytest.raises(GoogleCallError) as err:
        await gv.wait_veo(call_id)
    assert err.value.code == "timeout"
    row = journal.get_call(call_id)
    assert row["status"] == "error" and "may still finish and bill" in row["error_text"]
    assert row["cost_usd"] > 0                                   # Google may still bill it: the price stays


async def test_omni_clip_extension_and_failures():
    m = video_model("omni")
    answer = await gv.generate_omni(model=m, prompt="Waves", seconds=6, resolution="720p", aspect="16:9",
                                    refs=[("video_run", 1)])
    assert answer.data and answer.tokens_out > 0
    ext = await gv.generate_omni(model=m, prompt="Then the sun sets", seconds=4, resolution="720p", aspect=None,
                                 input_video=Blob(b"\x00" * 300, "video/mp4"), input_video_seconds=6.0,
                                 extend=True, bill_seconds=10.0, purpose="video_extend")
    take, extend = rows()
    assert take["region"] == "global" and take["status"] == "success" and take["cost_usd"] > 0
    assert extend["request_json"]["extend"] is True and "aspect_ratio" not in extend["request_json"]
    assert extend["input_video_seconds"] == 6.0 and extend["video_seconds"] == 10.0
    assert [a["role"] for a in extend["attachments_json"]] == ["input_video"]
    assert ext.cost_usd > answer.cost_usd                     # the attached video is billed too

    with pytest.raises(GoogleCallError) as blocked:
        await gv.generate_omni(model=m, prompt="[stub:blocked] x", seconds=4, resolution="720p", aspect="16:9")
    assert blocked.value.code == "safety_blocked"
    with pytest.raises(GoogleCallError) as refused:
        await gv.generate_omni(model=m, prompt="[stub:refused] x", seconds=4, resolution="720p", aspect="16:9")
    assert refused.value.code == "refused" and "I can't make that video" in refused.value.message
    bad, empty = rows()[2:]
    assert bad["status"] == "blocked" and empty["status"] == "error" and empty["cost_usd"] == 0


async def test_omni_extension_retries_without_generation_config(monkeypatch):
    m = video_model("omni")
    sent: list[dict] = []
    clip = base64.b64encode(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 64).decode()

    async def post(payload):
        sent.append(payload)
        if "generation_config" in payload:
            raise gv.OmniHttpError(400, 'Interactions 400: Invalid JSON payload received. Unknown name '
                                        '"generation_config": Cannot find field.')
        return {"status": "completed", "usage": {"total_input_tokens": 1000, "total_output_tokens": 50000},
                "steps": [{"content": [{"type": "video", "mime_type": "video/mp4", "data": clip}]}]}

    monkeypatch.setattr(gv, "_start_checks", lambda model: False)
    monkeypatch.setattr(gv, "_omni_post", post)
    answer = await gv.generate_omni(model=m, prompt="Then it rains", seconds=4, resolution="720p", aspect="16:9",
                                    input_video=Blob(b"\x00" * 100, "video/mp4"), input_video_seconds=5.0,
                                    references=[PNG], extend=True, bill_seconds=9.0, purpose="video_extend")
    assert answer.data.startswith(b"\x00\x00\x00\x18ftyp") and len(answer.call_ids) == 2
    first, second = sent
    assert first["generation_config"] == {"video_config": {"task": "extend"}}
    assert "generation_config" not in second and "aspect_ratio" not in second["response_format"]
    text = second["input"][-1]["text"]
    assert text.startswith("[# References <VIDEO_REF_0>@Video1 <IMAGE_REF_0>@Image1] ")
    assert text.endswith("Then it rains")
    failed, ok = rows("video_extend")
    assert failed["status"] == "error" and failed["error_code"] == "bad_request" and failed["cost_usd"] == 0
    assert "Unknown name" in failed["error_text"]                    # Google's text, word for word
    assert ok["status"] == "success" and ok["tokens_out"] == 50000 and ok["cost_usd"] > 0


def test_omni_parts_declare_roles():
    parts = gv.omni_parts("Go", first_frame=PNG, references=[PNG, PNG])
    assert [p["type"] for p in parts] == ["image", "image", "image", "text"]
    assert parts[-1]["text"] == ("[# Sources <FIRST_FRAME>@Image1] "
                                 "[# References <IMAGE_REF_0>@Image2 <IMAGE_REF_1>@Image3] Go")
    assert gv.rejects_video_config('Unknown name "video_config"') and not gv.rejects_video_config("bad shot")
    assert gv.is_content_block("blocked by Responsible AI") and not gv.is_content_block("quota")
    body = {"output_video": {"type": "video", "mime_type": "video/mp4", "data": base64.b64encode(b"v").decode()}}
    assert gv.omni_extract(body) == (b"v", "video/mp4") and gv.omni_extract({"steps": []}) is None
