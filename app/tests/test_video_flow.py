"""Module 11 (video), the jobs: a take, extension pieces (one, a paused list, a list in
a row, a failed piece), undo and versions, continue from the last frame, taking a
frame, a 4K source, and putting clips in order after a restart. The render service
is faked: it records what it was asked and writes small files."""

import asyncio
import io

import pytest
from PIL import Image

from vf.core import db, files, jobs, settings
from vf.core.google import journal
from vf.core.google.limiter import limiter
from vf.core.services import render
from vf.modules import video
from vf.modules.video import catalog, extend, generate, runs


@pytest.fixture(autouse=True)
def fast(database, no_sleep):
    settings.set("google.max_rpm", 600)
    limiter._starts.clear()
    return no_sleep


@pytest.fixture
async def runner(database):
    await jobs.runner.start()
    yield jobs.runner
    await jobs.runner.stop()


class FakeRender:
    """Lengths by file: a file probed once keeps its length; new files get ``default``."""

    def __init__(self) -> None:
        self.lengths: dict[str, float] = {}
        self.default = 8.0
        self.size = (1280, 720)
        self.calls: list[tuple] = []

    def length(self, rel: str) -> float:
        return self.lengths.setdefault(rel, self.default)

    async def probe(self, rel: str) -> dict:
        self.calls.append(("probe", rel))
        return {"duration": self.length(rel), "width": self.size[0], "height": self.size[1]}

    @staticmethod
    def _write(rel: str) -> None:
        path = files.abs_path(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 256)

    async def run(self, op: str, body: dict, *, ctx=None, progress_from=0.0, progress_to=1.0, note=None) -> dict:
        self.calls.append((op, body))
        if op == "trim":
            length = body["end"] - body["start"]
        elif op == "compose":
            length = body["trim"]["end"] - body["trim"]["start"]
        elif op == "concat":
            length = sum(self.length(r) for r in body["inputs"])
        else:
            raise AssertionError(f"unexpected render op {op}")
        self._write(body["output"])
        self.lengths[body["output"]] = round(length, 3)
        return {"output": body["output"]}

    async def frame(self, rel: str, output: str, at="first", max_width=None) -> dict:
        self.calls.append(("frame", rel, output, at))
        path = files.abs_path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (64, 36), (10, 20, 30)).save(path, "JPEG")
        return {"output": output}

    def ops(self, op: str) -> list:
        return [c for c in self.calls if c[0] == op]


@pytest.fixture
def fake(monkeypatch):
    f = FakeRender()
    monkeypatch.setattr(render, "probe", f.probe)
    monkeypatch.setattr(render, "run", f.run)
    monkeypatch.setattr(render, "frame", f.frame)
    monkeypatch.setattr(generate, "_ingest", lambda file_id: None)
    return f


