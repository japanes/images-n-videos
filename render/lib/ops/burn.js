/**
 * burn — bake layers into the picture: PNG overlays (a logo, a rendered text
 * card), each with its own place, size, opacity and time window, and an ASS
 * subtitle track on top.
 *
 * Subtitles arrive as ready ASS (in the body or as a file on the volume):
 * libass is the only thing here that does per-word highlighting and outlines
 * properly, and the styling is decided on the app side.
 *
 * Fonts: the image has DejaVu and Liberation, which cover Cyrillic, so an ASS
 * style asking for "Arial" or "DejaVu Sans" renders Russian and Ukrainian text
 * out of the box. Brand fonts are font files under `<data>/fonts` (and any
 * listed in `fonts`); they are handed to libass as its fonts directory.
 * Without that libass silently falls back to a default face.
 */

import { BadRequest } from '../errors.js'
import { ASS_EXT, FONT_EXT, IMAGE_EXT, VIDEO_EXT, resolveInput, resolveOutput } from '../paths.js'
import { A, V, even, list, num, optNum } from './common.js'

const MAX_ASS = 1_000_000

async function parseBurn(body, prefix = '') {
  const overlaysIn = list(body.overlays, `${prefix}overlays`, { max: 32 })
  const fontsIn = list(body.fonts, `${prefix}fonts`, { max: 32 })
  let ass = null
  if (body.subtitles_ass !== undefined && body.subtitles_ass !== null && body.subtitles_ass !== '') {
    if (typeof body.subtitles_ass !== 'string') throw new BadRequest(`${prefix}subtitles_ass must be a string`)
    if (body.subtitles_ass.length > MAX_ASS) throw new BadRequest(`${prefix}subtitles_ass is too large`)
    ass = body.subtitles_ass
  }
  const assPath = body.subtitles_path ? await resolveInput(body.subtitles_path, `${prefix}subtitles_path`, { exts: ASS_EXT }) : null
  if (ass && assPath) throw new BadRequest(`pass ${prefix}subtitles_ass or ${prefix}subtitles_path, not both`)

  const overlays = []
  for (const [i, o] of overlaysIn.entries()) {
    const f = `${prefix}overlays[${i}]`
    if (!o || typeof o !== 'object') throw new BadRequest(`${f} must be an object`)
    const start = optNum(o.start, `${f}.start`, { min: 0, max: 86_400 })
    const end = optNum(o.end, `${f}.end`, { min: 0, max: 86_400 })
    if (start !== null && end !== null && end <= start) throw new BadRequest(`${f}: end must be greater than start`)
    overlays.push({
      image: await resolveInput(o.image, `${f}.image`, { exts: IMAGE_EXT }),
      x: num(o.x ?? 0, `${f}.x`, { min: -8192, max: 8192, integer: true }),
      y: num(o.y ?? 0, `${f}.y`, { min: -8192, max: 8192, integer: true }),
      width: o.width ? even(num(o.width, `${f}.width`, { min: 2, max: 8192, integer: true })) : -1,
      height: o.height ? even(num(o.height, `${f}.height`, { min: 2, max: 8192, integer: true })) : -1,
      opacity: num(o.opacity ?? 1, `${f}.opacity`, { min: 0, max: 1 }),
      start,
      end,
    })
  }
  const fonts = []
  for (const [i, p] of fontsIn.entries()) fonts.push(await resolveInput(p, `${prefix}fonts[${i}]`, { exts: FONT_EXT }))

  if (!overlays.length && !ass && !assPath) {
    throw new BadRequest(`nothing to burn: pass ${prefix}overlays and/or ${prefix}subtitles_ass / ${prefix}subtitles_path`)
  }
  return { overlays, ass, assPath, fonts }
}

// `enable=between(t,…)` gives a layer its time window; omitted when the layer
// covers the whole clip, so the simple case stays a simple filtergraph.
function timeWindow(o) {
  if (o.start === null && o.end === null) return ''
  return `:enable='between(t,${o.start ?? 0},${o.end ?? 86_400})'`
}

export async function burnCore(ws, src, step) {
  const meta = await ws.probe(src)
  if (!meta.has_video) throw new BadRequest('source has no video stream')

  const args = ['-i', src]
  const steps = ['[0:v]null[v0]']
  let last = 'v0'
  for (const [i, o] of step.overlays.entries()) {
    args.push('-i', await ws.link(o.image, 'overlay'))
    const chain = [`[${i + 1}:v]scale=${o.width}:${o.height}`]
    // colorchannelmixer on alpha fades a PNG that already has transparency;
    // a plain alpha filter would flatten it.
    if (o.opacity < 1) chain.push(`format=rgba,colorchannelmixer=aa=${o.opacity}`)
    steps.push(`${chain.join(',')}[ov${i}]`)
    steps.push(`[${last}][ov${i}]overlay=x=${o.x}:y=${o.y}${timeWindow(o)}[v${i + 1}]`)
    last = `v${i + 1}`
  }

  let subs = null
  if (step.ass) subs = await ws.write('subs', '.ass', step.ass)
  else if (step.assPath) subs = await ws.link(step.assPath, 'subs')
  if (subs) {
    const fontsDir = await ws.fonts(step.fonts)
    steps.push(`[${last}]subtitles=${subs}${fontsDir ? `:fontsdir=${fontsDir}` : ''}[vout]`)
    last = 'vout'
  }

  args.push('-filter_complex', steps.join(';'), '-map', `[${last}]`, ...V)
  if (meta.has_audio) {
    // The sound is not touched; copied when the mp4 can carry it as is.
    const copyable = ['aac', 'mp3'].includes(meta.audio_codec)
    args.push('-map', '0:a:0', ...(copyable ? ['-c:a', 'copy'] : A))
  } else {
    args.push('-an')
  }
  const out = ws.name('burn', '.mp4')
  args.push(out)
  await ws.ffmpeg(args, { duration: meta.duration })
  return out
}

export default {
  name: 'burn',

  parseStep: parseBurn,
  core: burnCore,

  async validate(body) {
    const step = await parseBurn(body)
    const input = await resolveInput(body.input, 'input')
    const output = await resolveOutput(body.output, 'output', VIDEO_EXT)
    return { input, output, step }
  },

  async run({ input, output, step }, ws) {
    const src = await ws.link(input)
    const out = await burnCore(ws, src, step)
    const meta = await ws.probe(out)
    await ws.publish(out, output.abs)
    return { output: output.rel, meta }
  },
}
