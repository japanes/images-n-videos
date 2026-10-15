import io

import pytest
from PIL import Image

from vf.core import db, files
from vf.modules.media import library


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), (10, 120, 200)).save(buf, format="PNG")
    return buf.getvalue()


def _file(*, kind="image", origin="generated", source_type=None, service=False, title=None, name="a.png",
          created_at=None, size=None) -> dict:
    if kind == "image":
        row = files.save_bytes(_png(), name=name, origin=origin, source_type=source_type, service=service,
                               title=title)
    else:
        data = b"ID3\x04" + b"\x00" * (size or 100) if kind == "audio" else (
            b"\x00\x00\x00\x18ftypisom" + b"\x00" * (size or 100))
        mime = "audio/mpeg" if kind == "audio" else "video/mp4"
        row = files.save_bytes(data, mime=mime, name=name, origin=origin, source_type=source_type,
                               service=service, title=title)
    if created_at:
        db.update("files", row["id"], {"created_at": created_at})
    return files.get(row["id"])


@pytest.fixture
def usage_map():
    """A fake module that uses files: ``usage_map[file_id] = [usages]``."""
    used: dict[int, list[dict]] = {}

    def provider(file_id: int) -> list[dict]:
        return used.get(file_id, [])

    files._usage_providers.append(provider)
    yield used
    files._usage_providers.remove(provider)


def test_source_groups(database):
    assert library.source_group({"origin": "upload", "source_type": "avatar"}) == "upload"
    assert library.source_group({"origin": "generated", "source_type": "avatar_video"}) == "avatar"
    assert library.source_group({"origin": "generated", "source_type": "editor_export"}) == "export"
    assert library.source_group({"origin": "generated", "source_type": "editor_trim"}) == "editor"
    assert library.source_group({"origin": "derived", "source_type": None}) == "editor"
    assert library.source_group({"origin": "generated", "source_type": "studio_image"}) == "generation"


def test_list_filters_and_pages(database):
    up = _file(origin="upload", title="Beach day", name="beach.png", created_at="2026-10-01T10:00:00.000Z")
    gen = _file(source_type="studio_image", name="robot.png", created_at="2026-10-02T10:00:00.000Z")
    ava = _file(kind="video", source_type="avatar_video", name="anna.mp4", created_at="2026-10-03T10:00:00.000Z")
    exp = _file(kind="video", source_type="editor_export", name="final.mp4", created_at="2026-10-04T10:00:00.000Z")
    snd = _file(kind="audio", origin="upload", name="song 100%.mp3", created_at="2026-10-05T10:00:00.000Z")
    _file(service=True, name="internal.png")
    _file(kind="image", name="x.png")
    font = files.save_bytes(b"wOF2" + b"\x00" * 50, mime="font/woff2", name="brand.woff2", origin="upload")

    everything = library.list_files()
    ids = [i["id"] for i in everything["items"]]
    assert everything["total"] == 6 and font["id"] not in ids
    assert ids[1:] == [snd["id"], exp["id"], ava["id"], gen["id"], up["id"]]  # newest first

    assert [i["id"] for i in library.list_files(kind="video")["items"]] == [exp["id"], ava["id"]]
    assert {i["id"] for i in library.list_files(source="upload")["items"]} == {up["id"], snd["id"]}
    assert [i["id"] for i in library.list_files(source="avatar,export")["items"]] == [exp["id"], ava["id"]]
    assert [i["id"] for i in library.list_files(q="beach")["items"]] == [up["id"]]  # title
    assert [i["id"] for i in library.list_files(q="ROBOT")["items"]] == [gen["id"]]  # original name
    assert [i["id"] for i in library.list_files(q="100%")["items"]] == [snd["id"]]  # % is literal
    assert library.list_files(q="1_0")["total"] == 0
    days = library.list_files(date_from="2026-10-02", date_to="2026-10-04")
    assert [i["id"] for i in days["items"]] == [ava["id"], gen["id"]]
    since = library.list_files(date_from="2026-10-03T12:00:00+01:00")
    assert snd["id"] in [i["id"] for i in since["items"]] and ava["id"] not in [i["id"] for i in since["items"]]

    page = library.list_files(page=2, limit=4)
    assert page["pages"] == 2 and page["page"] == 2 and len(page["items"]) == 2

    with pytest.raises(Exception) as err:
        library.list_files(kind="font")
    assert err.value.code == "bad_request"
    with pytest.raises(Exception) as err:
        library.list_files(date_from="yesterday")
    assert err.value.code == "bad_request"


