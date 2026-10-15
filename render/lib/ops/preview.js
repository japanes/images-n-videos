/**
 * preview — what the media library shows for a video: a poster JPEG, a short
 * looping WebP that plays on hover, and optional smaller JPEG thumbnails.
 *
 * A single frame does not tell what happens in a clip, and a grid of <video>
 * elements costs hundreds of megabytes per scroll. So: a few short slices from
 * across the clip glued into a looping WebP, 320 px wide, no sound, a few
 * hundred kilobytes. Built once, when the video lands in the library.
 *
 * Defaults are factory's (api/services/video_media.py): poster at 10% of the
 * clip but no later than 1 s, 720 px wide; 4 slices of 0.6 s at 12 fps, q 55.
 */

import fsp from 'node:fs/promises'

import { BadRequest } from '../errors.js'
import { JPEG_EXT, WEBP_EXT, resolveInput, resolveOutput } from '../paths.js'
import { even, list, num, optNum } from './common.js'

/**
 * Evenly spaced marks, skipping the head and tail: the first frames are often
 * a fade-in and the last ones a fade-out, and neither says what the clip is.
 */
export function pickMarks(duration, count, each) {
  if (!duration || duration <= each * 1.5) return [0]
  const head = Math.min(duration * 0.05, 1)
  const tail = Math.max(duration - each - Math.min(duration * 0.05, 1), head)
  const span = tail - head
  if (span <= 0) return [head]
  const n = Math.max(1, Math.min(count, Math.floor(duration / each)))
  if (n === 1) return [head]
  return Array.from({ length: n }, (_, i) => Number((head + (span * i) / (n - 1)).toFixed(3)))
}

/** Canvas size from an (animated) WebP header; ffmpeg 5.1 cannot decode those back. */
async function webpSize(file) {
  const handle = await fsp.open(file, 'r')
  try {
    const buf = Buffer.alloc(30)
    await handle.read(buf, 0, 30, 0)
    if (buf.toString('ascii', 0, 4) !== 'RIFF' || buf.toString('ascii', 8, 12) !== 'WEBP') return { width: null, height: null }
    const chunk = buf.toString('ascii', 12, 16)
    if (chunk === 'VP8X') {
      return { width: buf.readUIntLE(24, 3) + 1, height: buf.readUIntLE(27, 3) + 1 }
    }
    if (chunk === 'VP8 ') return { width: buf.readUInt16LE(26) & 0x3fff, height: buf.readUInt16LE(28) & 0x3fff }
    if (chunk === 'VP8L') {
      const bits = buf.readUInt32LE(21)
      return { width: (bits & 0x3fff) + 1, height: ((bits >> 14) & 0x3fff) + 1 }
    }
    return { width: null, height: null }
  } finally {
    await handle.close()
  }
}

