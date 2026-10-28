import pytest


def test_health(client):
    body = client.get("/health").json()
    assert body == {"ok": True, "version": "1.2.3", "google_mode": "stub"}


def test_meta(client):
    body = client.get("/api/meta").json()
    assert body["stub"] is True and body["has_key"] is False


def test_models_list_and_roles(client):
    items = client.get("/api/models").json()["items"]
    assert {m["kind"] for m in items} == {"image", "video", "text"}
    roles = client.get("/api/models/roles").json()["items"]
    assert roles and all("model_id" in r for r in roles)


def test_model_default_switch(client):
    images = client.get("/api/models", params={"kind": "image"}).json()["items"]
    other = next(m for m in images if not m["is_default"])
    res = client.patch(f"/api/models/{other['id']}", json={"is_default": True})
    assert res.status_code == 200 and res.json()["is_default"] is True


def test_settings_roundtrip(client):
    res = client.put("/api/settings", json={"google.max_rpm": 20})
    assert res.status_code == 200
    assert res.json()["values"]["google.max_rpm"] == 20
    assert client.put("/api/settings", json={"google.max_rpm": None}).json()["values"]["google.max_rpm"] == 8


def test_bad_setting(client):
    res = client.put("/api/settings", json={"nope": 1})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "unknown_setting"


@pytest.mark.parametrize("kind", ["image", "text", "video"])
def test_estimate(client, kind):
    res = client.post("/api/estimate", json={"kind": kind})
    assert res.status_code == 200
    assert res.json()["usd"] > 0


def test_estimate_batch(client):
    res = client.post("/api/estimate/batch", json=[{"kind": "image", "count": 2}, {"kind": "text"}])
    body = res.json()
    assert body["usd"] == pytest.approx(sum(i["usd"] for i in body["items"]), abs=1e-4)


def test_unknown_api_is_json_404(client):
    res = client.get("/api/nothing-here")
    assert res.status_code == 404
    assert "error" in res.json()


def test_spa_placeholder_without_build(client):
    res = client.get("/studio")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]


def test_spa_serves_built_index(tmp_path, cfg):
    from dataclasses import replace

    from fastapi.testclient import TestClient

    from vf.core.config import set_config
    from vf.main import create_app

    web = tmp_path / "web"
    (web / "_nuxt").mkdir(parents=True)
    (web / "index.html").write_text("<html>APP</html>")
    (web / "_nuxt" / "a.js").write_text("console.log(1)")
    config = replace(cfg, web_dir=web)
    set_config(config)
    with TestClient(create_app(config)) as c:
        assert "APP" in c.get("/chat/5").text
        assert c.get("/_nuxt/a.js").text == "console.log(1)"
        assert c.get("/../../etc/passwd").status_code in (200, 404)
        assert "root:" not in c.get("/../../etc/passwd").text


def test_file_serving_and_thumbs(client):
    from io import BytesIO

    from PIL import Image

    from vf.core import files

    buf = BytesIO()
    Image.new("RGB", (800, 400), "blue").save(buf, "PNG")
    row = files.save_bytes(buf.getvalue(), name="b.png")
    full = client.get(f"/files/{row['id']}")
    assert full.status_code == 200 and full.content == buf.getvalue()
    thumb = client.get(f"/files/{row['id']}", params={"w": 300})
    assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/webp"
    assert Image.open(BytesIO(thumb.content)).width == 320
    assert client.get("/files/999999").status_code == 404
    info = client.get(f"/api/files/{row['id']}").json()
    assert info["width"] == 800


def test_posters_are_revalidated_but_images_are_immutable(client):
    """A video ingested again keeps its id but gets a new poster: no stale browser copy."""
    from io import BytesIO

    from PIL import Image

    from vf.core import db, files

    buf = BytesIO()
    Image.new("RGB", (640, 360), "red").save(buf, "JPEG")
    image = files.save_bytes(buf.getvalue(), name="p.jpg")
    assert "immutable" in client.get(f"/files/{image['id']}").headers["cache-control"]
    assert "immutable" in client.get(f"/files/{image['id']}", params={"w": 160}).headers["cache-control"]

    video = files.save_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64, name="v.mp4", mime="video/mp4")
    rel, abs_path = files.allocate("jpg")
    abs_path.write_bytes(buf.getvalue())
    db.update("files", video["id"], {"poster_path": rel})
    for url, params in ((f"/files/{video['id']}/poster", None), (f"/files/{video['id']}", {"w": 160})):
        res = client.get(url, params=params)
        assert res.status_code == 200
        assert res.headers["cache-control"] == "private, no-cache"
        assert res.headers.get("etag")
