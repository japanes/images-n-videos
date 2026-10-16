"""Module 04 (image studio): picture helpers and the answer of "find objects"."""

import io

import pytest
from PIL import Image

from vf.modules.studio import imaging
from vf.modules.studio.objects import normalize_objects


def png(size=(100, 80), color=(20, 120, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def size_of(data: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(data)) as im:
        return im.size


# ── fitting the answer to the frame ─────────────────────────────────────────


def test_fit_exact_keeps_the_bytes():
    fit = imaging.fit_to_frame(png((120, 150)), 120, 150)
    assert fit.image is None and fit.how == "exact"


def test_fit_without_base_stretches():
    fit = imaging.fit_to_frame(png((928, 1152)), 1080, 1350)
    assert fit.how == "stretched" and size_of(fit.image) == (1080, 1350)


def test_fit_on_base_completes_the_sliver_from_the_base():
    base = png((100, 100), color=(255, 0, 0))
    answer = png((99, 100), color=(0, 0, 255))     # 1% narrower: within the allowed drift
    fit = imaging.fit_to_frame(answer, 100, 100, base)
    assert fit.how == "fitted" and size_of(fit.image) == (100, 100)
    with Image.open(io.BytesIO(fit.image)) as im:
        assert im.convert("RGB").getpixel((50, 50)) == (0, 0, 255)


def test_fit_on_base_stretches_when_the_shape_is_too_different():
    fit = imaging.fit_to_frame(png((200, 100)), 100, 100, png((100, 100)))
    assert fit.how == "stretched"


def test_aspect_target_keeps_the_width():
    assert imaging.aspect_target(2048, 2000, "4:5") == (2048, 2560)
    assert imaging.aspect_target(1376, 770, "16:9") == (1376, 774)


# ── the marked copy and the place in words ──────────────────────────────────


def test_marked_copy_draws_a_magenta_frame_around_the_box():
    data = imaging.marked_copy(png((200, 200), color=(255, 255, 255)), {"x": 0.25, "y": 0.25, "w": 0.5, "h": 0.5})
    assert data is not None
    with Image.open(io.BytesIO(data)) as im:
        im = im.convert("RGB")
        assert im.size == (200, 200)
        assert im.getpixel((100, 100)) == (255, 255, 255)        # inside stays as it was
        edge = {im.getpixel((x, 100)) for x in range(40, 52)}
        assert imaging.MARKER_COLOUR in edge


@pytest.mark.parametrize("box", [None, {}, {"x": 0, "y": 0, "w": 0, "h": 0.5}, "box"])
def test_marked_copy_nothing_to_draw(box):
    assert imaging.marked_copy(png(), box) is None


def test_marked_copy_on_bytes_that_are_not_a_picture():
    assert imaging.marked_copy(b"not a picture", {"x": 0, "y": 0, "w": 1, "h": 1}) is None


def test_area_words():
    words = imaging.area_words({"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4})
    assert "between 10% and 40% from the left edge" in words
    assert "between 20% and 60% from the top edge" in words
    assert "about 12%" in words
    assert "less than 1%" in imaging.area_words({"x": 0, "y": 0, "w": 0.05, "h": 0.05})


def test_shrink_makes_a_small_jpeg():
    data, mime = imaging.shrink(png((3000, 1500)), "image/png")
    assert mime == "image/jpeg" and max(size_of(data)) == 1024


# ── the answer of "find objects" ────────────────────────────────────────────


def test_normalize_objects_list_with_box_2d():
    items = normalize_objects([
        {"label": "Red cup", "box_2d": [100, 150, 700, 850]},
        {"label": "Red cup", "box_2d": [0, 0, 500, 500]},
        {"label": "no box"},
        "junk",
    ])
    assert [i["id"] for i in items] == ["red-cup", "red-cup-2"]
    box = items[0]["box"]
    assert box == pytest.approx({"x": 0.15, "y": 0.1, "w": 0.7, "h": 0.6})


@pytest.mark.parametrize("key", ["objects", "regions", "items", "layers"])
def test_normalize_objects_dict_keys(key):
    items = normalize_objects({key: [{"name": "Lamp", "bbox": [0, 0, 1000, 1000]}]})
    assert items == [{"id": "lamp", "label": "Lamp", "box": pytest.approx({"x": 0, "y": 0, "w": 1, "h": 1})}]


def test_normalize_objects_ids_without_label_and_limit():
    items = normalize_objects([{"box": [0, 0, 10, 10]} for _ in range(40)])
    assert len(items) == 24
    assert items[0]["id"] == "r1" and items[1]["id"] == "r2"
    assert normalize_objects("nothing") == [] and normalize_objects({"other": []}) == []