def png(color=(20, 120, 200), size=(64, 80)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def stored_png(color=(20, 120, 200)) -> dict:
    return files.save_bytes(png(color), mime="image/png", name="pic.png", origin="upload")


def video_model(api: str) -> dict:
    for m in catalog.video_models():
        if m["api"] == api:
            return m
    pytest.skip(f"no {api} model")


def calls(purpose: str) -> list[dict]:
    return db.fetch_all("SELECT * FROM ai_calls WHERE purpose = ? ORDER BY id", (purpose,))


def refs_of(call_id: int) -> set[tuple[str, int]]:
    return {(r["ref_type"], r["ref_id"])
            for r in db.fetch_all("SELECT ref_type, ref_id FROM ai_call_refs WHERE call_id = ?", (call_id,))}


async def idle(run_id: int, timeout: float = 15.0) -> dict:
    for _ in range(int(timeout / 0.02)):
        busy = any(c["status"] in ("queued", "running") for c in runs.clips(run_id))
        if runs.active_job(run_id) is None and not busy:
            return video.public_run(run_id)
        await asyncio.sleep(0.02)
    raise AssertionError(f"video {run_id} still busy: {[c['status'] for c in runs.clips(run_id)]}")


async def made(brief: str = "A red boat leaves the harbour", **values) -> dict:
    run = video.create_run({"brief": brief, **values})
    video.start_take(run["id"])
    out = await idle(run["id"])
    assert out["status"] == "done", out["error"]
    return out


# ── the take ────────────────────────────────────────────────────────────────


async def test_veo_take_end_to_end(runner, fake):
    veo = video_model("veo")
    pic = stored_png()
    out = await made("A red boat.\nIt leaves.", model_id=veo["id"], first_frame_id=pic["id"], camera_move="static",
                     duration=6)
    (clip,) = out["clips"]
    assert clip["status"] == "done" and clip["cost_usd"] > 0 and clip["seconds_received"] == 8.0
    assert [v["number"] for v in out["versions"]] == [1] and out["current_version"] == 1
    assert out["result"]["id"] == clip["file"]["id"] and out["stage"] == "done"

    (row,) = calls("video_take")
    assert row["prompt_text"].startswith("A red boat.\nIt leaves.\n\nThe camera is locked off")  # brief word for word
    assert row["model_id"] == veo["id"] and row["video_seconds"] == 6
    assert [a["role"] for a in row["attachments_json"]] == ["first_frame"]
    assert refs_of(row["id"]) == {("video_run", out["id"]), ("video_clip", clip["id"])}
    assert journal.cost_of("video_run", out["id"]) == pytest.approx(clip["cost_usd"])
    assert out["spent_usd"] == pytest.approx(clip["cost_usd"])

    saved = files.get(out["result"]["id"])
    assert saved["is_service"] == 0 and saved["duration"] == 8.0 and saved["width"] == 1280
    assert any(u["type"] == "video" for u in files.usages(saved["id"]))


async def test_restart_take_archives_the_old_one_but_keeps_frames(runner, fake):
    pic = stored_png()
    out = await made(first_frame_id=pic["id"])
    old_file = out["result"]["id"]
    video.start_take(out["id"])
    out = await idle(out["id"])
    assert [c["number"] for c in out["clips"]] == [2] and [v["number"] for v in out["versions"]] == [2]
    assert out["first_frame"]["id"] == pic["id"]
    assert files.get(old_file)                                     # the old clip stays in the media library
    assert not any(u["type"] == "video" for u in files.usages(old_file))


async def test_blocked_omni_take_is_an_error_without_a_video(runner, fake):
    omni = video_model("omni")
    run = video.create_run({"brief": "[stub:blocked] a fight", "model_id": omni["id"]})
    video.start_take(run["id"])
    out = await idle(run["id"])
    (clip,) = out["clips"]
    assert out["status"] == "error" and out["error_code"] == "safety_blocked"
    assert clip["status"] == "error" and clip["error_code"] == "safety_blocked" and out["versions"] == []
    assert calls("video_take")[0]["status"] == "blocked"


# ── extension ───────────────────────────────────────────────────────────────


async def test_extend_keeps_the_head_and_joins_on_the_tail_frame(runner, fake):
    settings.set("video.extend_tail_seconds", 4)
    out = await made(model_id=video_model("veo")["id"])
    source = files.get(out["result"]["id"])
    info = extend.info(out["id"])
    assert info["available"] and info["tail_seconds"] == 4.0 and info["other_model"] is True
    est = extend.estimate(out["id"], [{"text": "It sails away", "seconds": 6}])
    assert est["pieces"][0]["tail_seconds"] == 4.0 and est["pieces"][0]["length_after"] == 14.0
    assert est["total_usd"] > 0

    fake.default = 10.0                                            # Omni answers with the tail and 6 new seconds
    video.extend.start_extend(out["id"], [{"text": "It sails away", "seconds": 6}])
    out = await idle(out["id"])
    assert out["status"] == "done", out["error"]
    clip = out["clips"][-1]
    assert clip["kind"] == "extend" and clip["status"] == "done" and clip["tail_seconds"] == 4.0
    assert clip["seconds_received"] == 6.0 and clip["source_version"] == 1

    trims = [body for _op, body in fake.ops("trim")]
    assert [(t["start"], t["end"]) for t in trims] == [(4.0, 8.0), (0, 4.0)]   # the tail, then the head
    (_f, src, _anchor, at), = fake.ops("frame")
    assert src == source["path"] and at == 4.0
    (_c, body), = fake.ops("concat")
    assert body["inputs"][0] == trims[1]["output"] and body["transition"] == "align"
    assert body["align_seconds"] == pytest.approx(0.2) and len(body["anchors"]) == 1

    (row,) = calls("video_extend")
    assert row["input_video_seconds"] == 4.0 and row["video_seconds"] == 10.0 and row["region"] == "global"
    assert "It sails away" in row["prompt_text"] and row["prompt_code"] == "video.extend"
    assert refs_of(row["id"]) == {("video_run", out["id"]), ("video_clip", clip["id"])}
    answer = files.get(clip["file"]["id"])
    assert answer["is_service"] == 1                                    # the raw answer is a service file
    assert [v["number"] for v in out["versions"]] == [1, 2] and out["current_version"] == 2
    assert out["versions"][1]["duration"] == 14.0 and out["extend"]["can_undo"] is True
    assert not [p for p in files.data_dir().joinpath("cache", "tmp").glob("*") if p.is_file()]  # scratch cleaned

    # Undo is free and goes back to the first version; choosing a version is free too.
    spent = journal.cost_of("video_run", out["id"])
    out = video.public_run(video.undo_last(out["id"])["id"])
    assert out["current_version"] == 1 and [v["number"] for v in out["versions"]] == [1]
    assert out["result"]["id"] == source["id"] and journal.cost_of("video_run", out["id"]) == spent


async def test_whole_video_as_tail_and_new_seconds_only(runner, fake):
    out = await made()
    fake.default = 14.0                       # the whole 8 s video went in; the answer is the new video
    video.extend.start_extend(out["id"], [{"text": "", "seconds": 6}])
    out = await idle(out["id"])
    (_c, body), = fake.ops("concat")
    assert len(body["inputs"]) == 1 and body["transition"] == "cut"
    clip = out["clips"][-1]
    assert clip["next_text"] == out["brief"]                         # empty "what next" = the brief
    assert out["versions"][-1]["duration"] == 14.0

    settings.set("video.extend_align", False)
    settings.set("video.extend_crossfade_seconds", 0)
    fake.default = 6.0                        # only the new seconds came back: they go after the video
    video.extend.start_extend(out["id"], [{"text": "Rain", "seconds": 6}])
    out = await idle(out["id"])
    (_c, _first), (_c2, body) = fake.ops("concat")
    assert len(body["inputs"]) == 2 and body["transition"] == "cut" and out["versions"][-1]["duration"] == 20.0
    assert fake.ops("frame")[-1][3] == "last"


async def test_four_k_source_makes_the_whole_video_1080p(runner, fake):
    fake.size = (3840, 2160)
    out = await made()
    info = extend.info(out["id"])
    assert info["source_resolution"] == "4k" and info["resolution"] == "1080p" and info["downscale"] is True
    fake.default = 6.0
    video.extend.start_extend(out["id"], [{"text": "Fog", "seconds": 6}])
    out = await idle(out["id"])
    (_c, cut), = fake.ops("compose")
    assert cut["crop"] == {"width": 1920, "height": 1080, "mode": "cover"}
    (_c, body), = fake.ops("concat")
    assert body["width"] == 1920 and body["height"] == 1080
    assert calls("video_extend")[0]["video_resolution"] == "1080p"


async def test_paused_plan_waits_for_next_piece(runner, fake):
    out = await made()
    fake.default = 6.0
    steps = [{"text": "One", "seconds": 4}, {"text": "Two", "seconds": 4}]
    video.extend.start_extend(out["id"], steps, pause_each=True)
    out = await idle(out["id"])
    assert out["status"] == "paused" and out["extend"]["plan"]["status"] == "paused"
    assert [s["status"] for s in out["extend"]["plan"]["steps"]] == ["done", "pending"]
    assert len(calls("video_extend")) == 1

    video.extend.continue_plan(out["id"])
    out = await idle(out["id"])
    assert out["status"] == "done" and out["extend"]["plan"]["status"] == "done"
    assert [v["number"] for v in out["versions"]] == [1, 2, 3]
    assert [c["next_text"] for c in out["clips"][1:]] == ["One", "Two"]


async def test_plan_in_a_row_and_a_failed_piece_stops_the_money(runner, fake):
    out = await made()
    fake.default = 6.0
    video.extend.start_extend(out["id"], [{"text": "One", "seconds": 4}, {"text": "Two", "seconds": 4}],
                              pause_each=False)
    out = await idle(out["id"])
    assert out["status"] == "done" and len(out["versions"]) == 3

    steps = [{"text": "[stub:refused] Three", "seconds": 4}, {"text": "Four", "seconds": 4}]
    video.extend.start_extend(out["id"], steps, pause_each=False)
    out = await idle(out["id"])
    plan = out["extend"]["plan"]
    assert out["status"] == "error" and plan["status"] == "error"
    assert [s["status"] for s in plan["steps"]] == ["error", "pending"]
    assert len(calls("video_extend")) == 3                           # nothing was sent for "Four"
    assert out["current_version"] == 3                               # the video stays as it was

    video.extend.continue_plan(out["id"], [{"text": "Three again", "seconds": 4}])
    out = await idle(out["id"])
    assert out["status"] == "paused" or out["status"] == "done"
    assert out["extend"]["plan"]["steps"][-1]["text"] == "Three again"


async def test_continue_from_the_last_frame(runner, fake):
    veo = video_model("veo")
    out = await made("A kite", model_id=veo["id"])
    est = extend.continue_estimate(out["id"], 6)
    assert est["seconds"] == 6 and est["estimate_usd"] > 0 and est["length_after"] == 14.0
    fake.default = 6.0
    extend.start_continue(out["id"], "The kite lands on the sand", 6)
    out = await idle(out["id"])
    assert out["status"] == "done", out["error"]
    clip = out["clips"][-1]
    (row,) = calls("video_continue")
    assert row["prompt_text"] == "The kite lands on the sand"          # word for word, no wrapper
    assert [a["role"] for a in row["attachments_json"]] == ["first_frame"]
    still_id = db.get("video_clips", clip["id"])["meta_json"]["first_frame_id"]
    still = files.get(still_id)
    assert still["kind"] == "image" and still["is_service"] == 1
    (_c, body), = fake.ops("concat")
    assert body["anchors"] == [still["path"]] and len(body["inputs"]) == 2
    assert out["versions"][-1]["kind"] == "continue" and out["versions"][-1]["duration"] == 14.0


async def test_take_frame_is_free_and_lands_in_the_library(runner, fake):
    out = await made()
    spent = journal.cost_of("video_run", out["id"])
    pic = await video.take_frame(out["id"], at=2.5)
    row = files.get(pic["id"])
    assert row["kind"] == "image" and row["is_service"] == 0 and row["meta_json"]["at"] == 2.5
    assert fake.ops("frame")[-1][3] == 2.5
    last = await video.take_frame(out["id"], at="last", version=1)
    assert last["id"] != pic["id"] and journal.cost_of("video_run", out["id"]) == spent


# ── stop and restart ────────────────────────────────────────────────────────


def _video_file() -> dict:
    return files.save_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 64, mime="video/mp4", name="v.mp4",
                            origin="generated", duration=8.0, width=1280, height=720)


