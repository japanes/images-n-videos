import io

from PIL import Image

from vf.core import files
from vf.modules import library


def _png(color=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (32, 24), color).save(buf, format="PNG")
    return buf.getvalue()


def test_categories_and_builtin_list(client):
    cats = client.get("/api/library/categories").json()
    assert len(cats["items"]) == 756
    roots = [c for c in cats["items"] if c["parent"] is None]
    assert len(roots) == 12
    assert sum(c["count"] for c in roots) + cats["uncategorized"] == cats["total"] == 67

    builtin = client.get("/api/library/styles", params={"tab": "builtin", "limit": 200}).json()
    assert builtin["total"] == 67
    photo = client.get("/api/library/styles", params={"tab": "builtin", "kind": "photo_style"}).json()
    assert photo["total"] == 31
    assert client.get("/api/library/styles", params={"tab": "mine"}).json()["total"] == 0

    style = client.get("/api/library/styles/1").json()
    assert style["code"] and style["is_builtin"] is True and style["variables"]
    assert style["category_path"][-1]["slug"] == style["category"]
    assert client.get("/api/library/styles", params={"tab": "nope"}).status_code == 422


def test_search_and_category_filter(client):
    one = client.get("/api/library/styles/1").json()
    word = one["title"].split()[0].upper()          # any case, Cyrillic too
    found = client.get("/api/library/styles", params={"q": word}).json()
    assert one["id"] in [s["id"] for s in found["items"]]
    root = one["category_path"][0]["slug"]
    sub = client.get("/api/library/styles", params={"category": root, "limit": 200}).json()
    assert one["id"] in [s["id"] for s in sub["items"]]
    assert all(s["category"] == root or s["category"].startswith(root + "/") for s in sub["items"])
    nothing = client.get("/api/library/styles", params={"q": "zzqqxx-no-such-style"}).json()
    assert nothing["total"] == 0


def test_shipped_preview_is_served(client):
    style = client.get("/api/library/styles/1").json()
    assert style["preview_url"] == f"/api/library/previews/{style['id']}"
    res = client.get(style["preview_url"])
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/jpeg"
    photo = client.get("/api/library/styles", params={"kind": "photo_style"}).json()["items"][0]
    assert photo["preview_url"] is None
    assert client.get(f"/api/library/previews/{photo['id']}").status_code == 404


def test_builtin_is_read_only_and_copy_goes_to_mine(client):
    style = client.get("/api/library/styles/1").json()
    res = client.patch(f"/api/library/styles/{style['id']}", json={"title": "x"})
    assert res.status_code == 409 and res.json()["error"]["code"] == "library_builtin_readonly"
    assert client.delete(f"/api/library/styles/{style['id']}").status_code == 409

    copy = client.post(f"/api/library/styles/{style['id']}/copy", json={}).json()
    assert copy["is_builtin"] is False and copy["code"] is None and copy["copied_from"] == style["code"]
    assert copy["prompt"] == style["prompt"] and copy["title"] == style["title"]
    assert copy["preview_url"] == f"/api/library/previews/{copy['id']}"
    mine = client.get("/api/library/styles", params={"tab": "mine"}).json()
    assert [s["id"] for s in mine["items"]] == [copy["id"]]

    edited = client.patch(f"/api/library/styles/{copy['id']}", json={"title": "My neon"}).json()
    assert edited["title"] == "My neon"
    assert client.get(f"/api/library/styles/{style['id']}").json()["title"] == style["title"]


