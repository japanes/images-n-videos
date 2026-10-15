# render

ffmpeg behind a small HTTP API. Only the `app` container talks to it, at
`http://render:3000` (`VF_RENDER_URL`); the port is never published to the host.
Node 22, plain `node:http`, no runtime dependencies.

Every path in a request or a response is **relative to the data volume**
(`VF_DATA_DIR`, `/data` in the image), e.g. `files/2026/10/clip.mp4`.

## Run and test

```sh
docker build -t vf-dev/render:dev render
# the whole suite against the ffmpeg that ships in the image (Debian bookworm, 5.1)
docker run --rm -v "$PWD/tmp/render/data:/data" vf-dev/render:dev npm test

# on a host with Node 22+ and ffmpeg on PATH (data goes to ../tmp/render/data)
cd render && npm ci && npm test && npm run lint
```

The tests make their media with ffmpeg's built-in generators, start the API on
a random local port and go through HTTP. Each test file gets its own folder
`test-<name>/` under the data dir; it is wiped at the start of the next run, not
at the end, so a failure can be looked at.

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `VF_DATA_DIR` | `/data` | The shared data volume. |
| `VF_VERSION` | `0.0.0-dev` | Reported by `/health`. |
| `HOST` / `PORT` | `0.0.0.0` / `3000` | Listen address inside the compose network. |
| `RENDER_CONCURRENCY` | `2` | Queued jobs that run at once (1–16). |
| `RENDER_JOB_TTL_MS` | `3600000` | How long a finished job stays at `GET /jobs/:id`. |
| `RENDER_FFMPEG_TIMEOUT_MS` | `1800000` | Hard limit for one ffmpeg process. |
| `RENDER_LOG_LEVEL` | `info` | `info`, `warn`, `error` or `silent`. |

Logs are JSON lines on stdout (`docker compose logs render`), one per request
and per job start/end, each with `batch_id`. Health checks and job polls are not
logged unless they fail. Subtitle text, file contents and the environment are
never logged.

## Paths

- Read (`input`, `image`, `inputs`, `anchors`, `subtitles_path`, `fonts`, track
  inputs): any regular file inside the data dir **except** `secrets/`,
  `backups/`, `app.db*` and `cache/render/`. Symlinks are resolved first; one
  that leads outside or into those places is refused.
- Write (`output`, `poster_output`, …): only under `files/` or `cache/`, not
  `cache/render/`. Missing folders are created. An existing file is replaced in
  one step (written to scratch, then renamed into place), so a reader never sees
  half a file.
- Absolute paths, `..`, backslashes and NUL are a `400`.
- Work happens in `cache/render/<job id>/`, removed when the job ends however it
  ends; leftovers from a crash are swept at start and every 5 minutes.
- Brand fonts: font files (`.ttf .otf .ttc .woff .woff2`) in `<data>/fonts/`
  and up to two levels of subfolders (at most 200) are always available to
  subtitles.

## Encoding

Video: H.264 (`libx264 -preset veryfast -crf 20`), `yuv420p`, `+faststart`.
Audio: AAC 192 kbit/s, 48 kHz. Every op that changes the picture re-encodes
(trim too: a stream copy would snap the cut to a keyframe up to ~1.5 s away).
Video outputs must end in `.mp4`.

## API

Errors always look like this, for every route and inside a failed job:

```json
{ "error": { "code": "bad_request", "message": "output must end with .mp4", "stderr_tail": null } }
```

| Status | `code` | When |
|---|---|---|
| 400 | `bad_request` | Wrong or missing field, forbidden path, bad JSON. |
| 404 | `not_found` | Input file, route or job does not exist. |
| 405 | `method_not_allowed` | Known route, wrong method. |
| 500 | `ffmpeg_failed` | ffmpeg/ffprobe exited with an error; `stderr_tail` is the last ≤ 2000 chars of its output. |
| 500 | `internal` | Anything else. |

Requests may carry `X-Batch-Id` (letters, digits, `_ . : -`, up to 128 chars;
anything else becomes `_`). It is echoed in the response header, stored on the
job and written on every log line.

Every result that describes a media file uses the `probe` shape below as `meta`.

### GET /health

```json
{ "ok": true, "version": "0.4.0", "ffmpeg": "5.1.9-0+deb12u1", "queue": { "running": 1, "queued": 0 } }
```

`503` with `ok: false` and `error` when ffmpeg is missing or the data dir is not
writable.

