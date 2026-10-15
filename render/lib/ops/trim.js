/**
 * trim — keep one stretch of a clip.
 *
 * Always re-encoded: copying would snap the cut to the nearest keyframe, which
 * on a Veo clip can be a second and a half away from where the user cut.
 */

import { BadRequest } from '../errors.js'
import { VIDEO_EXT, resolveInput, resolveOutput } from '../paths.js'
import { A, V, optNum } from './common.js'

/** Map and encode whatever streams the source has. */
export function streamArgs(meta, { video = '0:v:0', audio = '0:a:0' } = {}) {
  const args = []
  if (meta.has_video) args.push('-map', video, ...V)
  else args.push('-vn')
  if (meta.has_audio) args.push('-map', audio, ...A)
  else args.push('-an')
  return args
}

export function parseRange(body, prefix = '') {
  const start = optNum(body.start, `${prefix}start`, { min: 0, max: 86_400 }) ?? 0
  const end = optNum(body.end, `${prefix}end`, { min: 0, max: 86_400 })
  if (end !== null && end <= start) throw new BadRequest(`${prefix}end must be greater than ${prefix}start`)
  return { start, end }
}

/**
 * Cut `[start, end)` out of scratch file `src` into a new scratch file.
 * `end` null means "to the end". Returns the new name.
 */
export async function trimCore(ws, src, { start, end }, meta = null) {
  const info = meta || await ws.probe(src)
  if (info.duration > 0 && start >= info.duration) {
    throw new BadRequest(`start (${start}) is past the end of the source (${info.duration} s)`)
  }
  const stop = end === null ? info.duration : (info.duration > 0 ? Math.min(end, info.duration) : end)
  const length = Number((stop - start).toFixed(3))
  if (!(length > 0)) throw new BadRequest('the range to keep is empty')
  const out = ws.name('trim', '.mp4')
  // -ss before -i seeks fast, and because the output is re-encoded the cut is
  // still exact to the frame.
  await ws.ffmpeg(['-ss', String(start), '-i', src, '-t', String(length), ...streamArgs(info), out], { duration: length })
  return out
}

export default {
  name: 'trim',

  async parseStep(body, prefix = '') {
    if (Array.isArray(body.segments) && body.segments.length > 1) {
      throw new BadRequest('compose takes a single trim range; use split for several pieces')
    }
    const range = Array.isArray(body.segments) && body.segments.length === 1 ? body.segments[0] : body
    return parseRange(range, prefix)
  },

  async core(ws, src, step) {
    return trimCore(ws, src, step)
  },

  async validate(body) {
    const range = parseRange(body)
    const input = await resolveInput(body.input, 'input')
    const output = await resolveOutput(body.output, 'output', VIDEO_EXT)
    return { input, output, range }
  },

  async run({ input, output, range }, ws) {
    const src = await ws.link(input)
    const out = await trimCore(ws, src, range)
    const meta = await ws.probe(out)
    await ws.publish(out, output.abs)
    return { output: output.rel, meta }
  },
}
