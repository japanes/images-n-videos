/**
 * Test harness.
 *
 * Every test file gets its own data directory, laid out like the real volume
 * (`files/`, `cache/`, …), under `$VF_DATA_DIR/test-<name>/` — in the image
 * that is the mounted /data, on a host it falls back to
 * `<project>/tmp/render/data`. Never the system temp: a failed run should still
 * be there to look at tomorrow.
 *
 * Media fixtures are made by ffmpeg's own test sources (lavfi) when the file
 * starts, so the repository carries no binary media.
 *
 * Tests go through HTTP on purpose: that is the contract the app depends on,
 * and calling the op functions directly would leave the routes, the queue and
 * the error mapping untested.
 */

import { execFile } from 'node:child_process'
import { once } from 'node:events'
import fs from 'node:fs'
import fsp from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'

const run = promisify(execFile)
const here = path.dirname(fileURLToPath(import.meta.url))

export const DATA_ROOT = path.resolve(process.env.VF_DATA_DIR || path.join(here, '../../tmp/render/data'))

// The service logs a JSON line per request; in a test run that is noise. Set
// RENDER_LOG_LEVEL=info to see it.
process.env.RENDER_LOG_LEVEL ??= 'silent'

const ENC = ['-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '16', '-pix_fmt', 'yuv420p']

// The master take behind scene-a / scene-b / anchor.png: 4 s of testsrc2 at
// 25 fps. scene-a is its first 3.52 s, scene-b its last 1.52 s, so the two
// overlap on [2.48, 3.52) — like two generated scenes that both carry the
// shared still — and anchor.png is the frame at 3.0 s: 3.0 into scene-a, 0.52
// into scene-b.
const MASTER = 'testsrc2=size=320x240:rate=25:duration=4'
const TONE = 'sine=frequency=550:sample_rate=44100:duration=4'

function scene(start, end) {
  return [
    '-f', 'lavfi', '-i', `${MASTER},trim=start=${start}:end=${end},setpts=PTS-STARTPTS`,
    '-f', 'lavfi', '-i', `${TONE},atrim=start=${start}:end=${end},asetpts=PTS-STARTPTS`,
    ...ENC, '-c:a', 'aac', '-ac', '1',
  ]
}

export const FIXTURES = {
  'sample.mp4': [
    '-f', 'lavfi', '-i', 'testsrc2=size=320x240:rate=25:duration=4',
    '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=44100:duration=4',
    ...ENC, '-c:a', 'aac', '-ac', '1', '-shortest',
  ],
  'silent.mp4': ['-f', 'lavfi', '-i', 'testsrc=size=480x270:rate=25:duration=2', ...ENC, '-an'],
  // A flat grey picture: anything burnt onto it shows up as changed pixels.
  'plain.mp4': ['-f', 'lavfi', '-i', 'color=c=0x404040:size=320x240:rate=25:duration=2', ...ENC, '-an'],
  'voice.mp3': ['-f', 'lavfi', '-i', 'sine=frequency=220:sample_rate=16000:duration=6', '-ac', '1', '-c:a', 'libmp3lame', '-b:a', '32k'],
  'long.mp3': ['-f', 'lavfi', '-i', 'sine=frequency=330:sample_rate=16000:duration=70', '-ac', '1', '-c:a', 'libmp3lame', '-b:a', '32k'],
  'overlay.png': ['-f', 'lavfi', '-i', 'color=c=0xFF3300@0.6:size=64x64,format=rgba', '-frames:v', '1'],
  'scene-a.mp4': scene(0, 3.52),
  'scene-b.mp4': scene(2.48, 4),
  'anchor.png': ['-f', 'lavfi', '-i', `${MASTER},trim=start=3:end=3.04,setpts=PTS-STARTPTS`, '-frames:v', '1'],
}

export async function ffmpeg(args, opts = {}) {
  return run('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-nostdin', '-y', ...args], { maxBuffer: 64 * 1024 * 1024, ...opts })
}

/** Write the named fixtures into `<dir>/files/fx/`. */
export async function makeFixtures(dir, names) {
  const fx = path.join(dir, 'files', 'fx')
  await fsp.mkdir(fx, { recursive: true })
  await Promise.all(names.map((name) => ffmpeg([...FIXTURES[name], path.join(fx, name)])))
}

/** A fresh, empty data directory for one test file; VF_DATA_DIR points at it. */
export async function prepareData(name) {
  const dir = path.join(DATA_ROOT, `test-${name}`)
  await fsp.rm(dir, { recursive: true, force: true })
  for (const sub of ['files', 'cache/render', 'cache/tmp', 'cache/thumbs', 'secrets', 'backups']) {
    await fsp.mkdir(path.join(dir, sub), { recursive: true })
  }
  process.env.VF_DATA_DIR = dir
  handBack(dir)
  return dir
}

