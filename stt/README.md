# stt — local speech-to-text

Speech recognition for the clip editor's subtitles. Runs
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) on the CPU (int8), so
it costs nothing and needs no GPU. Nothing is sent anywhere except the one-time
model download from Hugging Face; after that it works offline.

- FastAPI + uvicorn on port **8000**, never published to the host: the `app`
  service calls `http://stt:8000` on the compose network.
- Shares the data volume with `app` at `/data` (`VF_DATA_DIR`). Inputs are paths
  relative to it; models live in `/data/models/`.
- Models are **not** in the image. One is downloaded the first time it is
  needed (or on `POST /models/download`) and can be deleted again.
- One transcription at a time; a second request gets `409 busy`.

## Models

| name | size | Hugging Face repo @ pinned revision |
|---|---|---|
| `large-v3-turbo` (default) | 1622 MB | `dropbox-dash/faster-whisper-large-v3-turbo` @ `0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf` |
| `small` | 486 MB | `Systran/faster-whisper-small` @ `536b0662742c02347bc0e980a01041f333bce120` |

The list, file sizes and checksums are data in `stt/registry.py`. Every file is
checked for exact size and checksum (sha256 for the weights, git blob sha1 for
the small JSON/text files) before the model counts as downloaded. `size_mb` is
decimal megabytes (1 MB = 1,000,000 bytes) of all files.

## Configuration (environment)

| variable | default | meaning |
|---|---|---|
| `VF_DATA_DIR` | `/data` | shared data dir; inputs are relative to it, models go to `<dir>/models` |
| `VF_VERSION` | `0.0.0-dev` | reported by `/health` (set at image build: `--build-arg VF_VERSION=…`) |
| `STT_CPU_THREADS` | `0` | CPU threads for Whisper; `0` = every CPU the container may use |
| `STT_IDLE_UNLOAD_S` | `600` | free the loaded model after this many idle seconds; `0` = keep it |
| `HF_ENDPOINT` | `https://huggingface.co` | where models are downloaded from (mirror support) |

## API

All bodies are JSON. Unknown fields in a request body are rejected (`400`).
Every error has the same shape:

```json
{"error": {"code": "busy", "message": "another transcription is running"}}
```

| code | HTTP | when |
|---|---|---|
| `bad_request` | 400 | invalid JSON or field, bad `language`, `input` absolute / with `..` / outside the data dir / inside `secrets/` or `models/` |
| `not_found` | 404 | `input` file does not exist (or is a directory); unknown route |
| `model_not_found` | 404 | `model` / `name` is not in the registry |
| `busy` | 409 | a transcription is already running; deleting a model that is in use |
| `no_audio` | 422 | the file has no audio track, or it is empty |
| `download_failed` | 502 | model download failed (network, HTTP error, checksum, disk full); the text says why |
| `transcribe_failed` | 500 | the file cannot be decoded, or Whisper failed |
| `internal_error` | 500 | anything unexpected |

### `GET /health`

```json
{"ok": true, "version": "0.0.0-dev", "busy": false}
```

`busy` is true while a transcription runs. Used by the Docker `HEALTHCHECK`.

### `GET /models`

Always lists every model of the registry, in this order:

```json
[
  {"name": "large-v3-turbo", "size_mb": 1622, "downloaded": false, "downloading": true,
   "progress": 0.4127, "error": null},
  {"name": "small", "size_mb": 486, "downloaded": true, "downloading": false,
   "progress": null, "error": null}
]
```

- `progress` is 0..1 while `downloading`, otherwise `null`.
- `error` is the text of the last failed download (until the next attempt or a
  delete), otherwise `null`.
- An interrupted download is resumed from where it stopped next time.

### `POST /models/download`

```json
{"name": "large-v3-turbo"}
```

- `202` + the model's status (as in `/models`): download started in the
  background, or was already running. Poll `GET /models` for progress.
- `200` + status: already downloaded, nothing to do.
- `404 model_not_found`.

Free disk space is checked first (download size + 64 MB); a failed download
shows up as `error` in `/models`.

### `DELETE /models/{name}`

Removes the model and any partial download; cancels a running download of it;
frees it from memory. Idempotent. Returns `200` + the new status
(`downloaded: false`). `409 busy` while a transcription uses that model.

### `POST /transcribe`

```json
{
  "input": "media/2026/10/clip-42.m4a",
  "model": "large-v3-turbo",
  "language": "auto",
  "word_timestamps": true
}
```

| field | type | default | notes |
|---|---|---|---|
| `input` | string | required | path relative to the data dir; any audio **or video** file FFmpeg can read (only the first audio track is used) |
| `model` | string | `large-v3-turbo` | a name from `/models`; downloaded first if missing (the request then waits for it) |
| `language` | string | `auto` | `auto`, `ru`, `uk` or `en` |
| `word_timestamps` | bool | `true` | `false` → `words` arrays are empty (a bit faster) |

