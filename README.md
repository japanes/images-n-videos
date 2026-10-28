# Vertex AI Factory

Make images and videos with Google models (Gemini, Veo) in the browser.
The app runs in Docker on your server. You connect your own Google Cloud
service account key; new Google Cloud accounts get a free trial credit that
pays for the generations.

The key and the files stay on the server where the app runs; requests go
straight from it to Google.

## What it does

- Chat-style studio: write what you want, attach photos, get images or video
  as messages. Reply to a picture to edit it, reply to a video to continue it.
- Avatars: one person kept the same across many pictures.
- Shot ideas, text on images, brand kits, photo styles to pick from.
- A simple video editor with subtitles (speech is recognised on the server, free).
- A media library and a spending journal: every paid Google call is recorded
  with its model, amount and price. Paid buttons show the price before you click.
- Interface in English, Ukrainian and Russian.

## What you need

- A Linux server (amd64 or arm64) with Docker and the Compose plugin.
- About 4 GB of free memory (RAM) and 5 GB of disk space.
  Subtitles need about 1.6 GB more; the speech model downloads the first time
  they are turned on.
- A domain name pointing to the server, for HTTPS.
- A Google Cloud account. The app's setup screen walks you through creating
  the service account key step by step.

## Install

```sh
git clone https://github.com/japanes/images-n-videos.git
cd images-n-videos
VF_GOOGLE_MODE=live VF_ALLOWED_HOSTS=studio.example.com \
  docker compose -f docker-compose.dev.yml up -d --build
```

The first build takes 5–20 minutes. The app then listens on
`127.0.0.1:8787` of the server only.

**The app has no login of its own.** Put a reverse proxy in front of it that
adds HTTPS and a password, for example Caddy:

```
studio.example.com {
    basic_auth {
        # caddy hash-password --plaintext 'your password'
        me $2a$14$...
    }
    reverse_proxy 127.0.0.1:8787
}
```

`VF_ALLOWED_HOSTS` lists the names the app is opened under (comma-separated);
requests for any other name are refused.

## Update, stop, remove

- **Update:** `git pull`, then the same `docker compose ... up -d --build`.
  Data lives in the `vertexai-factory-dev-data` Docker volume and is kept.
- **Stop:** `docker compose -f docker-compose.dev.yml down`. Files, settings
  and the key are kept.
- **Port 8787 is busy:** start with `VF_PORT=8788` (and point the proxy there).
- **Remove with data:** `docker compose -f docker-compose.dev.yml down -v`.

## Privacy and security

- The app listens on `127.0.0.1` of the server only; it is reached through
  your reverse proxy.
- The Google key is stored in the app's Docker volume. It is sent only to
  Google, never written to logs and never shown back in full.
- No telemetry, no analytics. The app itself goes online only to Google
  (generation) and Hugging Face (the subtitle model, once).
- Requests from other web sites open in the browser are refused: the app
  answers only to its own host names, and anything that changes data must come
  from the app's own page.

## For developers

The same compose file starts a local copy with Google calls faked
(`VF_GOOGLE_MODE=stub`, the default):

```sh
docker compose -f docker-compose.dev.yml up --build
```

It opens on <http://127.0.0.1:8787>.

| Service | What it is |
|---|---|
| `app/` | FastAPI (Python 3.12), SQLite, serves the built web UI |
| `web/` | Nuxt 3 single-page app |
| `render/` | Node 22 + ffmpeg, video assembly |
| `stt/` | faster-whisper, local speech recognition for subtitles |

Checks run in containers, nothing to install but Docker:

```sh
scripts/test-app.sh          # ruff + pytest
scripts/test-web.sh --build  # eslint + vitest + nuxt generate
scripts/smoke.sh 8787        # quick check of a running stack
```

Prompts sent to the models live in `app/prompts/` as versioned files; the model
list and prices are data (`app/seeds/models.json`), not code.
