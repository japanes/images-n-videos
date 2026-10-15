/**
 * Shared pieces of the operations: argument checks, the encoders, probing and
 * the per-call workspace.
 */

import fsp from 'node:fs/promises'
import path from 'node:path'

import { fontsDir } from '../config.js'
import { BadRequest, Cancelled } from '../errors.js'
import { FONT_EXT, publish, resolveInput } from '../paths.js'
import { ffmpeg, ffprobe } from '../run.js'

// One encoder setting for everything this service writes. veryfast because the
// user is waiting in front of the screen; crf 20 because these files are
// usually final. +faststart puts the index first so the browser can play the
// file before it has all of it.
export const V = ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p', '-movflags', '+faststart']
export const A = ['-c:a', 'aac', '-b:a', '192k', '-ar', '48000']

export const ASPECTS = {
  '9:16': [1080, 1920],
  '1:1': [1080, 1080],
  '16:9': [1920, 1080],
  '4:5': [1080, 1350],
}

// ── argument checks ─────────────────────────────────────────────────────────

export function num(value, field, { min = -1e9, max = 1e9, integer = false } = {}) {
  const n = typeof value === 'string' && value.trim() !== '' ? Number(value) : value
  if (typeof n !== 'number' || !Number.isFinite(n)) throw new BadRequest(`${field} must be a number`)
  if (n < min || n > max) throw new BadRequest(`${field} must be between ${min} and ${max}`)
  return integer ? Math.round(n) : Number(n.toFixed(3))
}

export function optNum(value, field, opts) {
  return value === undefined || value === null ? null : num(value, field, opts)
}

export function oneOf(value, allowed, field, fallback) {
  if (value === undefined || value === null) return fallback
  if (!allowed.includes(value)) throw new BadRequest(`${field} must be one of: ${allowed.join(', ')}`)
  return value
}

export function obj(value, field) {
  if (value === undefined || value === null) return null
  if (typeof value !== 'object' || Array.isArray(value)) throw new BadRequest(`${field} must be an object`)
  return value
}

export function list(value, field, { max = 100 } = {}) {
  if (value === undefined || value === null) return []
  if (!Array.isArray(value)) throw new BadRequest(`${field} must be an array`)
  if (value.length > max) throw new BadRequest(`${field} is capped at ${max} entries`)
  return value
}

export const even = (n) => (n % 2 === 0 ? n : n - 1)

