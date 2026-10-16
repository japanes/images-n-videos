# Vertex AI Factory

Make images and videos with Google models (Gemini, Veo) on your own computer.
The app runs in Docker and opens in your browser. You connect your own Google
Cloud service account key; new Google Cloud accounts get a free trial credit
that pays for the generations.

There is no server of ours in between: your key and your files stay on your
machine and requests go straight to Google.

*Русский и українська: инструкция на трёх языках — в [`release/README.txt`](release/README.txt)
(она же лежит в архиве релиза).*

## What it does

- Chat-style studio: write what you want, attach photos, get images or video
  as messages. Reply to a picture to edit it, reply to a video to continue it.
- Avatars: one person kept the same across many pictures.
- Shot ideas, text on images, brand kits, a style library.
- A simple video editor with subtitles (speech is recognised locally, free).
- A media library and a spending journal: every paid Google call is recorded
  with its model, amount and price. Paid buttons show the price before you click.
- Interface in English, Ukrainian and Russian.

## What you need

- Windows 10/11 or macOS (Apple Silicon Macs work too).
- [Docker Desktop](https://www.docker.com/products/docker-desktop/).
- About 4 GB of free memory (RAM) and 5 GB of disk space.
  Subtitles need about 1.6 GB more; the speech model downloads the first time
  you turn them on.
- A Google Cloud account. The app's setup screen walks you through creating
  the service account key step by step.

## Install

1. Install Docker Desktop and start it once.
2. Download `vertexai-factory-<version>.zip` from the
   [latest release](https://github.com/japanes/images-n-videos/releases/latest)
   and unzip it into any folder, for example Documents.
3. Double-click `start.bat` (Windows) or `start.command` (Mac).
4. The first start downloads several gigabytes and can take 5–20 minutes.
   Then the app opens in your browser at <http://127.0.0.1:8787>.

**If the system does not let you open the file**

- Mac, "could not verify the developer": click "Done", open System Settings →
  Privacy & Security, click "Open Anyway" at the bottom and confirm.
  On older macOS, right-click the file and choose "Open".
- Windows, "Windows protected your PC": click "More info", then "Run anyway".

## Stop, update, uninstall

- **Stop:** double-click `stop.bat` or `stop.command`. Files, settings and the
  key are kept.
- **Updates:** the app checks this repository's releases and installs new
  versions by itself. Before an update it backs up the database; if the new
  version does not start, it brings the previous one back. When and how to
  update is set in the app.
- **Port 8787 is busy:** the folder has a hidden `.env` file with
  `VF_PORT=8787`. Change the number (for example to 8788) and start again.
- **Uninstall:** run stop; to delete your data too, run
  `docker volume rm vertexai-factory-data` in a terminal; delete the
  `ghcr.io/japanes/images-n-videos/...` images in Docker Desktop → Images;
  delete the folder.

## Privacy and security

- The app listens on `127.0.0.1` only: other computers on your network
  cannot open it.
- Your Google key is stored in the app's Docker volume on your computer. It is
  sent only to Google, never written to logs and never shown back in full.
- No telemetry, no accounts, no analytics. The app itself goes online only to
  Google (generation), GitHub (update checks) and Hugging Face (the subtitle
  model, once).
- Requests from other web sites open in your browser are refused: the app
  answers only to `localhost` / `127.0.0.1`, and anything that changes data must
  come from the app's own page.

## For developers

The whole stack builds from this repository:

```sh
docker compose -f docker-compose.dev.yml up --build
```

It opens on <http://127.0.0.1:8787> with Google calls faked
(`VF_GOOGLE_MODE=stub`); start it with `VF_GOOGLE_MODE=live` to talk to Google.

| Service | What it is |
|---|---|
| `app/` | FastAPI (Python 3.12), SQLite, serves the built web UI |
| `web/` | Nuxt 3 single-page app |
| `render/` | Node 22 + ffmpeg, video assembly |
| `stt/` | faster-whisper, local speech recognition for subtitles |
| `updater/` | checks GitHub releases and swaps versions |
| `release/` | what goes into the release zip |

Checks run in containers, nothing to install but Docker:

```sh
scripts/test-app.sh          # ruff + pytest
scripts/test-web.sh --build  # eslint + vitest + nuxt generate
```

Prompts sent to the models live in `app/prompts/` as versioned files; the model
list and prices are data (`app/seeds/models.json`), not code.

If you open the app under another host name (a reverse proxy, a `.local`
name), add it with `VF_ALLOWED_HOSTS=name1,name2` in the app's environment.
