/**
 * split-audio — cut a long recording into small mono mp3 parts for speech
 * recognition. Speech does not need more than 16 kHz mono at a low bitrate,
 * and that turns a size cap into roughly an hour per part instead of minutes.
 *
 * Parts are written as `<output_dir>/part-000.mp3`, `part-001.mp3`, …; each
 * part's timestamps start at zero.
 */

import fsp from 'node:fs/promises'

import { BadRequest } from '../errors.js'
import { resolveInput, resolveOutputDir } from '../paths.js'
import { num, optNum } from './common.js'

export default {
  name: 'split-audio',

  async validate(body) {
    const maxMb = num(body.max_mb ?? 20, 'max_mb', { min: 1, max: 100 })
    const kbps = num(body.bitrate_kbps ?? 64, 'bitrate_kbps', { min: 32, max: 192, integer: true })
    const chunk = optNum(body.chunk_seconds, 'chunk_seconds', { min: 5, max: 3600, integer: true })
    const input = await resolveInput(body.input, 'input')
    const outputDir = await resolveOutputDir(body.output_dir, 'output_dir')
    return { input, outputDir, maxMb, kbps, chunk }
  },

  async run({ input, outputDir, maxMb, kbps, chunk }, ws) {
    const src = await ws.link(input)
    const meta = await ws.probe(src)
    if (!meta.has_audio) throw new BadRequest('source has no audio stream')

    // bytes per second = kbps * 1000 / 8; a 10% margin covers container
    // overhead and the muxer cutting on frame boundaries, not exact time.
    const perSecond = (kbps * 1000) / 8
    const chunkSeconds = chunk ?? Math.max(30, Math.floor(((maxMb * 1024 * 1024) / perSecond) * 0.9))

    const prefix = ws.name('part', '')
    await ws.ffmpeg([
      '-i', src,
      '-vn',
      '-ac', '1',
      '-ar', '16000',
      '-c:a', 'libmp3lame',
      '-b:a', `${kbps}k`,
      '-f', 'segment',
      '-segment_time', String(chunkSeconds),
      // Without this every part after the first keeps the original timeline and
      // the transcriber reports word timings minutes into a short file.
      '-reset_timestamps', '1',
      `${prefix}-%03d.mp3`,
    ], { duration: meta.duration })

    const pattern = new RegExp(`^${prefix}-(\\d{3})\\.mp3$`)
    const parts = (await fsp.readdir(ws.dir)).filter((f) => pattern.test(f)).sort()
    if (!parts.length) throw new Error('split produced no parts')

    const outputs = []
    for (const [i, name] of parts.entries()) {
      const base = `part-${String(i).padStart(3, '0')}.mp3`
      outputs.push({ name, base, rel: `${outputDir.rel}/${base}`, meta: await ws.probe(name) })
    }
    for (const o of outputs) await ws.publish(o.name, `${outputDir.abs}/${o.base}`)
    return {
      outputs: outputs.map((o) => ({ output: o.rel, meta: o.meta })),
      chunk_seconds: chunkSeconds,
      duration: meta.duration,
    }
  },
}