def test_item_shape(database):
    row = _file(kind="video", source_type="avatar_video")
    item = library.item(row)
    assert item["source_group"] == "avatar" and item["ext"] == "mp4"
    assert item["thumb_url"] is None and item["preview_url"] is None
    assert item["usage_count"] == 0 and item["ingest"] is None and "usages" not in item


def test_files_api_and_usages(client, usage_map):
    a = _file(origin="upload", name="face.png")
    b = _file(origin="upload", name="free.png")
    usage_map[a["id"]] = [{"type": "avatar", "id": 3, "title": "Anna", "url": "/avatars/3"}]

    items = client.get("/api/media/files").json()["items"]
    counts = {i["id"]: i["usage_count"] for i in items}
    assert counts == {a["id"]: 1, b["id"]: 0}

    detail = client.get(f"/api/media/files/{a['id']}").json()
    assert detail["usages"] == usage_map[a["id"]]

    res = client.delete(f"/api/media/files/{a['id']}")
    assert res.status_code == 409
    err = res.json()["error"]
    assert err["code"] == "file_in_use" and err["details"]["usages"][0]["title"] == "Anna"
    assert files.abs_path(a["path"]).exists()

    res = client.post("/api/media/files/delete", json={"ids": [a["id"], b["id"], 999999]}).json()
    assert res["deleted"] == [b["id"]] and res["missing"] == [999999]
    assert res["blocked"][0]["id"] == a["id"] and res["blocked"][0]["usages"][0]["type"] == "avatar"
    assert db.get("files", b["id"]) is None and not files.abs_path(b["path"]).exists()

    usage_map.clear()
    assert client.delete(f"/api/media/files/{a['id']}").json() == {"ok": True, "id": a["id"]}
    assert client.get(f"/api/media/files/{a['id']}").status_code == 404


def test_broken_usage_provider_blocks_delete(client):
    row = _file(origin="upload")

    def broken(_file_id):
        raise RuntimeError("module is down")

    files._usage_providers.append(broken)
    try:
        item = client.get(f"/api/media/files/{row['id']}").json()
        assert item["usages"] is None and item["usage_count"] is None
        with pytest.raises(RuntimeError):
            client.delete(f"/api/media/files/{row['id']}")
        res = client.post("/api/media/files/delete", json={"ids": [row["id"]]}).json()
        assert res["deleted"] == [] and res["blocked"] == [{"id": row["id"], "title": "a.png", "usages": None}]
        assert db.get("files", row["id"]) is not None
    finally:
        files._usage_providers.remove(broken)


def test_service_files_are_hidden(client):
    row = _file(service=True)
    assert client.get(f"/api/media/files/{row['id']}").status_code == 404
    assert client.delete(f"/api/media/files/{row['id']}").status_code == 404
    assert client.patch(f"/api/media/files/{row['id']}", json={"title": "x"}).status_code == 404
    res = client.post("/api/media/files/delete", json={"ids": [row["id"]]}).json()
    assert res == {"deleted": [], "blocked": [], "missing": [row["id"]]}
    assert db.get("files", row["id"]) is not None


def test_rename(client):
    row = _file(origin="upload", name="a.png")
    body = client.patch(f"/api/media/files/{row['id']}", json={"title": "  New name \n"}).json()
    assert body["title"] == "New name" and body["usages"] == []
    assert client.patch(f"/api/media/files/{row['id']}", json={"title": ""}).json()["title"] is None
    assert client.patch(f"/api/media/files/{row['id']}", json={"title": "z" * 300}).status_code == 400


def test_reingest_only_for_video_and_audio(client, monkeypatch):
    from vf.modules.media import ingest

    monkeypatch.setattr(ingest.jobs, "enqueue", lambda *a, **kw: 5)
    image = _file()
    video = _file(kind="video")
    assert client.post(f"/api/media/files/{image['id']}/ingest").status_code == 400
    assert client.post(f"/api/media/files/{video['id']}/ingest").json() == {"job_id": 5}


def test_stats(client, cfg):
    _file(origin="upload")
    _file(kind="video", size=5000)
    _file(service=True)
    (cfg.data_dir / "cache" / "thumbs" / "1").mkdir(parents=True, exist_ok=True)
    (cfg.data_dir / "cache" / "thumbs" / "1" / "480.webp").write_bytes(b"x" * 300)
    body = client.get("/api/media/stats").json()
    assert body["by_kind"]["image"]["count"] == 1 and body["by_kind"]["video"]["count"] == 1
    assert body["by_kind"]["video"]["bytes"] >= 5000
    assert body["service_bytes"] > 0 and body["cache_bytes"] >= 300
    assert body["total_bytes"] == body["library_bytes"] + body["service_bytes"] + body["cache_bytes"]
    assert body["disk"]["free"] > 0 and body["disk"]["total"] >= body["disk"]["free"]
