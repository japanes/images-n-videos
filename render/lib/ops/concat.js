/**
 * concat — join clips into one film, in the order given.
 *
 * Three ways to join, and the difference between them is the whole quality of
 * the seam. Neighbouring scenes of a long video are generated around one shared
 * still — one is supposed to end on the picture the next begins on — so the
 * same moment exists twice, once at the end of the outgoing scene and once at
 * the start of the incoming one.
 *
 *   cut       — a hard join at the file boundary. Shows that moment twice in a
 *               row: a visible hitch exactly on the seam.
 *   crossfade — dissolves the boundary (default). Hides the hitch, but blends
 *               two frames of the same subject a beat apart, and the subject
 *               comes out doubled and translucent.
 *   align     — pass `anchors`, the shared still of each join, and the cut moves
 *               to where each clip genuinely reaches it: the tail of the
 *               outgoing scene and the head of the incoming one are scored
 *               against the still (SSIM) and both are trimmed to their best
 *               frame. The scenes meet on one picture instead of two, and the
 *               join is left as a plain cut.
 *
 * Align degrades on its own: a join with no still, a still that is missing or
 * unreadable, or a best score below `align_min_score` keeps the dissolve for
 * that seam and says so in the log and in `joins`. One bad join never costs the
 * others their alignment. A `null` anchor is different: it says "this seam is a
 * real cut" (another place, another camera) and gets neither alignment nor a
 * dissolve.
 */

import { BadRequest, FfmpegError, NotFound } from '../errors.js'
import * as log from '../log.js'
import { IMAGE_EXT, VIDEO_EXT, resolveInput, resolveOutput } from '../paths.js'
import { A, V, even, list, num, oneOf, optNum, sizeFrom } from './common.js'
import { matchStill, matchWindow, uniformFps } from './match.js'

// A trim that would leave less than this of a scene is refused and the seam
// stays as it was.
const MIN_SPAN = 0.5

async function parseConcat(body, prefix = '') {
  const inputsIn = list(body.inputs, `${prefix}inputs`, { max: 40 })
  if (!inputsIn.length) throw new BadRequest(`${prefix}inputs must contain at least one clip`)
  const size = sizeFrom(body, prefix)
  const fps = optNum(body.fps, `${prefix}fps`, { min: 12, max: 60, integer: true })
  const transition = oneOf(body.transition, ['crossfade', 'cut', 'align'], `${prefix}transition`, 'crossfade')
  const fade = num(body.transition_seconds ?? 0.3, `${prefix}transition_seconds`, { min: 0.05, max: 2 })
  // Zero by default, and that is the point: once the cut sits on the frame where
  // the two scenes meet, dissolving it blends pictures several frames apart and
  // puts back the doubled subject alignment removes.
  const joinFade = num(body.align_seconds ?? 0, `${prefix}align_seconds`, { min: 0, max: 1 })
  const search = num(body.align_search ?? 2, `${prefix}align_search`, { min: 0.2, max: 5 })
  // SSIM between two renderings of the same moment sits well above this even
  // with the grain of two separate generations; between two different moments
  // of the same scene it does not.
  const minScore = num(body.align_min_score ?? 0.45, `${prefix}align_min_score`, { min: 0, max: 1 })

  const inputs = []
  for (const [i, p] of inputsIn.entries()) inputs.push(await resolveInput(p, `${prefix}inputs[${i}]`))

  const anchorsIn = list(body.anchors, `${prefix}anchors`, { max: 39 })
  if (anchorsIn.length > Math.max(0, inputs.length - 1)) {
    throw new BadRequest(`${prefix}anchors has more entries than there are joins (${inputs.length - 1})`)
  }
  const anchors = []
  for (const [j, a] of anchorsIn.entries()) {
    if (a === null || a === undefined || a === '') {
      anchors.push(null)
      continue
    }
    const field = `${prefix}anchors[${j}]`
    try {
      anchors.push({ rel: String(a), abs: await resolveInput(a, field, { exts: IMAGE_EXT }) })
    } catch (err) {
      // A still that is gone costs its seam the alignment, not the whole film.
      // A path that is malformed or points somewhere forbidden is still a 400.
      if (!(err instanceof NotFound)) throw err
      anchors.push({ rel: String(a), abs: null })
    }
  }
  return { inputs, size, fps, transition, fade, joinFade, search, minScore, anchors, prefix }
}

