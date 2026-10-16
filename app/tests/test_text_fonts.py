"""Module 06 fonts: the brand's type specimen for «the model draws the letters» and adding a
Google font to a kit (the network is replaced by a fake ``google_fonts.fetch``)."""

import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from vf.core import db, files
from vf.core.errors import AppError
from vf.core.google import Blob
from vf.modules import text
from vf.modules.brand import kits
from vf.modules.text import font_sheet, google_fonts
from vf.modules.text import fonts as F

ROBOTO = F.REGULAR.read_bytes()
FILE_URL = "https://fonts.gstatic.com/s/lobster/v30/Lobster-Regular.ttf"


@pytest.fixture
def api(cfg):
    from vf.main import create_app

    with TestClient(create_app(cfg, run_background=False)) as c:
        yield c


def code_of(exc_info) -> str:
    return exc_info.value.code


def sheets(kit_id: int) -> list[dict]:
    return db.fetch_all("SELECT * FROM text_font_sheets WHERE kit_id = ?", (kit_id,))


class FakeGoogle:
    """What fonts.google.com and fonts.gstatic.com answer; every request is noted."""

    def __init__(self, url: str = FILE_URL, data: bytes = ROBOTO):
        self.url, self.data, self.seen = url, data, []

    async def __call__(self, url: str, params: dict | None = None) -> bytes:
        self.seen.append((url, params))
        if url == google_fonts.LIST_URL:
            refs = [{"filename": "static/Lobster-Italic.ttf", "url": self.url.replace("Regular", "Italic")},
                    {"filename": "static/Lobster-Regular.ttf", "url": self.url},
                    {"filename": "OFL.txt", "url": "https://fonts.gstatic.com/ofl.txt"}]
            return (")]}'" + json.dumps({"manifest": {"fileRefs": refs}})).encode()
        return self.data


@pytest.fixture
def fake(monkeypatch):
    fake = FakeGoogle()
    monkeypatch.setattr(google_fonts, "fetch", fake)
    return fake


# ── the type specimen ───────────────────────────────────────────────────────


def test_a_kit_without_fonts_has_no_sheet(database):
    kit = kits.create_kit("Empty")
    sheet = text.ensure_font_sheet(kit["id"])
    assert sheet["file_id"] is None and sheet["fonts"] == 0 and sheet["rebuilt"] is False
    assert text.font_sheet_parts(kit["id"]) == []
    with pytest.raises(AppError) as e:
        text.ensure_font_sheet(99999)
    assert code_of(e) == "not_found"
    with pytest.raises(AppError) as e:
        text.ensure_font_sheet("x")
    assert code_of(e) == "bad_request"


def test_the_sheet_is_drawn_once_per_set_of_fonts(database):
    kit = kits.create_kit("Cafe")
    kits.add_font_upload(kit["id"], ROBOTO, filename="Roboto.ttf")
    first = text.ensure_font_sheet(kit["id"])
    assert first["file_id"] and first["drawn"] == 1 and first["fonts"] == 1 and first["rebuilt"] is True
    picture = Image.open(io.BytesIO(files.read_bytes(first["file_id"])))
    assert picture.width == font_sheet.SHEET_WIDTH and picture.height > 200
    row = db.get("files", first["file_id"])
    assert row["source_type"] == "text_font_sheet" and row["source_id"] == kit["id"]

    cached = text.ensure_font_sheet(kit["id"])
    assert cached["file_id"] == first["file_id"] and cached["rebuilt"] is False

    forced = text.ensure_font_sheet(kit["id"], force=True)
    assert forced["rebuilt"] is True and forced["signature"] == first["signature"]
    assert len(sheets(kit["id"])) == 1              # the old sheet was replaced, not kept
    assert files.read_bytes(forced["file_id"])[:4] == b"\x89PNG"

    bold = kits.add_font_upload(kit["id"], F.BOLD.read_bytes(), filename="Roboto-Bold.ttf")
    grown = text.ensure_font_sheet(kit["id"])
    assert grown["rebuilt"] is True and grown["drawn"] == 2 and grown["signature"] != forced["signature"]
    taller = Image.open(io.BytesIO(files.read_bytes(grown["file_id"])))
    assert taller.height > picture.height

    kits.delete_asset(bold["id"])
    assert text.ensure_font_sheet(kit["id"])["signature"] == forced["signature"]


def test_a_font_that_does_not_open_is_left_out(database):
    kit = kits.create_kit("Broken")
    kits.add_font_upload(kit["id"], ROBOTO, filename="Roboto.ttf")
    junk = files.save_bytes(b"not a font at all", mime="font/ttf", name="junk.ttf", origin="upload")
    kits.add_catalog_font(kit["id"], "Junk Sans", "sans", file_id=junk["id"])
    sheet = text.ensure_font_sheet(kit["id"])
    assert sheet["fonts"] == 2 and sheet["drawn"] == 1


def test_the_studio_gets_a_label_and_the_picture(database):
    kit = kits.create_kit("Cafe")
    kits.add_font_upload(kit["id"], ROBOTO, filename="Roboto.ttf")
    label, blob = text.font_sheet_parts(kit["id"])
    assert isinstance(label, str) and label.endswith(":") and len(label) > 3
    assert isinstance(blob, Blob) and blob.mime == "image/png" and blob.data[:4] == b"\x89PNG"
    rule = text.font_sheet_rule()
    assert rule and "{{" not in rule