def test_own_style_crud_and_validation(client):
    bad = client.post("/api/library/styles", json={"title": " ", "prompt": "x"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "library_title_required"
    bad = client.post("/api/library/styles", json={"title": "A", "prompt": ""})
    assert bad.json()["error"]["code"] == "library_prompt_required"
    bad = client.post("/api/library/styles", json={"title": "A", "prompt": "x" * 4001})
    assert bad.json()["error"]["code"] == "library_too_long"
    bad = client.post("/api/library/styles", json={"title": "A", "prompt": " ".join(f"{{{{v{i}}}}}" for i in range(21))})
    assert bad.json()["error"]["code"] == "library_too_many_variables"
    bad = client.post("/api/library/styles", json={"title": "A", "prompt": "x", "category": "no/such"})
    assert bad.json()["error"]["code"] == "library_unknown_category"
    bad = client.post("/api/library/styles", json={"title": "A", "prompt": "x", "kind": "banner"})
    assert bad.json()["error"]["code"] == "library_bad_kind"
    bad = client.post("/api/library/styles", json={"title": "A", "prompt": "x", "text_zones": "{oops"})
    assert bad.json()["error"]["code"] == "text_zones_invalid_json"

    category = client.get("/api/library/categories").json()["items"][5]["slug"]
    created = client.post("/api/library/styles", json={
        "title": "  Soft   pastel ", "prompt": "Pastel {{subject|cup}} on {{background_color|#f0e0d0}}",
        "kind": "photo_style", "category": category,
        "text_zones": '{"zones": [{"x": 10, "y": 10, "w": 80, "h": 20}]}',
    }).json()
    assert created["title"] == "Soft pastel" and created["kind"] == "photo_style"
    assert created["text_zone_count"] == 1 and created["category"] == category
    assert [v["key"] for v in created["variables"]] == ["subject", "background_color"]

    cleared = client.patch(f"/api/library/styles/{created['id']}", json={"text_zones": None}).json()
    assert cleared["text_zones"] is None and cleared["title"] == "Soft pastel"

    assert client.delete(f"/api/library/styles/{created['id']}").json()["ok"] is True
    assert client.get(f"/api/library/styles/{created['id']}").status_code == 404


def test_preview_upload_is_a_used_file(client):
    style = client.post("/api/library/styles", json={"title": "Mine", "prompt": "Neon"}).json()
    res = client.post(f"/api/library/styles/{style['id']}/preview", files={"file": ("p.png", _png(), "image/png")})
    assert res.status_code == 200
    updated = res.json()
    file_id = updated["preview_file_id"]
    assert updated["preview_url"] == f"/files/{file_id}?w=480"
    assert files.usages(file_id) == [{"type": "style", "id": style["id"], "title": "Mine"}]
    assert client.get(f"/files/{file_id}").status_code == 200

    wrong = client.post(f"/api/library/styles/{style['id']}/preview",
                        files={"file": ("p.txt", b"hello there", "text/plain")})
    assert wrong.status_code == 400 and wrong.json()["error"]["code"] == "library_bad_image"

    cleared = client.delete(f"/api/library/styles/{style['id']}/preview").json()
    assert cleared["preview_url"] is None
    assert files.usages(file_id) == []
    # the uploaded picture stays in the media library
    assert client.get(f"/files/{file_id}").status_code == 200

    again = client.post(f"/api/library/styles/{style['id']}/preview/from-file", json={"file_id": file_id}).json()
    assert again["preview_file_id"] == file_id


def test_render_fills_slots_on_the_server(client):
    style = client.post("/api/library/styles", json={
        "title": "Neon", "prompt": "Neon sign {{brand|ACME}} over {{background_color|black}} wall"}).json()
    plain = client.post("/api/library/render", json={"style_id": style["id"]}).json()
    assert plain["prompt"] == "Neon sign ACME over black wall"
    typed = client.post("/api/library/render", json={
        "style_id": style["id"], "values": {"Brand": "SALT"}, "extra": "rainy night"}).json()
    assert typed["prompt"] == "Neon sign SALT over black wall\nrainy night"
    assert typed["values"] == {"brand": "SALT", "background_color": ""}

    ref = library.make_style_ref(style, {"brand": "STONE"}, extra="")
    by_ref = client.post("/api/library/render", json={"ref": ref}).json()
    assert by_ref["prompt"] == "Neon sign STONE over black wall"

    client.delete(f"/api/library/styles/{style['id']}")
    assert client.post("/api/library/render", json={"ref": ref}).status_code == 404
    assert library.render_style(ref) is None          # a deleted style: the work goes without it


def test_random_style(client):
    first = client.get("/api/library/styles/random").json()["item"]
    assert first["kind"] == "style" and first["is_builtin"] is True
    for _ in range(10):
        again = client.get("/api/library/styles/random", params={"exclude": first["id"]}).json()["item"]
        assert again["id"] != first["id"]
    photo = client.get("/api/library/styles/random", params={"kind": "photo_style"}).json()["item"]
    assert photo["kind"] == "photo_style"
    assert client.get("/api/library/styles/random", params={"tab": "mine"}).json()["item"] is None


def test_python_helpers(client):
    photo = client.get("/api/library/styles", params={"kind": "photo_style"}).json()["items"][0]
    assert library.photo_style_text(photo["id"]) == photo["prompt"].strip()
    assert library.photo_style_text(999999) is None
    assert library.photo_style_text(1) is None or library.get_style(1)["kind"] == "photo_style"
    blob = library.preview_blob(1)
    assert blob is not None and blob.mime == "image/jpeg" and blob.data[:3] == b"\xff\xd8\xff"
    assert library.preview_blob(photo["id"]) is None
    typed = library.resolve_style_value("  watercolor, soft edges ")
    assert typed["prompt"] == "watercolor, soft edges" and typed["preset_id"] is None
    assert library.resolve_style_value("") is None
    assert library.find_style(999999) is None
    assert library.get_style("style-1")["id"] == library.get_style(1)["id"]