### Answered inline (200)

**POST /probe** `{ "input": "files/2026/10/clip.mp4" }`

```json
{ "duration": 8.0, "width": 1280, "height": 720, "fps": 24, "has_video": true, "has_audio": true,
  "video_codec": "h264", "audio_codec": "aac", "size_bytes": 4120345, "bitrate": 4120345,
  "rotation": 0, "display_width": 1280, "display_height": 720 }
```

`display_*` is the upright size of a rotated phone clip. Audio files have
`width`/`height`/`fps` = `null`.

**POST /frame** — one JPEG.

```json
{ "input": "files/2026/10/clip.mp4", "output": "cache/tmp/last.jpg", "at": "last", "max_width": 1280 }
```

`at`: seconds, `"first"` (default) or `"last"`; a second past the end gives the
last frame. → `{ "output", "width", "height", "at" }`.

**POST /match** — at what second a clip comes closest to a still (SSIM on
160×160 grey frames). Used to stitch extensions on their shared frame.

```json
{ "input": "files/2026/10/scene-2.mp4", "image": "files/2026/10/scene-1-last.jpg", "window": "head", "seconds": 2 }
```

`window`: `head`, `tail` or `all` (default); `seconds` 0.2–30 (default 2, capped
at half the clip for head/tail); `fps` defaults to the clip's, max 30.
→ `{ "at": 0.52, "score": 0.98, "frames": 50, "window": "head", "window_start": 0, "window_seconds": 2, "duration": 8 }`.
`score` 0 means nothing was scored.

### Queued (202)

`POST /<op>` validates everything first (a bad path is a `400`/`404` right
away, nothing is queued) and answers `202 { "job_id": "…" }`. Jobs run in
arrival order, `RENDER_CONCURRENCY` at a time.

**GET /jobs/:id**

```json
{ "id": "8289af19-…", "op": "trim", "status": "done", "progress": 1,
  "result": { "output": "files/2026/10/cut.mp4", "meta": { "duration": 1.52, "…": "…" } },
  "error": null, "batch_id": "clip-42",
  "created_at": "2026-10-15T18:45:20.195Z", "started_at": "2026-10-15T18:45:20.196Z", "finished_at": "2026-10-15T18:45:20.491Z" }
```

`status`: `queued` → `running` → `done` | `error` | `cancelled`. `progress` is
0–1 and never goes back. `result` is set only on `done`, `error` only on
`error`. Finished jobs are forgotten after `RENDER_JOB_TTL_MS` (then `404`).

**DELETE /jobs/:id** — cancel. A queued job never starts; a running one has its
ffmpeg killed and its scratch removed, and nothing is written to `output`.
Answers the job. On a finished job it changes nothing.

#### preview — poster, hover loop, thumbnails

```json
{ "input": "files/2026/10/clip.mp4",
  "poster_output": "cache/thumbs/clip.jpg", "preview_output": "cache/thumbs/clip.webp",
  "thumbs": [{ "width": 160, "output": "cache/thumbs/clip-160.jpg" }] }
```

At least one of the three outputs. Options: `poster_width` 720, `poster_at`
(default 10% of the clip, at most 1 s), `segments` 4, `segment_seconds` 0.6,
`width` 320, `fps` 12, `quality` 55 (WebP). → `{ "poster": {output, width,
height, size_bytes, at}, "preview": {output, width, height, size_bytes,
segments}, "thumbs": [...], "source": meta }` (missing outputs are `null`/`[]`).

#### trim — keep one stretch

`{ "input", "output", "start": 1.5, "end": 6 }` (`start` default 0, `end`
default the end). → `{ "output", "meta" }`.

#### split — cut into pieces

`{ "input", "at": [3, 7.5], "outputs": ["files/a.mp4", "files/b.mp4", "files/c.mp4"] }`
— `outputs` has one more entry than `at`. → `{ "outputs": [{ "output", "meta" }, …] }`.

#### crop — reframe

```json
{ "input": "files/2026/10/clip.mp4", "output": "files/2026/10/clip-916.mp4", "aspect": "9:16", "mode": "blur" }
```

Target: `aspect` (`9:16` 1080×1920, `1:1` 1080×1080, `16:9` 1920×1080, `4:5`
1080×1350) or `width`+`height` (even, 16–4096), and/or `rect` `{x, y, width,
height}` cut first, in upright pixels. `mode`: `cover` (fill and cut, default),
`pad` (bars of `pad_color` `#RRGGBB`), `blur` (bars of a blurred copy).
→ `{ "output", "meta" }`.

