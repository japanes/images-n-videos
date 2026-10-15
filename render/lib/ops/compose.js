/**
 * compose — several edits in one job, with no half-finished file ever
 * surfacing on the volume.
 *
 * Every step is optional; the ones present run in this fixed order, because it
 * is the only order that makes sense — reframing after burning would stretch
 * the text, and mixing before burning would be re-encoded away by the burn:
 *
 *   concat → trim → crop → burn → mix
 *
 * `concat` is the one step that brings its own sources, so it can only come
 * first and `input` is then not allowed. Each step takes the same fields as the
 * operation of the same name, minus `input`/`output`.
 */

import fsp from 'node:fs/promises'

import { BadRequest } from '../errors.js'
import * as log from '../log.js'
import { VIDEO_EXT, resolveInput, resolveOutput } from '../paths.js'
import burn from './burn.js'
import { obj } from './common.js'
import concat, { concatCore } from './concat.js'
import crop from './crop.js'
import mix from './mix.js'
import trim from './trim.js'

const STEPS = [
  ['concat', concat],
  ['trim', trim],
  ['crop', crop],
  ['burn', burn],
  ['mix', mix],
]

export default {
  name: 'compose',

  async validate(body) {
    const wanted = []
    for (const [name, op] of STEPS) {
      const raw = obj(body[name], name)
      if (raw) wanted.push({ name, op, raw })
    }
    if (!wanted.length) {
      throw new BadRequest(`compose needs at least one of ${STEPS.map(([n]) => n).join(', ')}`)
    }
    const joins = wanted[0].name === 'concat'
    if (joins && body.input !== undefined && body.input !== null) {
      throw new BadRequest('pass input or concat, not both: concat brings its own sources')
    }
    const input = joins ? null : await resolveInput(body.input, 'input')
    const steps = []
    for (const w of wanted) steps.push({ name: w.name, op: w.op, params: await w.op.parseStep(w.raw, `${w.name}.`) })
    const output = await resolveOutput(body.output, 'output', VIDEO_EXT)
    return { input, output, steps }
  },

  async run({ input, output, steps }, ws) {
    let current = input ? await ws.link(input) : null
    let joins = null
    for (const [i, s] of steps.entries()) {
      const stage = ws.stage(i / steps.length, (i + 1) / steps.length)
      const startedAt = Date.now()
      const previous = current
      if (s.name === 'concat') {
        const made = await concatCore(stage, s.params)
        current = made.name
        joins = made.joins
      } else {
        current = await s.op.core(stage, current, s.params)
      }
      // The step before is no longer needed; long films should not hold every
      // intermediate on disk at once.
      if (previous) await fsp.rm(ws.path(previous), { force: true })
      log.info(ws.batchId, 'compose step done', { step: s.name, ms: Date.now() - startedAt })
    }
    const meta = await ws.probe(current)
    await ws.publish(current, output.abs)
    const result = { output: output.rel, meta, steps: steps.map((s) => s.name) }
    if (joins) result.joins = joins
    return result
  },
}
