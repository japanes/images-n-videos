/**
 * probe — what a media file is: length, size, frame rate, streams. Answered
 * inline: the app calls it right after an upload or a generation, and nobody
 * should wait on a queue for it.
 */

import { resolveInput } from '../paths.js'
import { probeFile } from './common.js'

export default {
  name: 'probe',
  sync: true,
  scratch: false,

  async validate(body) {
    return { input: await resolveInput(body.input, 'input') }
  },

  async run(params) {
    return probeFile(params.input)
  },
}