export default {
  name: 'preview',

  async validate(body) {
    const thumbsIn = list(body.thumbs, 'thumbs', { max: 8 })
    const segments = num(body.segments ?? 4, 'segments', { min: 1, max: 8, integer: true })
    const each = num(body.segment_seconds ?? 0.6, 'segment_seconds', { min: 0.2, max: 2 })
    const width = even(num(body.width ?? 320, 'width', { min: 64, max: 1280, integer: true }))
    const fps = num(body.fps ?? 12, 'fps', { min: 5, max: 30, integer: true })
    const quality = num(body.quality ?? 55, 'quality', { min: 10, max: 95, integer: true })
    const posterWidth = even(num(body.poster_width ?? 720, 'poster_width', { min: 16, max: 4096, integer: true }))
    const posterAt = optNum(body.poster_at, 'poster_at', { min: 0, max: 86_400 })

    const input = await resolveInput(body.input, 'input')
    const poster = body.poster_output ? await resolveOutput(body.poster_output, 'poster_output', JPEG_EXT) : null
    const preview = body.preview_output ? await resolveOutput(body.preview_output, 'preview_output', WEBP_EXT) : null
    const thumbs = []
    for (const [i, t] of thumbsIn.entries()) {
      if (!t || typeof t !== 'object') throw new BadRequest(`thumbs[${i}] must be an object`)
      thumbs.push({
        width: even(num(t.width, `thumbs[${i}].width`, { min: 16, max: 4096, integer: true })),
        output: await resolveOutput(t.output, `thumbs[${i}].output`, JPEG_EXT),
      })
    }
    if (!poster && !preview && !thumbs.length) {
      throw new BadRequest('preview needs at least one of poster_output, preview_output, thumbs')
    }
    return { input, poster, preview, thumbs, segments, each, width, fps, quality, posterWidth, posterAt }
  },

  async run(p, ws) {
    const src = await ws.link(p.input)
    const meta = await ws.probe(src)
    if (!meta.has_video) throw new BadRequest('source has no video stream')
    const result = { poster: null, preview: null, thumbs: [], source: meta }
    const publishes = []

    // Poster and thumbnails: one decode of one frame, split and scaled per output.
    const stills = []
    if (p.poster) stills.push({ width: p.posterWidth, dest: p.poster, kind: 'poster' })
    for (const t of p.thumbs) stills.push({ width: t.width, dest: t.output, kind: 'thumb' })
    if (stills.length) {
      const lastAt = Math.max(0, meta.duration - 1 / (meta.fps || 25))
      const at = Number(Math.min(p.posterAt ?? Math.min(1, meta.duration * 0.1), lastAt).toFixed(3))
      const graph = []
      if (stills.length > 1) graph.push(`[0:v]split=${stills.length}${stills.map((_, i) => `[s${i}]`).join('')}`)
      const args = ['-ss', String(at), '-i', src]
      stills.forEach((s, i) => {
        // Never upscale: a 480 px source asked for a 720 px poster stays 480.
        const w = even(Math.min(s.width, meta.display_width || s.width))
        graph.push(`${stills.length > 1 ? `[s${i}]` : '[0:v]'}scale=${w}:-2[o${i}]`)
        s.name = ws.name(s.kind, '.jpg')
      })
      args.push('-filter_complex', graph.join(';'))
      stills.forEach((s, i) => args.push('-map', `[o${i}]`, '-frames:v', '1', '-q:v', '3', '-update', '1', s.name))
      await ws.stage(0, 0.2).ffmpeg(args)
      for (const s of stills) {
        const pic = await ws.probe(s.name)
        const entry = { output: s.dest.rel, width: pic.width, height: pic.height, size_bytes: pic.size_bytes, at }
        if (s.kind === 'poster') result.poster = entry
        else result.thumbs.push(entry)
        publishes.push([s.name, s.dest.abs])
      }
    }

    if (p.preview) {
      const marks = pickMarks(meta.duration, p.segments, p.each)
      const name = ws.name('preview', '.webp')
      // One pass, the same file opened once per slice with its own -ss: a
      // keyframe seek and `each` seconds decoded, no intermediates.
      const args = []
      for (const at of marks) args.push('-ss', String(at), '-t', String(p.each), '-i', src)
      const chain = marks
        .map((_, i) => `[${i}:v]scale=${p.width}:-2:force_original_aspect_ratio=decrease,fps=${p.fps},setsar=1[s${i}]`)
        .join(';')
      const joined = marks.map((_, i) => `[s${i}]`).join('')
      args.push(
        '-filter_complex', `${chain};${joined}concat=n=${marks.length}:v=1:a=0[out]`,
        '-map', '[out]',
        '-an',
        '-loop', '0',
        '-c:v', 'libwebp',
        '-lossless', '0',
        '-compression_level', '4',
        '-q:v', String(p.quality),
        // Without this the muxer keeps source timestamps and a slice taken at
        // 6 s starts its own timeline there, which shows as a long freeze.
        '-fps_mode', 'passthrough',
        name,
      )
      await ws.stage(0.2, 1).ffmpeg(args, { duration: marks.length * p.each })
      const size = await webpSize(ws.path(name))
      const bytes = (await fsp.stat(ws.path(name))).size
      result.preview = { output: p.preview.rel, width: size.width, height: size.height, size_bytes: bytes, segments: marks.length }
      publishes.push([name, p.preview.abs])
    }

    // Nothing lands on the volume until every piece is ready.
    for (const [name, dest] of publishes) await ws.publish(name, dest)
    return result
  },
}
