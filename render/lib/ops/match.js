/**
 * match — at what second a clip comes closest to a given still.
 *
 * This is how a chain of extensions is stitched without a hitch: each
 * extension was generated from the previous clip's last frame, so the same
 * picture exists at the end of one clip and the start of the next. Finding it
 * in both tells where to cut.
 */

import { IMAGE_EXT, resolveInput } from '../paths.js'
import { num, oneOf } from './common.js'

// Comparison happens on small grey frames. 160×160 is plenty to tell "this is
// the same moment" from "this is half a second later", and doing it at 1080p
// would mean decoding and scoring full frames forty times per join.
const MATCH_SIZE = 160

/**
 * Where in a stretch of a clip the still appears. Both streams are reduced to
 * the same small grey frames and handed to ffmpeg's own `ssim`, which prints a
 * score per frame pair; the highest score wins.
 *
 * The answer is the frame's own timestamp (`pts_time` from metadata=print), not
 * one computed from a frame number: the match is one frame wide, and a
 * fraction of a frame off is enough to leave a visible jump on the seam. So the
 * whole clip is decoded and the window comes from `trim` with timestamps left
 * alone. Clips here are seconds long.
 *
 * Returns `{ time, score, frames }`. Score 0 means nothing was scored, which
 * callers treat as "no match", not as a match at the window start.
 */
export async function matchStill(ws, video, still, { start, seconds, fps }) {
  const end = start + seconds
  const { stdout } = await ws.ffmpeg([
    '-v', 'error',
    '-i', video,
    '-i', still,
    '-filter_complex',
    `[0:v]fps=${fps},trim=start=${start}:end=${end},`
    + `scale=${MATCH_SIZE}:${MATCH_SIZE},format=gray[a];`
    + `[1:v]loop=loop=-1:size=1,fps=${fps},trim=duration=${seconds},`
    + `setpts=PTS-STARTPTS+${start}/TB,`
    + `scale=${MATCH_SIZE}:${MATCH_SIZE},format=gray[b];`
    + '[a][b]ssim=f=-:shortest=1,metadata=print:key=lavfi.ssim.All:file=-',
    '-f', 'null', '-',
  ], { capture: true, timeoutMs: 180_000 })

  // metadata=print writes two lines per frame:
  //   frame:40   pts:88      pts_time:3.666667
  //   lavfi.ssim.All=0.994391
  const best = { time: Number(start.toFixed(3)), score: 0, frames: 0 }
  let at = null
  for (const line of String(stdout).split('\n')) {
    const stamp = /\bpts_time:(-?[0-9.]+)/.exec(line)
    if (stamp) {
      at = Number(stamp[1])
      continue
    }
    const parsed = /^lavfi\.ssim\.All=([0-9.]+)/.exec(line.trim())
    if (!parsed || at === null) continue
    best.frames += 1
    const score = Number(parsed[1])
    if (!Number.isFinite(score) || score <= best.score) continue
    // Six places, not three: a frame at 24 fps is 41 ms, and rounding to the
    // millisecond can put the boundary on the wrong side of it.
    best.time = Number(at.toFixed(6))
    best.score = Number(score.toFixed(4))
  }
  return best
}

/**
 * The frame rate every source shares, or null when they differ or one is
 * unknown. Rounded: ffprobe says 24000/1001 for footage everyone calls 24.
 */
export function uniformFps(metas) {
  const rates = metas.map((m) => Math.round(m.fps || 0)).filter((r) => r >= 12 && r <= 60)
  if (rates.length !== metas.length) return null
  return rates.every((r) => r === rates[0]) ? rates[0] : null
}

/**
 * Which stretch of a clip to search. Head and tail are capped at half the clip
 * so the two ends of one scene can never claim the same frames.
 */
export function matchWindow(duration, where, seconds) {
  const total = duration || seconds
  const span = Math.max(0.1, Math.min(seconds, where === 'all' ? total : total / 2))
  if (where === 'head') return { start: 0, seconds: Number(span.toFixed(3)) }
  if (where === 'tail') {
    return { start: Number(Math.max(0, total - span).toFixed(3)), seconds: Number(span.toFixed(3)) }
  }
  return { start: 0, seconds: Number(total.toFixed(3)) }
}

export default {
  name: 'match',
  sync: true,

  async validate(body) {
    const where = oneOf(body.window, ['head', 'tail', 'all'], 'window', 'all')
    const seconds = num(body.seconds ?? 2, 'seconds', { min: 0.2, max: 30 })
    const fps = body.fps === undefined || body.fps === null ? null : num(body.fps, 'fps', { min: 1, max: 60 })
    const input = await resolveInput(body.input, 'input')
    const image = await resolveInput(body.image, 'image', { exts: IMAGE_EXT })
    return { input, image, where, seconds, fps }
  },

  async run({ input, image, where, seconds, fps }, ws) {
    const video = await ws.link(input)
    const still = await ws.link(image, 'still')
    const meta = await ws.probe(video)
    const rate = fps ?? Math.min(meta.fps || 25, 30)
    const window = matchWindow(meta.duration, where, seconds)
    const found = await matchStill(ws, video, still, { ...window, fps: rate })
    return {
      at: found.time,
      score: found.score,
      frames: found.frames,
      window: where,
      window_start: window.start,
      window_seconds: window.seconds,
      duration: meta.duration,
    }
  },
}
