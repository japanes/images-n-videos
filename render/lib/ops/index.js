/**
 * The operation table. Each op is `{ validate(body) → params, run(params, ws) }`:
 * `validate` checks the request and resolves every path (so a bad request is a
 * 400/404 before anything is queued), `run` does the work in a scratch
 * workspace and returns the result body.
 */

import burn from './burn.js'
import compose from './compose.js'
import concat from './concat.js'
import crop from './crop.js'
import frame from './frame.js'
import match from './match.js'
import mix from './mix.js'
import preview from './preview.js'
import probe from './probe.js'
import split from './split.js'
import splitAudio from './split-audio.js'
import trim from './trim.js'

/** Answered in the request itself: quick, and the caller waits for them. */
export const SYNC = { probe, frame, match }

/** Queued: `202 { job_id }`, then poll GET /jobs/:id. */
export const JOBS = {
  preview,
  trim,
  split,
  crop,
  concat,
  compose,
  burn,
  mix,
  'split-audio': splitAudio,
}