/** `#RRGGBB` / `RRGGBB` → `RRGGBB`. */
export function color(value, field, fallback = '000000') {
  if (value === undefined || value === null || value === '') return fallback
  if (!/^#?[0-9a-f]{6}$/i.test(String(value))) throw new BadRequest(`${field} must look like #RRGGBB`)
  return String(value).replace('#', '').toUpperCase()
}

/**
 * Output size from `width`/`height` or `aspect`. Null when neither is given,
 * so each op can pick its own default.
 */
export function sizeFrom(body, prefix = '') {
  const hasW = body.width !== undefined && body.width !== null
  const hasH = body.height !== undefined && body.height !== null
  if (hasW || hasH) {
    if (!hasW || !hasH) throw new BadRequest(`${prefix}width and ${prefix}height go together`)
    return [
      even(num(body.width, `${prefix}width`, { min: 16, max: 4096, integer: true })),
      even(num(body.height, `${prefix}height`, { min: 16, max: 4096, integer: true })),
    ]
  }
  if (body.aspect !== undefined && body.aspect !== null) {
    return ASPECTS[oneOf(body.aspect, Object.keys(ASPECTS), `${prefix}aspect`)]
  }
  return null
}

// ── probe ───────────────────────────────────────────────────────────────────

function parseFps(rate) {
  if (!rate) return null
  const [n, d] = String(rate).split('/').map(Number)
  if (!n || !d) return null
  return Number((n / d).toFixed(3))
}

function rotationOf(video) {
  if (!video) return 0
  const tag = Number(video.tags?.rotate)
  if (Number.isFinite(tag) && tag) return ((tag % 360) + 360) % 360
  const matrix = (video.side_data_list || []).find((s) => s.rotation !== undefined)
  if (matrix) return ((Math.round(Number(matrix.rotation)) % 360) + 360) % 360
  return 0
}

/**
 * What ffprobe says about a file. `width`/`height` are the coded size; when
 * `rotation` is 90 or 270 the picture is shown the other way round, which is
 * what `display_width`/`display_height` give.
 */
export async function probeFile(file, { signal } = {}) {
  const { stdout } = await ffprobe(
    ['-v', 'error', '-print_format', 'json', '-show_format', '-show_streams', file],
    { signal },
  )
  let parsed
  try {
    parsed = JSON.parse(stdout)
  } catch (err) {
    throw new Error('ffprobe returned unparseable output', { cause: err })
  }
  const streams = parsed.streams || []
  // An mp3 with cover art reports the picture as a video stream; it is not one.
  const video = streams.find((s) => s.codec_type === 'video' && !s.disposition?.attached_pic) || null
  const audio = streams.find((s) => s.codec_type === 'audio') || null
  const format = parsed.format || {}
  const duration = Number(format.duration) || Number(video?.duration) || Number(audio?.duration) || 0
  const rotation = rotationOf(video)
  const width = video ? Number(video.width) || null : null
  const height = video ? Number(video.height) || null : null
  const turned = rotation === 90 || rotation === 270
  return {
    duration: Number(duration.toFixed(3)),
    width,
    height,
    fps: video ? parseFps(video.avg_frame_rate || video.r_frame_rate) : null,
    has_video: Boolean(video),
    has_audio: Boolean(audio),
    video_codec: video?.codec_name || null,
    audio_codec: audio?.codec_name || null,
    size_bytes: Number(format.size) || null,
    bitrate: Number(format.bit_rate) || null,
    rotation,
    display_width: turned ? height : width,
    display_height: turned ? width : height,
  }
}

// ── workspace ───────────────────────────────────────────────────────────────

function safeExt(file) {
  const ext = path.extname(file).toLowerCase()
  return /^\.[a-z0-9]{1,5}$/.test(ext) ? ext : '.bin'
}

/**
 * One call's scratch directory, plus what every op needs inside it.
 *
 * Sources are symlinked in under plain generated names (`in-1.mp4`) and ffmpeg
 * runs with the scratch dir as its working directory. Filter arguments
 * (`subtitles=`, font dirs) therefore only ever contain names this code made
 * up, so nothing from a request needs filtergraph escaping, and a `%` in a file
 * name can never be read as an image-sequence pattern.
 */
export class Workspace {
  constructor({ dir, signal = null, onProgress = null, span = [0, 1], counter = { n: 0 }, batchId = null }) {
    this.dir = dir
    this.batchId = batchId
    this.signal = signal
    this.onProgress = onProgress
    this.span = span
    this.counter = counter
  }

  /** A child workspace whose progress fills `[from, to]` of this one's. */
  stage(from, to) {
    const [a, b] = this.span
    return new Workspace({
      dir: this.dir,
      signal: this.signal,
      onProgress: this.onProgress,
      span: [a + (b - a) * from, a + (b - a) * to],
      counter: this.counter,
      batchId: this.batchId,
    })
  }

  progress(fraction) {
    if (!this.onProgress) return
    const [a, b] = this.span
    this.onProgress(a + (b - a) * Math.max(0, Math.min(1, fraction)))
  }

  /** A fresh file name in scratch. */
  name(prefix, ext) {
    this.counter.n += 1
    return `${prefix}-${this.counter.n}${ext}`
  }

  path(name) {
    return path.join(this.dir, name)
  }

  /** Symlink a resolved source into scratch; returns its bare name. */
  async link(abs, prefix = 'in') {
    const name = this.name(prefix, safeExt(abs))
    await fsp.symlink(abs, this.path(name))
    return name
  }

  async write(prefix, ext, text) {
    const name = this.name(prefix, ext)
    await fsp.writeFile(this.path(name), text, 'utf8')
    return name
  }

  /**
   * A fonts directory for libass: the request's own font files plus whatever
   * sits in `<data>/fonts`. Returns its name, or null when there are none.
   */
  async fonts(requested = []) {
    const found = [...requested]
    for (const file of await volumeFonts()) found.push(file)
    if (!found.length) return null
    const name = this.name('fonts', '')
    await fsp.mkdir(this.path(name))
    let i = 0
    for (const abs of found) {
      i += 1
      await fsp.symlink(abs, path.join(this.path(name), `font-${String(i).padStart(3, '0')}${safeExt(abs)}`))
    }
    return name
  }

  async ffmpeg(args, { duration = 0, capture = false, timeoutMs } = {}) {
    this.checkCancelled()
    const result = await ffmpeg(args, {
      cwd: this.dir,
      signal: this.signal,
      capture,
      timeoutMs,
      duration,
      onProgress: (f) => this.progress(f),
    })
    this.progress(1)
    return result
  }

  probe(name) {
    this.checkCancelled()
    return probeFile(this.path(name), { signal: this.signal })
  }

  checkCancelled() {
    if (this.signal?.aborted) throw new Cancelled()
  }

  /** Move a scratch file to its final place (see paths.publish). */
  async publish(name, dest) {
    this.checkCancelled()
    await publish(this.path(name), dest)
  }
}

const MAX_VOLUME_FONTS = 200

/**
 * Font files under `<data>/fonts`, two levels deep at most, each one checked to
 * really live inside the data directory.
 */
async function volumeFonts() {
  const root = fontsDir()
  const found = []
  async function walk(dir, depth, relBase) {
    let entries
    try {
      entries = await fsp.readdir(dir, { withFileTypes: true })
    } catch (_) {
      return
    }
    for (const entry of entries) {
      if (found.length >= MAX_VOLUME_FONTS) return
      if (entry.name.startsWith('.')) continue
      const rel = `${relBase}/${entry.name}`
      if (entry.isDirectory()) {
        if (depth < 2) await walk(path.join(dir, entry.name), depth + 1, rel)
        continue
      }
      if (!FONT_EXT.includes(path.extname(entry.name).toLowerCase())) continue
      try {
        found.push(await resolveInput(rel, 'font'))
      } catch (_) {
        // A dangling link or something pointing off the volume is skipped, not fatal.
      }
    }
  }
  await walk(root, 0, 'fonts')
  return found
}