/**
 * Move every join onto the frame where the two scenes actually meet. For join
 * j the shared still is `anchors[j]`; the tail of scene j and the head of
 * scene j+1 are each scored against it and both are trimmed to their best
 * frame.
 */
async function alignJoins(ws, step, files, metas) {
  const cuts = metas.map((m) => ({ start: 0, end: m.duration || 0 }))
  const joins = []
  const total = Math.max(1, files.length - 1)

  for (let j = 0; j + 1 < files.length; j += 1) {
    const anchor = step.anchors[j]
    const stage = ws.stage(j / total, (j + 1) / total)
    if (!anchor) {
      joins.push({ join: j, aligned: false, reason: j < step.anchors.length ? 'declared cut' : 'no still' })
      continue
    }
    if (!anchor.abs) {
      log.warn(ws.batchId, 'anchor not found, seam left as is', { join: j, anchor: anchor.rel })
      joins.push({ join: j, aligned: false, reason: 'still not found' })
      continue
    }

    const still = await ws.link(anchor.abs, 'anchor')
    const leftFps = Math.min(metas[j].fps || 25, 30)
    const rightFps = Math.min(metas[j + 1].fps || 25, 30)
    const tail = matchWindow(cuts[j].end, 'tail', step.search)
    const head = matchWindow(cuts[j + 1].end, 'head', step.search)

    let out
    let into
    try {
      [out, into] = await Promise.all([
        matchStill(stage.stage(0, 0.5), files[j], still, { ...tail, fps: leftFps }),
        matchStill(stage.stage(0.5, 1), files[j + 1], still, { ...head, fps: rightFps }),
      ])
    } catch (err) {
      if (!(err instanceof FfmpegError)) throw err
      log.warn(ws.batchId, 'anchor unreadable, seam left as is', { join: j, anchor: anchor.rel, error: err.message })
      joins.push({ join: j, aligned: false, reason: 'still unreadable' })
      continue
    }

    const weak = Math.min(out.score, into.score) < step.minScore
    const tooShort = out.time - cuts[j].start < MIN_SPAN || cuts[j + 1].end - into.time < MIN_SPAN
    const report = { join: j, out_at: out.time, out_score: out.score, into_at: into.time, into_score: into.score }
    if (weak || tooShort) {
      const reason = weak ? 'no clear match' : 'would leave too little of a scene'
      log.info(ws.batchId, 'seam not aligned', { ...report, reason })
      joins.push({ ...report, aligned: false, reason })
      continue
    }

    // Both clips carry the same picture on the matched frame, so exactly one of
    // the two copies may survive. A timestamp is never exactly what arithmetic
    // says it is, so half a frame of slack on each side settles it: the
    // outgoing scene stops before its copy, the incoming one opens on its own.
    cuts[j].end = Number((out.time - 0.5 / leftFps).toFixed(6))
    cuts[j + 1].start = Math.max(0, Number((into.time - 0.5 / rightFps).toFixed(6)))
    log.info(ws.batchId, 'seam aligned', report)
    joins.push({ ...report, aligned: true, reason: null })
  }
  return { cuts, joins }
}

/**
 * Join `step.inputs` into a new scratch file. Returns `{ name, joins }`;
 * `joins` reports what happened at each seam when aligning (empty otherwise).
 */
