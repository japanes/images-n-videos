"""Module 12: the edit list of a clip — cleaning, time arithmetic, sizes."""

from vf.modules.clip import state as st


def test_empty_state_shape():
    s = st.empty_state()
    assert s["trim"] == {"start": 0.0, "end": None}
    assert s["cuts"] == [] and s["removed"] == [] and s["layers"] == []
    assert s["crop"] == {"aspect": "", "mode": "cover"}
    assert s["subtitles"]["enabled"] is False and s["subtitles"]["preset_code"] == "clean"
    assert s["audio"] == {"keep_original": True, "original_volume": 1.0, "tracks": []}


def test_normalize_clamps_and_drops_bad_values():
    raw = {
        "trim": {"start": -5, "end": 100},
        "cuts": [3, 3.01, "x", 0.01, 9.99, 5],
        "removed": [[4, 2], [3, 3.5], [8, 8.001], "bad"],
        "crop": {"aspect": "3:2", "mode": "blur"},
        "layers": [
            {"type": "text", "text": "Hi", "x": 2, "size": 9, "color": "zz"},
            {"type": "image"},  # no file -> dropped
            {"type": "video", "file_id": 1},  # unknown type -> dropped
            {"type": "image", "file_id": "7", "opacity": -1},
        ],
        "audio": {"original_volume": 9, "tracks": [
            {"file_id": 1, "role": "voice"}, {"file_id": 2, "role": "voice"}, {"file_id": None},
            {"file_id": 3, "role": "drums", "volume": 2.5, "fade_in": 99},
        ]},
    }
    s = st.normalize(raw, 10.0)
    assert s["trim"] == {"start": 0.0, "end": None}  # end past the video means "to the end"
    assert s["cuts"] == [3.0, 5.0]  # too close to each other or to the ends -> dropped
    assert s["removed"] == [[2.0, 4.0]]
    assert s["crop"] == {"aspect": "", "mode": "blur"}
    text, image = s["layers"]
    assert text["x"] == 1.0 and text["size"] == 0.3 and text["color"] == "#FFFFFF"
    assert image["file_id"] == 7 and image["opacity"] == 0.0
    tracks = s["audio"]["tracks"]
    assert [t["role"] for t in tracks] == ["voice", "sfx", "music"]  # one voice only
    assert tracks[2]["volume"] == 2.5 and tracks[2]["fade_in"] == 30.0
    assert s["audio"]["original_volume"] == 4.0


def test_short_trim_is_widened():
    s = st.normalize({"trim": {"start": 5, "end": 5.01}}, 10)
    assert s["trim"]["end"] - s["trim"]["start"] >= st.MIN_CLIP_S - 1e-9


def test_words_cleaned_and_sorted():
    words = st.normalize_words([{"word": " b ", "start": 2, "end": 1}, {"text": "a", "start": 1, "end": 1.5},
                                {"text": ""}, "x", {"text": "c", "start": "bad"}])
    assert words == [{"text": "a", "start": 1.0, "end": 1.5}, {"text": "b", "start": 2.0, "end": 2.06}]


def test_segments_and_mapping():
    s = st.normalize({"trim": {"start": 1, "end": 9}, "removed": [[3, 4], [6, 7]], "cuts": [5]}, 10)
    segs = st.segments(s, 10)
    assert segs == [(1.0, 3.0), (4.0, 6.0), (7.0, 9.0)]
    assert st.output_duration(segs) == 6.0
    assert st.to_output(4.5, segs) == 2.5
    assert st.to_output(3.5, segs) is None
    assert st.map_range(2, 8, segs) == [(1.0, 5.0)]  # joined over the removed pieces
    words = [{"text": "a", "start": 2.5, "end": 3.6}, {"text": "cut", "start": 3.2, "end": 3.4},
             {"text": "b", "start": 7.5, "end": 8}]
    assert st.map_words(words, segs) == [{"text": "a", "start": 1.5, "end": 2.0},
                                         {"text": "b", "start": 4.5, "end": 5.0}]
    assert st.part_points(s, segs) == [3.0]


def test_nothing_left():
    s = st.normalize({"removed": [[0, 10]]}, 10)
    assert st.segments(s, 10) == []


def test_output_size():
    src = {"width": 1920, "height": 1080}
    plain = st.normalize({}, 10)
    assert st.output_size(plain, src) == (1920, 1080)
    assert st.output_size(plain, src, preview=True, preview_max=960) == (960, 540)
    vertical = st.normalize({"crop": {"aspect": "9:16"}}, 10)
    assert st.output_size(vertical, src) == (1080, 1920)
    assert st.output_size(vertical, src, preview=True, preview_max=960) == (540, 960)
    odd = {"width": 721, "height": 405}
    assert st.output_size(plain, odd) == (720, 404)


def test_referenced_files():
    s = st.normalize({
        "layers": [{"type": "image", "file_id": 4}, {"type": "text", "text": "x", "font_file_id": 5}],
        "audio": {"tracks": [{"file_id": 6}]},
    }, 10)
    assert st.referenced_files(s) == {"images": [4], "fonts": [5], "tracks": [6]}
