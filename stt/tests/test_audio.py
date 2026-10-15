from __future__ import annotations

import threading

import numpy as np
import pytest
from conftest import tone, write_video, write_wav

from stt.audio import SAMPLE_RATE, decode_audio
from stt.errors import Cancelled, ServiceError


def test_wav_mono_16k(tmp_path):
    audio = decode_audio(write_wav(tmp_path / "a.wav", 2.0))
    assert audio.dtype == np.float32
    assert audio.shape == (2 * SAMPLE_RATE,)
    assert 0.2 < float(np.abs(audio).max()) < 0.3  # 8000 / 32768


def test_wav_stereo_44k_is_resampled(tmp_path):
    progress = []
    audio = decode_audio(
        write_wav(tmp_path / "a.wav", 2.0, rate=44100, channels=2),
        on_progress=progress.append,
    )
    assert abs(audio.shape[0] - 2 * SAMPLE_RATE) <= 32
    assert progress[-1] == 1.0
    assert progress == sorted(progress)


def test_video_with_audio(tmp_path):
    path = write_video(tmp_path / "v.mp4", tone(2.0), 2.0)
    audio = decode_audio(path)
    assert abs(audio.shape[0] - 2 * SAMPLE_RATE) < 3000
    assert float(np.abs(audio).max()) > 0.1


def test_long_audio_is_batched(tmp_path):
    # More than BATCH_SAMPLES input samples so the fifo is flushed mid-way.
    audio = decode_audio(write_wav(tmp_path / "a.wav", 40.0))
    assert audio.shape == (40 * SAMPLE_RATE,)


def test_video_without_audio(tmp_path):
    path = write_video(tmp_path / "v.mp4", None, 1.0)
    with pytest.raises(ServiceError) as exc:
        decode_audio(path)
    assert exc.value.code == "no_audio"


def test_empty_audio_track(tmp_path):
    path = write_wav(tmp_path / "a.wav", 0.0)
    with pytest.raises(ServiceError) as exc:
        decode_audio(path)
    assert exc.value.code in {"no_audio", "transcribe_failed"}


@pytest.mark.parametrize("data", [b"", b"not a media file at all" * 50])
def test_garbage(tmp_path, data):
    path = tmp_path / "x.mp3"
    path.write_bytes(data)
    with pytest.raises(ServiceError) as exc:
        decode_audio(path)
    assert exc.value.code == "transcribe_failed"


def test_network_playlist_is_not_followed(tmp_path):
    path = tmp_path / "list.m3u8"
    path.write_text("#EXTM3U\n#EXTINF:1,\nhttp://127.0.0.1:9/a.wav\n#EXT-X-ENDLIST\n")
    with pytest.raises(ServiceError) as exc:
        decode_audio(path)
    assert exc.value.code in {"transcribe_failed", "no_audio"}


def test_stop(tmp_path):
    stop = threading.Event()
    stop.set()
    with pytest.raises(Cancelled):
        decode_audio(write_wav(tmp_path / "a.wav", 1.0), stop)
