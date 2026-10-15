"""Module 08: brand kits — CRUD, colors, assets, fonts, snapshot, file usage."""

import io

import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from PIL import Image

from vf.core import db, files
from vf.core.errors import AppError
from vf.modules.brand import fonts, kits


def png_bytes(color=(200, 30, 30), size=(64, 48)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def make_font(family="Plain Face", *, fixed=False, ibm_class=0, weight=400) -> bytes:
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder([".notdef", "A"])
    fb.setupCharacterMap({65: "A"})
    pen = TTGlyphPen(None)
    pen.moveTo((0, 0))
    pen.lineTo((0, 500))
    pen.lineTo((500, 0))
    pen.closePath()
    glyph = pen.glyph()
    fb.setupGlyf({".notdef": glyph, "A": glyph})
    fb.setupHorizontalMetrics({".notdef": (500, 0), "A": (500, 0)})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": family, "styleName": "Regular"})
    fb.setupOS2(sFamilyClass=ibm_class << 8, usWeightClass=weight)
    fb.setupPost(isFixedPitch=1 if fixed else 0)
    buf = io.BytesIO()
    fb.save(buf)
    return buf.getvalue()


# ── fonts: local category detection ─────────────────────────────────────────


@pytest.mark.parametrize(("kwargs", "category", "by"), [
    ({"fixed": True}, "mono", "fixed_pitch"),
    ({"ibm_class": 10}, "handwriting", "ibm_class"),
    ({"ibm_class": 8}, "sans", "ibm_class"),
    ({"ibm_class": 1}, "serif", "ibm_class"),
    ({"family": "Grand Serif"}, "serif", "name"),
    ({"family": "Grand Sans Serif"}, "sans", "name"),
    ({"family": "Plain Face"}, "sans", "default"),
])
def test_font_category(kwargs, category, by):
    info = fonts.inspect_font(make_font(**kwargs))
    assert info.category == category
    assert info.detected_by == by
    assert info.family


def test_font_rejects_garbage():
    with pytest.raises(AppError) as err:
        fonts.inspect_font(b"not a font at all")
    assert err.value.code == "font_unreadable"


# ── kits over HTTP ──────────────────────────────────────────────────────────


def test_kit_crud_and_colors(client):
    r = client.post("/api/brand/kits", json={"name": "  Coffee  shop ", "colors": ["#abc", {"hex": "112233", "label": "Dark"}]})
    assert r.status_code == 200, r.text
    kit = r.json()
    assert kit["name"] == "Coffee shop"
    assert kit["colors"] == [{"hex": "#AABBCC", "label": ""}, {"hex": "#112233", "label": "Dark"}]
    rev = kit["revision"]

    r = client.patch(f"/api/brand/kits/{kit['id']}", json={"tone": "Friendly, short sentences."})
    assert r.json()["tone"] == "Friendly, short sentences."
    assert r.json()["revision"] > rev

    r = client.patch(f"/api/brand/kits/{kit['id']}", json={"colors": ["#12345"]})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "bad_color"

    r = client.post("/api/brand/kits", json={"name": "   "})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "name_required"

    items = client.get("/api/brand/kits").json()["items"]
    assert [k["name"] for k in items] == ["Coffee shop"]

    assert client.delete(f"/api/brand/kits/{kit['id']}").status_code == 200
    assert client.get(f"/api/brand/kits/{kit['id']}").status_code == 404


def test_kit_assets_upload_order_and_delete(client):
    kit = client.post("/api/brand/kits", json={"name": "Shop"}).json()
    kid = kit["id"]
    ids = []
    for index, kind in enumerate(["logo", "logo", "sticker", "reference"]):
        r = client.post(f"/api/brand/kits/{kid}/assets", files={"file": (f"pic{index}.png", png_bytes(), "image/png")},
                        data={"kind": kind})
        assert r.status_code == 200, r.text
        asset = r.json()
        assert asset["kind"] == kind
        assert asset["name"] == f"pic{index}"
        assert asset["file"]["url"]
        ids.append(asset["id"])

    r = client.post(f"/api/brand/kits/{kid}/assets", files={"file": ("x.gif", b"GIF89a....", "image/gif")},
                    data={"kind": "logo"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "bad_image_type"

    r = client.patch(f"/api/brand/assets/{ids[2]}", json={"position_hint": "bottom right corner",
                                                          "note": "only on light backgrounds", "name": "Star"})
    assert r.json()["position_hint"] == "bottom right corner"
    assert r.json()["name"] == "Star"

    r = client.put(f"/api/brand/kits/{kid}/assets/order", json={"ids": [ids[1], ids[0]]})
    assert r.status_code == 200
    logos = [a["id"] for a in r.json()["items"] if a["kind"] == "logo"]
    assert logos == [ids[1], ids[0]]
    r = client.put(f"/api/brand/kits/{kid}/assets/order", json={"ids": [99999]})
    assert r.json()["error"]["code"] == "bad_order"

    kit = client.get(f"/api/brand/kits/{kid}").json()
    assert kit["counts"] == {"logo": 2, "sticker": 1, "reference": 1}
    assert kit["logo"]["id"] == next(a for a in kit["assets"] if a["id"] == ids[1])["file_id"]

    # Our own uploaded file goes away with the asset.
    file_id = next(a for a in kit["assets"] if a["id"] == ids[3])["file_id"]
    assert client.delete(f"/api/brand/assets/{ids[3]}").status_code == 200
    assert db.get("files", file_id) is None


def test_kit_font_upload_and_category_override(client):
    kid = client.post("/api/brand/kits", json={"name": "Type"}).json()["id"]
    r = client.post(f"/api/brand/kits/{kid}/fonts",
                    files={"file": ("Grand-Serif.ttf", make_font("Grand Serif"), "font/ttf")})
    assert r.status_code == 200, r.text
    asset = r.json()
    assert asset["kind"] == "font"
    assert asset["font"]["family"] == "Grand Serif"
    assert asset["font"]["category"] == "serif"
    assert asset["font"]["detected_by"] == "name"
    assert asset["file"]["mime"] == "font/ttf"

    r = client.patch(f"/api/brand/assets/{asset['id']}", json={"font_category": "display"})
    assert r.json()["font"]["category"] == "display"
    assert r.json()["font"]["detected_category"] == "serif"
    r = client.patch(f"/api/brand/assets/{asset['id']}", json={"font_category": "fancy"})
    assert r.json()["error"]["code"] == "bad_font_category"

    r = client.post(f"/api/brand/kits/{kid}/fonts", files={"file": ("x.ttf", b"\x00\x01\x00\x00junk", "font/ttf")})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "font_unreadable"


def test_used_file_cannot_be_deleted(client):
    kid = client.post("/api/brand/kits", json={"name": "Shop"}).json()["id"]
    stored = files.save_bytes(png_bytes(), mime="image/png", name="lib.png", origin="upload")
    r = client.post(f"/api/brand/kits/{kid}/assets/from-file", json={"kind": "reference", "file_id": stored["id"]})
    assert r.status_code == 200, r.text
    with pytest.raises(AppError) as err:
        files.delete(stored["id"])
    assert err.value.code == "file_in_use"
    assert err.value.details["usages"][0]["type"] == "brand_kit"

    # Removing the asset keeps a file that was picked from elsewhere.
    client.delete(f"/api/brand/assets/{r.json()['id']}")
    assert db.get("files", stored["id"]) is not None
    files.delete(stored["id"])


# ── snapshot ────────────────────────────────────────────────────────────────


def test_snapshot_and_kit_changed(database):
    kit = kits.create_kit("Bakery", colors=["#ff0000"], tone="Warm")
    kits.add_image_asset(kit["id"], "logo", png_bytes(), filename="logo.png")
    kits.add_image_asset(kit["id"], "frame", png_bytes(), filename="frame.png")
    kits.add_image_asset(kit["id"], "reference", png_bytes(), filename="ref.png")
    kits.add_font_upload(kit["id"], make_font("Grand Serif"), filename="g.ttf")
    snap = kits.snapshot_kit(kit["id"])
    assert snap["colors"] == [{"hex": "#FF0000", "label": ""}]
    assert snap["tone"] == "Warm"
    assert len(snap["logos"]) == 1 and len(snap["references"]) == 1
    assert snap["elements"][0]["kind"] == "frame"
    assert snap["fonts"][0]["family"] == "Grand Serif"
    assert kits.kit_changed(snap) is False

    kits.update_kit(kit["id"], tone="Warm and short")
    assert kits.kit_changed(snap) is True
    fresh = kits.snapshot_kit(kit["id"])
    assert fresh["tone"] == "Warm and short"
    assert kits.kit_changed(fresh) is False

    kits.delete_kit(kit["id"])
    assert kits.kit_changed(fresh) is None
    assert db.fetch_value("SELECT COUNT(*) FROM files WHERE source_type = 'brand_asset'") == 0


def test_catalog_font_for_module_06(database):
    kit = kits.create_kit("Fonts")
    asset = kits.add_catalog_font(kit["id"], "Roboto Slab", "serif")
    assert asset["font"]["source"] == "google"
    assert asset["file_id"] is None
    with pytest.raises(AppError):
        kits.add_catalog_font(kit["id"], "X", "weird")