export async function concatCore(ws, step) {
  const files = []
  for (const abs of step.inputs) files.push(await ws.link(abs, 'part'))
  const metas = []
  for (const [i, f] of files.entries()) {
    const meta = await ws.probe(f)
    if (!meta.has_video) throw new BadRequest(`${step.prefix}inputs[${i}] has no video stream`)
    metas.push(meta)
  }

  // Default frame: the first clip's own (upright) size. A chain of extensions
  // all share it, so nothing gets scaled.
  const [w, h] = step.size || [even(metas[0].display_width), even(metas[0].display_height)]
  // Sources that already agree on a frame rate keep it: forcing 30 onto 24 fps
  // material repeats a frame every so often, and a repeat on a join reads as a
  // stutter exactly where the eye is looking for one.
  const fps = step.fps ?? uniformFps(metas) ?? 30

  const align = step.transition === 'align'
  const encode = align ? ws.stage(0.25, 1) : ws
  const { cuts, joins } = align
    ? await alignJoins(ws.stage(0, 0.25), step, files, metas)
    : { cuts: metas.map((m) => ({ start: 0, end: m.duration || 0 })), joins: [] }
  const alignedAt = (j) => joins[j]?.aligned === true
  const declaredCut = (j) => align && j < step.anchors.length && !step.anchors[j]

  // What each scene contributes after trimming; every offset below is measured
  // along the assembled timeline, so this is what the dissolve arithmetic uses.
  const spans = cuts.map((c, i) => Number((c.end - c.start).toFixed(3)) || metas[i].duration || 0)

  const args = []
  for (const f of files) args.push('-i', f)
  const silenceIndex = files.length
  if (metas.some((m) => !m.has_audio)) {
    args.push('-f', 'lavfi', '-i', 'anullsrc=channel_layout=stereo:sample_rate=48000')
  }

  const steps = []
  const legs = []
  metas.forEach((m, i) => {
    const cut = cuts[i]
    const trimmed = cut.start > 0 || cut.end < (m.duration || 0) - 0.001
    // setpts on every leg: xfade times the dissolve from the incoming stream's
    // own clock, and a scene that starts anywhere but zero would slide the join.
    steps.push(
      `[${i}:v]scale=${w}:${h}:force_original_aspect_ratio=increase,crop=${w}:${h},`
      + `fps=${fps},setsar=1,format=yuv420p,`
      + (trimmed ? `trim=start=${cut.start}:end=${cut.end},` : '')
      + `setpts=PTS-STARTPTS[cv${i}]`,
    )
    if (m.has_audio) {
      steps.push(
        `[${i}:a]aresample=48000,aformat=channel_layouts=stereo,`
        + (trimmed ? `atrim=start=${cut.start}:end=${cut.end},` : '')
        + `asetpts=PTS-STARTPTS[ca${i}]`,
      )
    } else {
      // The shared silence is infinite; cut it to this scene's length or concat
      // never reaches the next input.
      steps.push(`[${silenceIndex}:a]atrim=0:${spans[i] || 1},asetpts=PTS-STARTPTS[ca${i}]`)
    }
    legs.push(`[cv${i}][ca${i}]`)
  })

  // A dissolve eats its length off both sides of a join, so it cannot be longer
  // than the shorter scene can spare.
  const shortest = Math.min(...spans)
  const dissolves = files.slice(1).map((_, j) => {
    if (step.transition === 'cut' || shortest <= 0.5) return 0
    if (declaredCut(j)) return 0
    const want = alignedAt(j) ? step.joinFade : step.fade
    const usable = Math.min(want, Math.min(spans[j], spans[j + 1]) / 3)
    return usable >= 0.03 ? Number(usable.toFixed(3)) : 0
  })

  let length = spans.reduce((a, b) => a + b, 0)
  if (dissolves.some(Boolean)) {
    let video = 'cv0'
    let audio = 'ca0'
    let at = spans[0]
    for (let i = 1; i < files.length; i += 1) {
      // A join whose dissolve came out zero still has to be a join; xfade over
      // one frame is a hard cut with the timeline arithmetic intact.
      const dissolve = dissolves[i - 1] || Number((1 / fps).toFixed(3))
      const offset = Number((at - dissolve).toFixed(3))
      steps.push(`[${video}][cv${i}]xfade=transition=fade:duration=${dissolve}:offset=${offset}[vx${i}]`)
      steps.push(`[${audio}][ca${i}]acrossfade=d=${dissolve}:c1=tri:c2=tri[ax${i}]`)
      video = `vx${i}`
      audio = `ax${i}`
      at = Number((at + spans[i] - dissolve).toFixed(3))
    }
    length = at
    steps.push(`[${video}]null[vout]`, `[${audio}]anull[aout]`)
  } else {
    steps.push(`${legs.join('')}concat=n=${files.length}:v=1:a=1[vout][aout]`)
  }

  const name = ws.name('concat', '.mp4')
  args.push('-filter_complex', steps.join(';'), '-map', '[vout]', '-map', '[aout]', ...V, ...A, name)
  await encode.ffmpeg(args, { duration: length })
  return { name, joins }
}

export default {
  name: 'concat',

  parseStep: parseConcat,

  async validate(body) {
    const step = await parseConcat(body)
    const output = await resolveOutput(body.output, 'output', VIDEO_EXT)
    return { output, step }
  },

  async run({ output, step }, ws) {
    const { name, joins } = await concatCore(ws, step)
    const meta = await ws.probe(name)
    await ws.publish(name, output.abs)
    return { output: output.rel, meta, joins }
  },
}
