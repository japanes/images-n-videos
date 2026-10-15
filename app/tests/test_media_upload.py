import io

import pytest
from PIL import Image

from vf.core import files, settings
from vf.modules.media import upload


def _png(size=(32, 24), color=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


MP4 = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2" + b"\x00" * 700
MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 700
HEIC = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic" + b"\x00" * 700
WOFF2 = b"wOF2" + b"\x00" * 700
MKV = b"\x1aE\xdf\xa3" + b"\x00" * 30 + b"matroska" + b"\x00" * 700


def _post(client, name, data, *, mime="application/octet-stream", title=None, kinds=None):
    params = {"kinds": kinds} if kinds else None
    form = {"title": title} if title is not None else None
    return client.post("/api/media/upload", params=params, data=form, files={"file": (name, data, mime)})


def _tmp_leftovers(cfg) -> list:
    tmp = cfg.data_dir / "cache" / "tmp"
    return [p for p in tmp.rglob("*") if p.is_file()] if tmp.is_dir() else []


@pytest.mark.parametrize(("head", "mime"), [
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff\xe0", "image/jpeg"),
    (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp"),
    (b"GIF89a", "image/gif"),
    (MP4[:40], "video/mp4"),
    (b"\x00\x00\x00\x14ftypqt  ", "video/quicktime"),
    (b"\x00\x00\x00\x08wide\x00\x00\x00\x00mdat", "video/quicktime"),
    (b"\x1aE\xdf\xa3\x00\x00\x00webm", "video/webm"),
    (b"ID3\x04", "audio/mpeg"),
    (b"\xff\xfb\x90\x00", "audio/mpeg"),
    (b"RIFF\x00\x00\x00\x00WAVEfmt ", "audio/wav"),
    (b"\x00\x00\x00\x18ftypM4A ", "audio/mp4"),
    (b"\xff\xf1\x50\x80", "audio/aac"),
    (b"OggS\x00\x02", "audio/ogg"),
    (b"fLaC\x00\x00", "audio/flac"),
    (b"\x00\x01\x00\x00\x00\x10", "font/ttf"),
    (b"OTTO\x00\x10", "font/otf"),
    (b"wOFF\x00\x01", "font/woff"),
    (b"wOF2\x00\x01", "font/woff2"),
])
def test_sniff_known_types(head, mime):
    assert upload.sniff(head + b"\x00" * 64) == mime


@pytest.mark.parametrize("head", [HEIC, MKV, b"<svg xmlns='http://www.w3.org/2000/svg'/>", b"%PDF-1.7", b"PK\x03\x04",
                                  b"hello world"])
def test_sniff_rejects_other_types(head):
    assert upload.sniff(head[:512]) is None


def test_clean_name_and_title():
    assert upload.clean_name("C:\\Users\\me\\photo.png") == "photo.png"
    assert upload.clean_name("../../etc/passwd") == "passwd"
    assert upload.clean_name("a\x00b\x1f.png") == "ab.png"
    long = upload.clean_name("x" * 400 + ".jpeg")
    assert len(long) == upload.MAX_NAME and long.endswith(".jpeg")
    assert upload.clean_title("  hi\nthere ") == "hi there"
    assert upload.clean_title("   ") is None
    assert len(upload.clean_title("y" * 500)) == upload.MAX_TITLE


def test_parse_kinds():
    assert upload.parse_kinds(None) == ("image", "video", "audio")
    assert upload.parse_kinds("Image, font,image") == ("image", "font")
    with pytest.raises(Exception) as err:
        upload.parse_kinds("image,exe")
    assert err.value.code == "bad_request"


def test_limits_endpoint(client):
    body = client.get("/api/media/limits").json()
    assert body["max_mb"] == {"image": 25, "video": 300, "audio": 100, "font": 25}
    assert "image/png" in body["types"]["image"] and "video/webm" in body["types"]["video"]
    assert body["default_kinds"] == ["image", "video", "audio"]


def test_upload_image_keeps_name_and_title(client, cfg):
    data = _png((40, 30))
    res = _post(client, "My photo.PNG", data, mime="image/png", title="  Cover  ")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["kind"] == "image" and body["mime"] == "image/png" and body["ext"] == "png"
    assert body["original_name"] == "My photo.PNG" and body["title"] == "Cover"
    assert (body["width"], body["height"]) == (40, 30)
    assert body["origin"] == "upload" and body["is_service"] is False
    assert body["source_group"] == "upload" and body["usage_count"] == 0
    assert body["ingest_job_id"] is None
    row = files.get(body["id"])
    assert files.abs_path(row["path"]).read_bytes() == data
    assert row["sha256"] and row["path"].startswith("files/")
    assert client.get(body["url"]).content == data
    assert _tmp_leftovers(cfg) == []


def test_type_comes_from_bytes_not_name(client):
    res = _post(client, "photo.png", b"just some text, not a picture" * 30, mime="image/png")
    assert res.status_code == 415
    assert res.json()["error"]["code"] == "unsupported_type"
    # A real JPEG named .png is stored as JPEG.
    buf = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buf, format="JPEG")
    body = _post(client, "photo.png", buf.getvalue(), mime="image/png").json()
    assert body["mime"] == "image/jpeg" and body["ext"] == "jpg"


def test_broken_image_is_refused(client, cfg):
    res = _post(client, "broken.png", b"\x89PNG\r\n\x1a\n" + b"\x00garbage" * 100)
    assert res.status_code == 415
    assert res.json()["error"]["code"] == "unsupported_type"
    assert _tmp_leftovers(cfg) == []
    assert [p for p in (cfg.data_dir / "files").rglob("*") if p.is_file()] == []


@pytest.mark.parametrize("data", [HEIC, MKV, b"<svg xmlns='http://www.w3.org/2000/svg'></svg>" * 20])
def test_unsupported_types(client, data):
    res = _post(client, "file.bin", data)
    assert res.status_code == 415
    assert res.json()["error"]["code"] == "unsupported_type"


def test_kinds_restrict_what_is_accepted(client):
    res = _post(client, "song.mp3", MP3, kinds="image")
    assert res.status_code == 415
    assert res.json()["error"]["details"]["kinds"] == ["image"]
    # Fonts only when the screen asks for them.
    assert _post(client, "brand.woff2", WOFF2).status_code == 415
    body = _post(client, "brand.woff2", WOFF2, kinds="font").json()
    assert body["kind"] == "font" and body["ext"] == "woff2"
    assert _post(client, "a.png", _png(), kinds="nope").status_code == 400


def test_empty_and_missing_file(client):
    res = _post(client, "empty.png", b"")
    assert res.status_code == 400 and res.json()["error"]["code"] == "upload_empty"
    res = client.post("/api/media/upload", data={"title": "x"}, files={"other": ("a.png", _png(), "image/png")})
    assert res.status_code == 400 and res.json()["error"]["code"] == "upload_empty"
    res = client.post("/api/media/upload", json={"file": "x"})
    assert res.status_code == 400 and res.json()["error"]["code"] == "bad_request"


def test_size_limit_while_streaming(client, cfg):
    assert client.put("/api/settings", json={"media.max_image_mb": 1}).status_code == 200
    big = b"\x89PNG\r\n\x1a\n" + b"\x00" * (1024 * 1024 + 10)
    res = _post(client, "big.png", big)
    assert res.status_code == 413
    err = res.json()["error"]
    assert err["code"] == "file_too_large" and err["details"]["max_mb"] == 1
    assert err["details"]["kind"] == "image"
    assert _tmp_leftovers(cfg) == []


def test_size_limit_from_content_length(client, cfg):
    settings.set("media.max_image_mb", 1)
    big = b"\x89PNG\r\n\x1a\n" + b"\x00" * (3 * 1024 * 1024)
    res = _post(client, "big.png", big, kinds="image")
    assert res.status_code == 413
    assert res.json()["error"]["details"]["max_mb"] == 1
    assert _tmp_leftovers(cfg) == []


def test_video_upload_queues_intake(client, monkeypatch):
    from vf.modules.media import ingest

    queued = []
    monkeypatch.setattr(ingest.jobs, "enqueue", lambda *a, **kw: queued.append((a, kw)) or 77)
    body = _post(client, "clip.mp4", MP4).json()
    assert body["kind"] == "video" and body["ingest_job_id"] == 77
    assert queued[0][0][0] == "media.ingest" and queued[0][1]["ref_id"] == body["id"]
    assert files.get(body["id"])["meta_json"]["ingest"]["status"] == "queued"
    audio = _post(client, "song.mp3", MP3).json()
    assert audio["kind"] == "audio" and audio["ingest_job_id"] == 77


def test_range_requests_on_files(client):
    body = _post(client, "clip.mp4", MP4, kinds="video").json()
    res = client.get(body["url"], headers={"Range": "bytes=0-9"})
    assert res.status_code == 206
    assert res.headers["content-range"] == f"bytes 0-9/{len(MP4)}"
    assert res.content == MP4[:10]
    assert res.headers.get("accept-ranges") == "bytes"