#### burn — overlays and subtitles into the picture

```json
{ "input": "files/2026/10/clip.mp4", "output": "files/2026/10/clip-subs.mp4",
  "overlays": [{ "image": "files/brand/logo.png", "x": 40, "y": 40, "width": 200, "opacity": 0.8, "start": 0, "end": 3 }],
  "subtitles_ass": "[Script Info]\n…", "fonts": ["files/brand/Brand-Bold.ttf"] }
```

`overlays` (up to 32): `image` PNG/JPEG/WebP, `x`/`y`, `width`/`height` (one
may be left out to keep the aspect), `opacity` 0–1, `start`/`end` seconds.
Subtitles: ready ASS as `subtitles_ass` (text, ≤ 1 MB) **or** `subtitles_path`
(`.ass` file). Fonts in the image: DejaVu Sans/Serif/Mono and Liberation
Sans/Serif/Mono (Cyrillic incl. Ukrainian; "Arial", "Helvetica", "Times New
Roman" resolve to Liberation). Other fonts: put them under `<data>/fonts/` or
list them in `fonts`. Sound is passed through. → `{ "output", "meta" }`.

#### mix — audio tracks over a video

```json
{ "input": "files/2026/10/clip.mp4", "output": "files/2026/10/clip-mixed.mp4", "original_volume": 0.3,
  "tracks": [
    { "input": "files/2026/10/voice.mp3", "role": "voice", "delay": 0.5 },
    { "input": "files/music/bed.mp3", "role": "music", "volume": 0.6, "fade_in": 1, "fade_out": 2, "duck": true }
  ] }
```

Per track: `volume` 0–4 (1), `delay` s, `fade_in` s, `fade_out` s (ends at the
video's end unless `fade_out_at` says when it starts), `role` `voice` | `music`
| `sfx`, `duck` (pushed down while the one `voice` track speaks;
`duck_threshold` 0.03, `duck_ratio` 8). `keep_original_audio` true,
`original_volume` 1. The result is exactly as long as the video. → `{ "output",
"meta" }`.

#### split-audio — parts for speech recognition

`{ "input": "files/2026/10/interview.mp4", "output_dir": "cache/tmp/stt-42", "max_mb": 20 }`

Mono 16 kHz MP3 parts `part-000.mp3`, `part-001.mp3`, … each starting at 0 s.
`bitrate_kbps` 64; part length from `max_mb`, or `chunk_seconds` (5–3600).
→ `{ "outputs": [{ "output", "meta" }, …], "chunk_seconds": 2359, "duration": 5400.2 }`.

#### concat — join clips

```json
{ "inputs": ["files/s1.mp4", "files/s2.mp4", "files/s3.mp4"], "output": "files/film.mp4",
  "transition": "align", "anchors": ["files/s1-last.jpg", "files/s2-last.jpg"] }
```

Frame: `aspect` or `width`+`height`, default the first clip's upright size;
clips are scaled to cover it. `fps`: default the clips' shared rate, else 30.
Clips without sound get silence. `transition`:

- `crossfade` (default) — dissolve of `transition_seconds` (0.3).
- `cut` — hard join.
- `align` — `anchors[j]` is the still shared by clip j and j+1; the end of one
  and the start of the next are searched (`align_search` 2 s) and both are cut
  on their best frame, joined with a dissolve of `align_seconds` (0 = cut). A
  join whose still is missing, unreadable or scores under `align_min_score`
  (0.45) falls back to the crossfade; a `null` anchor means a real cut.

→ `{ "output", "meta", "joins": [{ "join": 0, "aligned": true, "reason": null, "out_at": 7.96, "out_score": 0.97, "into_at": 0.04, "into_score": 0.96 }, …] }`
(`joins` is empty unless `align`).

#### compose — several edits, one job

`{ "input" | "concat": {…}, "output", "trim": {…}, "crop": {…}, "burn": {…}, "mix": {…} }`

Each step takes the fields of the op of the same name without `input`/`output`
and runs in the fixed order concat → trim → crop → burn → mix. With `concat`,
`input` is not allowed. Only the final file appears on the volume.
→ `{ "output", "meta", "steps": ["concat", "burn"], "joins": [...] }` (`joins`
only with `concat`).
