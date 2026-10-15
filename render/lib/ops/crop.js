/**
 * crop — reframe a clip: to a target aspect or size, and/or to a rectangle.
 *
 *   cover — fill the frame and cut the overflow (default);
 *   pad   — fit the whole picture and fill the bars with a colour;
 *   blur  — fit the whole picture and fill the bars with a blurred copy of
 *           itself, which is what phone editors do and viewers read as normal.
 *
 * `rect` cuts a region first, in displayed pixels (a rotated phone clip is
 * measured upright). Without a target size the region's own size is kept.
 */

import { BadRequest } from '../errors.js'
import { VIDEO_EXT, resolveInput, resolveOutput } from '../paths.js'
import { A, V, color, even, num, obj, oneOf, sizeFrom } from './common.js'

function parseRect(value, prefix) {
  const rect = obj(value, `${prefix}rect`)
  if (!rect) return null
  return {
    x: num(rect.x ?? 0, `${prefix}rect.x`, { min: 0, max: 16_384, integer: true }),
    y: num(rect.y ?? 0, `${prefix}rect.y`, { min: 0, max: 16_384, integer: true }),
    width: num(rect.width, `${prefix}rect.width`, { min: 2, max: 16_384, integer: true }),
    height: num(rect.height, `${prefix}rect.height`, { min: 2, max: 16_384, integer: true }),
  }
}

function parseCrop(body, prefix = '') {
  const size = sizeFrom(body, prefix)
  const rect = parseRect(body.rect, prefix)
  if (!size && !rect) throw new BadRequest(`${prefix ? `${prefix.slice(0, -1)} ` : 'crop '}needs aspect, width/height or rect`)
  return {
    size,
    rect,
    mode: oneOf(body.mode, ['cover', 'pad', 'blur'], `${prefix}mode`, 'cover'),
    color: color(body.pad_color, `${prefix}pad_color`),
  }
}

export function fitFilter(w, h, mode, padColor = '000000') {
  if (mode === 'pad') {
    return `scale=${w}:${h}:force_original_aspect_ratio=decrease,`
      + `pad=${w}:${h}:(ow-iw)/2:(oh-ih)/2:0x${padColor},setsar=1`
  }
  if (mode === 'blur') {
    return 'split=2[bg][fg];'
      + `[bg]scale=${w}:${h}:force_original_aspect_ratio=increase,crop=${w}:${h},gblur=sigma=25[bgb];`
      + `[fg]scale=${w}:${h}:force_original_aspect_ratio=decrease[fgs];`
      + '[bgb][fgs]overlay=(W-w)/2:(H-h)/2,setsar=1'
  }
  return `scale=${w}:${h}:force_original_aspect_ratio=increase,crop=${w}:${h},setsar=1`
}

export async function cropCore(ws, src, step) {
  const meta = await ws.probe(src)
  if (!meta.has_video) throw new BadRequest('source has no video stream')
  let pre = ''
  if (step.rect) {
    const { x, y, width, height } = step.rect
    if (x + width > meta.display_width || y + height > meta.display_height) {
      throw new BadRequest(`rect does not fit inside the ${meta.display_width}x${meta.display_height} picture`)
    }
    pre = `crop=${width}:${height}:${x}:${y},`
  }
  const [w, h] = step.size || [even(step.rect.width), even(step.rect.height)]
  const out = ws.name('crop', '.mp4')
  const args = ['-i', src, '-filter_complex', `[0:v]${pre}${fitFilter(w, h, step.mode, step.color)}[vout]`, '-map', '[vout]', ...V]
  args.push(...(meta.has_audio ? ['-map', '0:a:0', ...A] : ['-an']), out)
  await ws.ffmpeg(args, { duration: meta.duration })
  return out
}

export default {
  name: 'crop',

  async parseStep(body, prefix = '') {
    return parseCrop(body, prefix)
  },

  core: cropCore,

  async validate(body) {
    const step = parseCrop(body)
    const input = await resolveInput(body.input, 'input')
    const output = await resolveOutput(body.output, 'output', VIDEO_EXT)
    return { input, output, step }
  },

  async run({ input, output, step }, ws) {
    const src = await ws.link(input)
    const out = await cropCore(ws, src, step)
    const meta = await ws.probe(out)
    await ws.publish(out, output.abs)
    return { output: output.rel, meta }
  },
}
