"""Module 12: subtitles from speech through the local stt service (faked here)."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from vf.core import db, files, jobs, settings
from vf.core.errors import AppError
from vf.core.services import render, stt
from vf.modules.clip import projects, transcribe

MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 200
WORDS = [{"word": " Hello", "start": 0.4, "end": 0.8}, {"word": " world", "start": 0.9, "end": 1.3}]


@pytest.fixture
def fake_stt(monkeypatch):
    """The stt service without its container: answers at once with two words."""
    state = {"calls": [], "result": {"text": "Hello world", "language": "en", "duration": 60.0, "words": WORDS},
             "error": None, "models": [{"name": "large-v3-turbo", "downloaded": False, "size_mb": 1600},
                                       {"name": "small", "downloaded": True, "size_mb": 480}]}

    async def fake_transcribe(rel, *, model, language="auto", word_timestamps=True):
        state["calls"].append(("transcribe", rel, model, language))
        if state["error"]:
            raise state["error"]
        return dict(state["result"])

    async def fake_progress():
        return {"busy": False, "phase": None}

    async def fake_models():
        return state["models"]

    async def fake_download(name):
        state["calls"].append(("download", name))
        if state["error"]:
            raise state["error"]
        return {"name": name, "status": "downloading"}

    async def fake_remove(name):
        state["calls"].append(("remove", name))

    async def probe(_rel):
        return {"duration": 60.0, "has_video": True, "has_audio": True, "width": 1280, "height": 720}

    monkeypatch.setattr(stt, "transcribe", fake_transcribe)
    monkeypatch.setattr(stt, "progress", fake_progress)
    monkeypatch.setattr(stt, "models", fake_models)
    monkeypatch.setattr(stt, "download", fake_download)
    monkeypatch.setattr(stt, "remove", fake_remove)
    monkeypatch.setattr(render, "probe", probe)
    return state


@pytest.fixture
async def runner(database):
    await jobs.runner.start()
    yield jobs.runner
    await jobs.runner.stop()


@pytest.fixture
def api(cfg, fake_stt):
    from vf.main import create_app

    with TestClient(create_app(cfg, run_background=False)) as test_client:
        yield test_client


async def _wait(job_id, timeout=5.0):
    for _ in range(int(timeout / 0.02)):
        row = jobs.get(job_id)
        if row["status"] in jobs.FINISHED:
            return row
        await asyncio.sleep(0.02)
    raise AssertionError(f"job {job_id} stuck in {jobs.get(job_id)['status']}")


async def _project(state: dict | None = None) -> dict:
    video = files.save_bytes(MP4, mime="video/mp4", name="talk.mp4")
    project = await projects.open_project(video["id"])
    if state is not None:
        project = projects.update_project(project["id"], state=state)
    return project


def _transcript(file_id: int, *, model="large-v3-turbo", language="auto", duration=60.0, elapsed=30.0) -> int:
    return db.insert("transcripts", {
        "file_id": file_id, "engine": "faster-whisper", "model": model, "requested_language": language,
        "language": "en", "text": "old", "words_json": [{"text": "old", "start": 1.0, "end": 1.5}],
        "duration": duration, "elapsed_s": elapsed, "created_at": db.now(),
    })


async def test_job_saves_words_and_fills_subtitles(runner, fake_stt):
    project = await _project()
    started = transcribe.start(project["id"], language="en")
    assert started["transcript"] is None and started["job_id"]
    job = await _wait(started["job_id"])
    assert job["status"] == "done", job
    assert job["result_json"]["words"] == 2 and job["result_json"]["applied"] is True
    assert fake_stt["calls"] == [("transcribe", files.get(project["file_id"])["path"], "large-v3-turbo", "en")]
    row = db.get("transcripts", job["result_json"]["transcript_id"])
    assert row["requested_language"] == "en" and row["language"] == "en" and row["text"] == "Hello world"
    assert row["elapsed_s"] is not None and row["duration"] == 60.0
    sub = projects.project_dict(db.get("clip_projects", project["id"]))["state"]["subtitles"]
    assert sub["enabled"] is True and sub["transcript_id"] == row["id"]
    assert [w["text"] for w in sub["words"]] == ["Hello", "world"]


async def test_saved_transcript_is_reused(runner, fake_stt):
    project = await _project({"subtitles": {"words": [{"text": "mine", "start": 2, "end": 3}]}})
    tid = _transcript(project["file_id"])
    kept = transcribe.start(project["id"])
    assert kept["job_id"] is None and kept["transcript"]["id"] == tid and kept["applied"] is False
    words = projects.project_dict(db.get("clip_projects", project["id"]))["state"]["subtitles"]["words"]
    assert [w["text"] for w in words] == ["mine"]  # the editor's own words are not overwritten
    replaced = transcribe.start(project["id"], replace=True)
    assert replaced["applied"] is True
    words = projects.project_dict(db.get("clip_projects", project["id"]))["state"]["subtitles"]["words"]
    assert [w["text"] for w in words] == ["old"]
    assert fake_stt["calls"] == []  # nothing recognised again
    again = transcribe.start(project["id"], force=True)
    assert again["job_id"] is not None


async def test_running_job_is_reused(database, fake_stt):
    project = await _project()
    first = transcribe.start(project["id"])
    second = transcribe.start(project["id"], model="small")
    assert second["job_id"] == first["job_id"]
    assert jobs.get(first["job_id"])["kind"] == transcribe.JOB_KIND


async def test_stt_error_gets_its_own_code(runner, fake_stt):
    project = await _project()
    fake_stt["error"] = AppError("stt_failed", 502, "no sound in this file", service_code="no_audio")
    job = await _wait(transcribe.start(project["id"])["job_id"])
    assert job["status"] == "error" and job["error_code"] == "stt_no_audio"
    assert db.fetch_value("SELECT COUNT(*) FROM transcripts", (), 0) == 0


def test_unknown_model_and_language(database):
    with pytest.raises(AppError) as exc:
        transcribe.check_model("tiny")
    assert exc.value.code == "clip_stt_model"
    with pytest.raises(AppError) as exc:
        transcribe.check_language("de")
    assert exc.value.code == "clip_stt_language"
    assert transcribe.check_model(None) == "large-v3-turbo"
    assert transcribe.check_language(None) == "auto"


def test_estimate_from_setting_then_from_runs(database):
    guess = transcribe.estimate("large-v3-turbo", 120)
    assert guess["measured"] is False and guess["seconds_per_minute"] == 40.0 and guess["expected_s"] == 80
    settings.set("stt.seconds_per_minute_small", 6)
    assert transcribe.estimate("small", 60)["expected_s"] == 6
    video = files.save_bytes(MP4, mime="video/mp4", name="a.mp4")
    _transcript(video["id"], duration=60.0, elapsed=20.0)
    _transcript(video["id"], duration=120.0, elapsed=60.0)
    _transcript(video["id"], duration=60.0, elapsed=10.0)
    _transcript(video["id"], duration=2.0, elapsed=50.0)  # too short to count
    learned = transcribe.estimate("large-v3-turbo", 60)
    assert learned["measured"] is True and learned["samples"] == 3
    assert learned["seconds_per_minute"] == 20.0 and learned["expected_s"] == 20
    assert transcribe.estimate("large-v3-turbo", None)["expected_s"] is None


def test_stt_routes(api, fake_stt):
    listed = api.get("/api/clip/stt/models").json()
    assert [m["name"] for m in listed["items"]] == ["large-v3-turbo", "small"]
    assert listed["default"] == "large-v3-turbo" and listed["language"] == "auto"
    assert api.post("/api/clip/stt/models/small/download").json()["status"] == "downloading"
    assert api.post("/api/clip/stt/models/tiny/download").json()["error"]["code"] == "clip_stt_model"
    assert api.delete("/api/clip/stt/models/small").json() == {"ok": True}
    assert ("remove", "small") in fake_stt["calls"]
    fake_stt["error"] = AppError("stt_failed", 409, "busy", service_code="busy")
    res = api.post("/api/clip/stt/models/small/download")
    assert res.status_code == 409 and res.json()["error"]["code"] == "stt_busy"

    video = files.save_bytes(MP4, mime="video/mp4", name="talk.mp4")
    project = api.post("/api/clip/projects", json={"file_id": video["id"]}).json()
    est = api.get("/api/clip/stt/estimate", params={"project_id": project["id"]}).json()
    assert est["duration"] == 60.0 and est["expected_s"] == 40
    assert api.get("/api/clip/stt/estimate", params={"model": "small", "duration": 30}).json()["expected_s"] == 8
    started = api.post(f"/api/clip/projects/{project['id']}/transcribe", json={"model": "small"}).json()
    assert jobs.get(started["job_id"])["payload_json"]["model"] == "small"
    bad = api.post(f"/api/clip/projects/{project['id']}/transcribe", json={"language": "xx"})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "clip_stt_language"
    tid = _transcript(video["id"])
    assert api.get(f"/api/clip/transcripts/{tid}").json()["words"][0]["text"] == "old"
    assert api.get("/api/clip/transcripts/999999").status_code == 404