The call is **synchronous**: the response comes when the text is ready, which
can take minutes for long audio (plus the model download on first use). The
caller needs a long read timeout and should show `GET /progress` meanwhile. If
the caller disconnects, the transcription stops (after the current ~30 s
window) and the slot is freed.

Response `200` (shaped like OpenAI `whisper-1` `verbose_json` with word
timestamps, so the subtitle code from factory reads it unchanged):

```json
{
  "task": "transcribe",
  "language": "en",
  "duration": 11.0,
  "text": "And so my fellow Americans, ask not what your country can do for you, ask what you can do for your country.",
  "segments": [
    {
      "id": 0,
      "start": 0.0,
      "end": 10.94,
      "text": "And so my fellow Americans, ask not what your country can do for you, ask what you can do for your country.",
      "words": [
        {"word": "And", "start": 0.0, "end": 0.32, "probability": 0.6831},
        {"word": "so", "start": 0.32, "end": 0.58, "probability": 0.9862}
      ]
    }
  ],
  "words": [
    {"word": "And", "start": 0.0, "end": 0.32, "probability": 0.6831},
    {"word": "so", "start": 0.32, "end": 0.58, "probability": 0.9862}
  ],
  "model": "large-v3-turbo"
}
```

- Times are seconds (3 decimals); `duration` is the decoded audio length.
- `language` is the ISO code (`en`, `ru`, `uk`, …) — the detected one for
  `auto`. (OpenAI returns a full name such as `english`; here it is the code.)
- `words` (top level) is all segment words in order. Word texts are trimmed
  (no leading space, unlike raw Whisper); empty words are dropped.
- `segments[].id` counts from 0. Segment fields beyond `id/start/end/text/words`
  (tokens, logprobs, …) are not returned.
- Silence (or speech-free audio) gives `200` with `text: ""` and empty lists:
  the built-in voice-activity filter (Silero VAD) removes it before Whisper.
- Decoding is fixed: `beam_size=5`, `vad_filter=true`, CPU `int8`.

Errors: `400`, `404 not_found`, `404 model_not_found`, `409 busy`,
`422 no_audio`, `502 download_failed`, `500 transcribe_failed`.

### `GET /progress`

```json
{"busy": true, "phase": "transcribing", "progress": 0.35, "model": "large-v3-turbo",
 "duration": 184.2, "elapsed_s": 41.7}
```

| `phase` | `progress` |
|---|---|
| `starting` | `null` |
| `downloading` | model download 0..1 |
| `decoding` | reading the audio 0..1 |
| `loading` | `null` (model is being loaded into memory) |
| `transcribing` | position of the last finished segment / `duration`, 0..1 (moves in steps) |

`duration` (seconds of audio) is known from `loading` on. When idle every field
except `busy: false` is `null`.

## Behaviour notes

- **Memory.** One model in memory at a time (large-v3-turbo weights are 1.6 GB
  on disk; real RAM use is not measured yet). It stays loaded between requests
  and is freed after
  `STT_IDLE_UNLOAD_S` idle seconds, on delete, or when another model is used.
- **Disk layout** under `/data/models/`: `<name>/` is a complete model (with
  `.vf-manifest.json`); `.partial-<name>/` is a download in progress or an
  interrupted one (resumed with HTTP Range); `.old-<name>-*` is cleaned up at
  start. A partial download never counts as downloaded: it is moved into place
  with one rename after every file is verified.
- **Inputs** are restricted to regular files inside the data dir (symlinks are
  resolved first) and never inside `secrets/` or `models/`. Media is opened for
  local files only: a playlist inside a file cannot make FFmpeg fetch URLs.
- **No telemetry.** The only outgoing requests are model downloads from
  `HF_ENDPOINT` (`User-Agent: vertexai-factory-stt`). The service never sees
  the Google key.

## Development

The image has no compilers and no `ffmpeg` binary: every dependency is a
prebuilt wheel for both `linux/amd64` and `linux/arm64` (PyAV bundles the FFmpeg
libraries). All versions are pinned in `requirements.txt`.

```sh
docker build -t vf-dev/stt:dev stt/

# fast tests (Whisper and Hugging Face are faked) + lint
docker run --rm -v "$PWD/stt:/src:ro" -w /src vf-dev/stt:dev sh -c \
  "pip install -q -r requirements-dev.txt && pytest -q && ruff check --no-cache . && ruff format --check --no-cache ."

# slow end-to-end test: real download of the tiny model (~78 MB) + real Whisper
mkdir -p tmp/stt/slow
docker run --rm -v "$PWD/stt:/src:ro" -v "$PWD/tmp/stt/slow:/work" -e STT_SLOW_DATA_DIR=/work \
  -w /src vf-dev/stt:dev sh -c "pip install -q -r requirements-dev.txt && pytest -m slow -q"
```

Layout: `stt/main.py` (HTTP), `stt/service.py` (the single job slot and the
result format), `stt/models.py` (download / status / delete),
`stt/engine.py` (loaded model, idle unload), `stt/audio.py` (decoding with
PyAV), `stt/paths.py` (input validation), `stt/registry.py` (models).
