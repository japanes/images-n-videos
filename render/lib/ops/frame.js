/**
 * frame — one still as a JPEG: the first frame (the next extension starts from
 * it), the last one (the chain continues from it), or any second in between.
 */

import fsp from 'node:fs/promises'

import { BadRequest } from '../errors.js'
import { JPEG_EXT, resolveInput, resolveOutput } from '../paths.js'
import { even, num } from './common.js'

function parseAt(value) {
  if (value === undefined || value === null || value === 'first') return 'first'
  if (value === 'last') return 'last'
  if (typeof value === 'string' && !/^\s*-?[0-9.]+\s*$/.test(value)) {
    throw new BadRequest('at must be a number of seconds, "first" or "last"')
  }
  return num(value, 'at', { min: 0, max: 86_400 })
}

export default {
  name: 'frame',
  sync: true,

  async validate(body) {
    const at = parseAt(body.at)
    const maxWidth = body.max_width === undefined || body.max_width === null
      ? null
      : even(num(body.max_width, 'max_width', { min: 16, max: 8192, integer: true }))
    const input = await resolveInput(body.input, 'input')
    const output = await resolveOutput(body.output, 'output', JPEG_EXT)
    return { input, output, at, maxWidth }
  },

  async run({ input, output, at, maxWidth }, ws) {
    const src = await ws.link(input)
    const meta = await ws.probe(src)
    if (!meta.has_video) throw new BadRequest('source has no video stream')

    // The last frame starts one frame before the end. Asking for a second past
    // it, or for the end itself, means "the last frame": seeking there would
    // decode nothing and write no picture at all.
    const frameStep = 1 / (meta.fps || 25)
    const lastAt = Math.max(0, Number((meta.duration - frameStep).toFixed(3)))
    const wantsLast = at === 'last' || (typeof at === 'number' && meta.duration > 0 && at >= lastAt)

    // ffmpeg turns rotated phone video upright before filters, so the size to
    // compare against is the displayed one.
    const scale = maxWidth && meta.display_width > maxWidth ? ['-vf', `scale=${maxWidth}:-2`] : []
    const out = ws.name('frame', '.jpg')

    const grab = async (last) => {
      const args = last
        // Decode the final second and keep overwriting one file: whatever frame
        // comes last is the one left on disk. Seeking straight to "duration
        // minus one frame" misses on clips whose timestamps do not end exactly
        // where the container says.
        ? (meta.duration > 0 ? ['-sseof', String(-Math.min(1, meta.duration)), '-i', src] : ['-i', src])
        : ['-ss', String(at === 'first' ? 0 : at), '-i', src, '-frames:v', '1']
      args.push(...scale, '-q:v', '2', '-update', '1', out)
      await ws.ffmpeg(args)
    }

    await grab(wantsLast)
    let reported = wantsLast ? lastAt : (at === 'first' ? 0 : at)
    let exists = await fsp.stat(ws.path(out)).then((s) => s.size > 0).catch(() => false)
    if (!exists && !wantsLast) {
      // A seek that lands past the last decodable frame writes nothing; the
      // nearest real frame is the last one.
      await grab(true)
      reported = lastAt
      exists = await fsp.stat(ws.path(out)).then((s) => s.size > 0).catch(() => false)
    }
    if (!exists) throw new BadRequest('no frame could be read at that point')

    const pic = await ws.probe(out)
    await ws.publish(out, output.abs)
    return { output: output.rel, width: pic.width, height: pic.height, at: reported }
  },
}
