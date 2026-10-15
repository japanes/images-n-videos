/**
 * render — ffmpeg behind a small HTTP API, for the app container only.
 *
 * Listens on 0.0.0.0:3000 inside the compose network and is never published to
 * the host. Every file it reads or writes is a path relative to the shared
 * data volume (VF_DATA_DIR, /data in the image).
 */

import fsp from 'node:fs/promises'

import { createApp } from './lib/app.js'
import { concurrency, dataDir, scratchRoot, version } from './lib/config.js'
import * as jobs from './lib/jobs.js'
import * as log from './lib/log.js'

const host = process.env.HOST || '0.0.0.0'
const port = Number(process.env.PORT) || 3000

try {
  await fsp.mkdir(scratchRoot(), { recursive: true })
  await jobs.sweepScratch()
} catch (err) {
  // Not fatal: /health reports a missing or read-only volume.
  log.warn(null, 'scratch directory not ready', { error: err.message })
}
jobs.startTimers()

const server = createApp()
server.listen(port, host, () => {
  log.info(null, 'listening', { host, port, version: version(), data_dir: dataDir(), concurrency: concurrency() })
})

let stopping = false
function shutdown(signal) {
  if (stopping) return
  stopping = true
  log.info(null, 'shutting down', { signal })
  jobs.stopTimers()
  jobs.abortAll()
  server.close(() => process.exit(0))
  setTimeout(() => process.exit(0), 5000).unref()
}
process.on('SIGTERM', () => shutdown('SIGTERM'))
process.on('SIGINT', () => shutdown('SIGINT'))
