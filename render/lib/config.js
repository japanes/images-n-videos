/**
 * Environment, read on every call rather than once at import.
 *
 * The tests point VF_DATA_DIR at a throwaway directory before they start the
 * app; reading lazily means no module has to be imported in a particular order
 * for that to work.
 */

import path from 'node:path'

export function dataDir() {
  return path.resolve(process.env.VF_DATA_DIR || '/data')
}

/** Per-job scratch directories live here, on the same volume as the outputs. */
export function scratchRoot() {
  return path.join(dataDir(), 'cache', 'render')
}

/** Brand fonts the user (or the app) dropped on the volume. */
export function fontsDir() {
  return path.join(dataDir(), 'fonts')
}

export function version() {
  return process.env.VF_VERSION || '0.0.0-dev'
}

export function concurrency() {
  const n = Number(process.env.RENDER_CONCURRENCY)
  return Number.isInteger(n) && n >= 1 && n <= 16 ? n : 2
}

/** How long a finished job stays visible at GET /jobs/:id. */
export function jobTtlMs() {
  const n = Number(process.env.RENDER_JOB_TTL_MS)
  return Number.isFinite(n) && n > 0 ? n : 60 * 60 * 1000
}

/** Hard ceiling for one ffmpeg process. A stuck encode must not hold a slot forever. */
export function ffmpegTimeoutMs() {
  const n = Number(process.env.RENDER_FFMPEG_TIMEOUT_MS)
  return Number.isFinite(n) && n > 0 ? n : 30 * 60 * 1000
}