def test_stop_a_queued_plan_and_try_again(database):
    run = video.create_run({"brief": "A road"})
    src = _video_file()
    runs.add_version(run["id"], kind="take", file_id=src["id"], duration=8.0, clip_ids=[])
    runs.update_run_state(run["id"], stage="done", status="done")
    video.extend.start_extend(run["id"], [{"text": "A", "seconds": 4}, {"text": "B", "seconds": 4}])
    out = video.stop_run(run["id"])
    assert out["status"] == "done" and out["extend_plan_json"]["status"] == "stopped"
    assert runs.clips(run["id"])[0]["status"] == "cancelled"
    video.extend.continue_plan(run["id"])
    assert runs.active_job(run["id"]) is not None
    assert runs.clips(run["id"])[-1]["next_text"] == "A"


async def test_open_veo_operation_is_waited_again_after_a_restart(runner, fake, monkeypatch):
    await runner.stop()
    veo = video_model("veo")
    run = video.create_run({"brief": "A boat", "model_id": veo["id"]})
    video.start_take(run["id"])
    (clip,) = runs.clips(run["id"])
    call_id = journal.start_call(kind="video", purpose="video_take", model=veo, region="us-central1",
                                 prompt_text="A boat", request={"aspect_ratio": "16:9"}, stub=True,
                                 video_seconds=8.0, video_resolution="720p",
                                 refs=[("video_run", run["id"]), ("video_clip", clip["id"])])
    journal.update_call(call_id, operation_name="stub-op-before-restart")
    runs.update_clip(clip["id"], status="running", call_id=call_id, operation_name="stub-op-before-restart")
    db.update("jobs", clip["job_id"], {"status": "interrupted"})      # its job did not come back

    video.sweep()
    new_job = runs.get_clip(clip["id"])["job_id"]
    assert new_job != clip["job_id"]
    await runner.start()
    out = await idle(run["id"])
    assert out["status"] == "done" and len(out["versions"]) == 1
    (row,) = calls("video_take")                                      # nothing was paid twice
    assert row["id"] == call_id and row["status"] == "success"