/**
 * In the image the tests run as root, on a folder bind-mounted from the
 * developer's machine. Without this every file they leave there would belong
 * to root and need sudo to delete; on exit it is given to whoever owns the
 * mounted folder.
 */
function handBack(dir) {
  if (typeof process.getuid !== 'function' || process.getuid() !== 0) return
  let owner
  try {
    owner = fs.statSync(DATA_ROOT)
  } catch (_) {
    return
  }
  if (owner.uid === 0) return
  process.once('exit', () => chownTree(dir, owner.uid, owner.gid))
}

function chownTree(target, uid, gid) {
  try {
    fs.lchownSync(target, uid, gid)
  } catch (_) {
    return
  }
  let entries
  try {
    entries = fs.readdirSync(target, { withFileTypes: true })
  } catch (_) {
    return
  }
  for (const entry of entries) {
    const child = path.join(target, entry.name)
    if (entry.isDirectory()) chownTree(child, uid, gid)
    else {
      try {
        fs.lchownSync(child, uid, gid)
      } catch (_) {
        // already gone
      }
    }
  }
}

/**
 * Data directory + fixtures + the app on an ephemeral port. The lib is
 * imported only after VF_DATA_DIR is set (config reads it lazily anyway).
 */
export async function setup(name, { fixtures = Object.keys(FIXTURES) } = {}) {
  const dir = await prepareData(name)
  await makeFixtures(dir, fixtures)
  const { createApp } = await import('../lib/app.js')
  const server = createApp().listen(0, '127.0.0.1')
  await once(server, 'listening')
  return {
    dir,
    base: `http://127.0.0.1:${server.address().port}`,
    abs: (rel) => path.join(dir, rel),
    stop: () => new Promise((resolve) => server.close(resolve)),
  }
}

export async function post(base, route, body, { batchId = 'test-batch', raw = null } = {}) {
  const res = await fetch(`${base}${route}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'x-batch-id': batchId },
    body: raw ?? JSON.stringify(body),
  })
  return { status: res.status, headers: res.headers, json: await res.json() }
}

export async function getJob(base, id) {
  const res = await fetch(`${base}/jobs/${id}`)
  return { status: res.status, json: await res.json() }
}

export const TERMINAL = ['done', 'error', 'cancelled']

/** Submit a queued op and wait for it to settle. Returns the job body. */
export async function runJob(base, op, body, { timeoutMs = 180_000 } = {}) {
  const submitted = await post(base, `/${op}`, body)
  if (submitted.status !== 202) {
    throw new Error(`${op} was not accepted: ${submitted.status} ${JSON.stringify(submitted.json)}`)
  }
  return waitJob(base, submitted.json.job_id, { timeoutMs })
}

export async function waitJob(base, id, { timeoutMs = 180_000, until = TERMINAL } = {}) {
  const deadline = Date.now() + timeoutMs
  for (;;) {
    const { json } = await getJob(base, id)
    if (until.includes(json.status)) return json
    if (Date.now() > deadline) throw new Error(`job ${id} did not reach ${until.join('/')} within ${timeoutMs} ms`)
    await sleep(100)
  }
}

/** A readable failure message for a job that did not end `done`. */
export const why = (job) => JSON.stringify(job.error)

export const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

export const near = (actual, expected, tolerance = 0.35) => Math.abs(actual - expected) <= tolerance

/** ffprobe a file the tests produced. */
export async function probe(abs) {
  const { probeFile } = await import('../lib/ops/common.js')
  return probeFile(abs)
}

/** One decoded frame as raw 8-bit grey pixels. */
export async function grayFrame(abs, at) {
  const { stdout } = await ffmpeg(['-ss', String(at), '-i', abs, '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'gray', '-'], { encoding: 'buffer' })
  return stdout
}

/** How many pixels differ by more than `delta` between two grey frames. */
export function changedPixels(a, b, delta = 40) {
  if (a.length !== b.length) throw new Error(`frame sizes differ: ${a.length} vs ${b.length}`)
  let n = 0
  for (let i = 0; i < a.length; i += 1) if (Math.abs(a[i] - b[i]) > delta) n += 1
  return n
}

export function ass(text, { font = 'DejaVu Sans', size = 24, start = '0:00:00.00', end = '0:00:04.00' } = {}) {
  return `[Script Info]
ScriptType: v4.00+
PlayResX: 320
PlayResY: 240

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,${font},${size},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,5,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,${start},${end},Default,,0,0,0,,${text}
`
}

export const ASS = ass('hello {\\c&H00FF00&}world')