# ── Google Fonts ────────────────────────────────────────────────────────────


def test_search_the_catalog(database):
    found = google_fonts.search("robo")
    assert found["items"][0]["family"] == "Roboto" and found["items"][0]["cyrillic"] is True
    assert found["total"] >= 2 and found["taken_at"]
    every = google_fonts.search(limit=500)
    assert len(every["items"]) == google_fonts.MAX_PAGE and every["total"] > 1000
    serif = google_fonts.search(category="serif", limit=50)
    assert serif["items"] and all(x["category"] == "serif" for x in serif["items"])
    cyrillic = google_fonts.search(cyrillic=True, limit=100)
    assert cyrillic["total"] < every["total"] and all(x["cyrillic"] for x in cyrillic["items"])
    page = google_fonts.search(offset=10, limit=5)
    assert [x["family"] for x in page["items"]] == [x["family"] for x in every["items"][10:15]]
    with pytest.raises(AppError) as e:
        google_fonts.search(category="comic")
    assert code_of(e) == "bad_request"


def test_pick_the_upright_regular_file():
    refs = [{"filename": "X-Italic[wght].ttf", "url": "u1"}, {"filename": "X[wght].ttf", "url": "u2"},
            {"filename": "static/X-Bold.ttf", "url": "u3"}, {"filename": "static/X-Regular.ttf", "url": "u4"}]
    assert google_fonts.pick_file(refs)["url"] == "u4"
    assert google_fonts.pick_file(refs[:3])["url"] in ("u2", "u3")
    assert google_fonts.pick_file([{"filename": "OFL.txt", "url": "u"}]) is None


async def test_add_a_google_font_to_a_kit(database, fake):
    kit = kits.create_kit("Cafe")
    asset = await text.add_google_font(kit["id"], "lobster")
    assert asset["font"]["google_family"] == "Lobster" and asset["font"]["source"] == "google"
    assert asset["font"]["category"] == "display" and asset["file_id"]
    assert files.read_bytes(asset["file_id"]) == ROBOTO
    assert db.get("files", asset["file_id"])["mime"] == "font/ttf"
    assert fake.seen == [(google_fonts.LIST_URL, {"family": "Lobster"}), (FILE_URL, None)]
    assert F.font_path(asset["file_id"])                         # the renderer can use it
    assert text.ensure_font_sheet(kit["id"])["drawn"] == 1       # and the specimen too

    with pytest.raises(AppError) as e:
        await text.add_google_font(kit["id"], "Lobster")
    assert code_of(e) == "font_in_kit"

    other = kits.create_kit("Bakery")
    await text.add_google_font(other["id"], "Lobster")
    assert len(fake.seen) == 2                                    # the second kit used the cached file

    with pytest.raises(AppError) as e:
        await text.add_google_font(other["id"], "No Such Font")
    assert code_of(e) == "not_found"
    with pytest.raises(AppError) as e:
        await text.add_google_font(99999, "Lobster")
    assert code_of(e) == "not_found"
    with pytest.raises(AppError) as e:
        await text.add_google_font(None, "Lobster")
    assert code_of(e) == "bad_request"


async def test_only_files_from_fonts_gstatic_are_downloaded(database, monkeypatch):
    fake = FakeGoogle(url="https://example.com/Lobster-Regular.ttf")
    monkeypatch.setattr(google_fonts, "fetch", fake)
    kit = kits.create_kit("Cafe")
    with pytest.raises(AppError) as e:
        await text.add_google_font(kit["id"], "Lobster")
    assert code_of(e) == "font_download_failed" and e.value.status == 502
    assert len(fake.seen) == 1
    assert db.fetch_all("SELECT id FROM brand_assets WHERE kit_id = ?", (kit["id"],)) == []


async def test_a_file_that_is_not_a_font_is_refused(database, monkeypatch):
    monkeypatch.setattr(google_fonts, "fetch", FakeGoogle(data=b"<html>nope</html>"))
    kit = kits.create_kit("Cafe")
    with pytest.raises(AppError) as e:
        await text.add_google_font(kit["id"], "Lobster")
    assert code_of(e) == "font_unreadable"
    assert db.fetch_all("SELECT id FROM brand_assets WHERE kit_id = ?", (kit["id"],)) == []


def test_font_routes(api, fake):
    kit = kits.create_kit("Cafe")
    r = api.post("/api/text/fonts/google/add", json={"kit_id": kit["id"], "family": "Lobster"})
    assert r.status_code == 200 and r.json()["asset"]["font"]["google_family"] == "Lobster"
    r = api.post("/api/text/fonts/google/add", json={"kit_id": kit["id"], "family": "Lobster"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "font_in_kit"
    r = api.get("/api/text/font-sheet", params={"kit_id": kit["id"]})
    assert r.status_code == 200 and r.json()["file_id"] and r.json()["url"]
    r = api.get("/api/text/fonts/google", params={"q": "lob", "cyrillic": True})
    assert r.json()["items"][0]["family"] == "Lobster"