def test_clip_in_flight_without_an_operation_is_interrupted(database):
    omni = video_model("omni")
    run = video.create_run({"brief": "Waves", "model_id": omni["id"]})
    video.start_take(run["id"])
    (clip,) = runs.clips(run["id"])
    runs.update_clip(clip["id"], status="running")
    db.update("jobs", clip["job_id"], {"status": "interrupted"})
    video.sweep()
    clip = runs.get_clip(clip["id"])
    assert clip["status"] == "error" and clip["error_code"] == "video_interrupted"
    out = video.public_run(run["id"])
    assert out["status"] == "error" and out["error_code"] == "video_interrupted"
    assert db.fetch_value("SELECT COUNT(*) FROM ai_calls") == 0       # nothing re-sent by itself


async def test_retried_job_does_not_resend_an_omni_clip(runner, fake):
    await runner.stop()
    omni = video_model("omni")
    run = video.create_run({"brief": "Waves", "model_id": omni["id"]})
    video.start_take(run["id"])
    (clip,) = runs.clips(run["id"])
    runs.update_clip(clip["id"], status="running")                  # it was being made when the app stopped
    await runner.start()
    out = await idle(run["id"])
    assert out["clips"][0]["error_code"] == "video_interrupted" and out["status"] == "error"
    assert calls("video_take") == []
