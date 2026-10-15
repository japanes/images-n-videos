/**
 * split — cut one clip into pieces at the given seconds. N cut points give
 * N+1 pieces; each is re-encoded so every cut is exact to the frame.
 */

import { BadRequest } from '../errors.js'
import { VIDEO_EXT, resolveInput, resolveOutput } from '../paths.js'
import { list, num } from './common.js'
import { trimCore } from './trim.js'

export default {
  name: 'split',

  async validate(body) {
    const at = list(body.at, 'at', { max: 49 }).map((v, i) => num(v, `at[${i}]`, { min: 0, max: 86_400 }))
    if (!at.length) throw new BadRequest('at must list at least one cut point')
    at.forEach((t, i) => {
      if (t <= 0) throw new BadRequest(`at[${i}] must be greater than 0`)
      if (i && t <= at[i - 1]) throw new BadRequest('at must be in increasing order')
    })
    const outs = list(body.outputs, 'outputs', { max: 50 })
    if (outs.length !== at.length + 1) {
      throw new BadRequest(`outputs must have ${at.length + 1} entries (one more than at)`)
    }
    const input = await resolveInput(body.input, 'input')
    const outputs = []
    for (const [i, o] of outs.entries()) outputs.push(await resolveOutput(o, `outputs[${i}]`, VIDEO_EXT))
    if (new Set(outputs.map((o) => o.abs)).size !== outputs.length) throw new BadRequest('outputs must all differ')
    return { input, outputs, at }
  },

  async run({ input, outputs, at }, ws) {
    const src = await ws.link(input)
    const meta = await ws.probe(src)
    const last = at[at.length - 1]
    if (meta.duration > 0 && last >= meta.duration) {
      throw new BadRequest(`cut point ${last} is not before the end of the source (${meta.duration} s)`)
    }
    const bounds = [0, ...at, null]
    const pieces = []
    for (let i = 0; i + 1 < bounds.length; i += 1) {
      const stage = ws.stage(i / (bounds.length - 1), (i + 1) / (bounds.length - 1))
      pieces.push(await trimCore(stage, src, { start: bounds[i], end: bounds[i + 1] }, meta))
    }
    const result = []
    for (const [i, name] of pieces.entries()) {
      result.push({ output: outputs[i].rel, meta: await ws.probe(name) })
    }
    for (const [i, name] of pieces.entries()) await ws.publish(name, outputs[i].abs)
    return { outputs: result }
  },
}
