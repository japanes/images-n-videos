/**
 * The job queue: in memory, first in first out, RENDER_CONCURRENCY at a time.
 *
 * Nothing survives a restart, and that is fine: the app owns the job records
 * and resubmits; render only owns the ffmpeg processes. A finished job stays
 * readable for an hour so a poller that blinked does not lose the result.
 *
 * Scratch: every job (and every synchronous call that needs files) works in
 * `<data>/cache/render/<id>/`, which is removed when it ends, whatever happened.
 * A crash can still leave a directory behind, so a sweeper removes any that do
 * not belong to live work — at startup and every five minutes.
 */

import { randomUUID } from 'node:crypto'
import fsp from 'node:fs/promises'
import path from 'node:path'

import { concurrency, jobTtlMs, scratchRoot } from './config.js'
import { Cancelled, errorBody } from './errors.js'
import * as log from './log.js'

const jobs = new Map()
const queue = []
let running = 0
const liveScratch = new Set()
let timers = []

function now() {
  return new Date().toISOString()
}

export function toJSON(job) {
  return {
    id: job.id,
    op: job.op,
    status: job.status,
    progress: job.progress,
    result: job.result,
    error: job.error,
    batch_id: job.batchId,
    created_at: job.createdAt,
    started_at: job.startedAt,
    finished_at: job.finishedAt,
  }
}

/**
 * Queue `work(ctx)`. `ctx` carries `{ jobId, batchId, signal, progress(f) }`.
 * Returns the job record.
 */
export function submit(op, work, { batchId = null } = {}) {
  const job = {
    id: randomUUID(),
    op,
    status: 'queued',
    progress: null,
    result: null,
    error: null,
    batchId,
    createdAt: now(),
    startedAt: null,
    finishedAt: null,
    finishedMs: null,
    work,
    controller: null,
  }
  jobs.set(job.id, job)
  queue.push(job)
  log.info(batchId, 'job queued', { job_id: job.id, op, queued: queue.length })
  pump()
  return job
}

export function get(id) {
  return jobs.get(id) || null
}

function finish(job, status, { result = null, error = null } = {}) {
  job.status = status
  job.result = result
  job.error = error
  job.finishedAt = now()
  job.finishedMs = Date.now()
  job.work = null
}

function pump() {
  while (running < concurrency() && queue.length) {
    const job = queue.shift()
    start(job)
  }
}

function start(job) {
  running += 1
  job.status = 'running'
  job.startedAt = now()
  job.progress = 0
  job.controller = new AbortController()
  const startedMs = Date.now()
  const ctx = {
    jobId: job.id,
    batchId: job.batchId,
    signal: job.controller.signal,
    progress(fraction) {
      if (job.status !== 'running' || !Number.isFinite(fraction)) return
      const f = Math.max(0, Math.min(1, fraction))
      // Never backwards: a multi-step op restarting its own counter should not
      // make the bar jump back.
      if (f > (job.progress ?? 0)) job.progress = Number(f.toFixed(3))
    },
  }
  log.info(job.batchId, 'job started', { job_id: job.id, op: job.op })

  Promise.resolve()
    .then(() => {
      // Cancelled between being picked and getting here: never start the work.
      if (ctx.signal.aborted) throw new Cancelled()
      return job.work(ctx)
    })
    .then((result) => {
      if (job.status !== 'running') return
      job.progress = 1
      finish(job, 'done', { result })
      log.info(job.batchId, 'job done', { job_id: job.id, op: job.op, ms: Date.now() - startedMs })
    })
    .catch((err) => {
      if (job.status !== 'running') return
      if (err instanceof Cancelled || job.controller.signal.aborted) {
        finish(job, 'cancelled')
        return
      }
      const body = errorBody(err)
      finish(job, 'error', { error: body })
      log.error(job.batchId, 'job failed', {
        job_id: job.id,
        op: job.op,
        code: body.code,
        error: body.message,
        stderr_tail: body.stderr_tail ? body.stderr_tail.slice(-600) : undefined,
        ms: Date.now() - startedMs,
      })
    })
    .finally(() => {
      running -= 1
      pump()
    })
}

/**
 * Cancel a job. A queued one is simply dropped; a running one has its ffmpeg
 * killed. The status flips to `cancelled` immediately; the slot frees as soon
 * as the process is gone. A finished job is left as it is.
 */
export function cancel(id) {
  const job = jobs.get(id)
  if (!job) return null
  if (job.status === 'queued') {
    const at = queue.indexOf(job)
    if (at !== -1) queue.splice(at, 1)
    finish(job, 'cancelled')
    log.info(job.batchId, 'job cancelled', { job_id: job.id, op: job.op, was: 'queued' })
  } else if (job.status === 'running') {
    finish(job, 'cancelled')
    job.controller.abort()
    log.info(job.batchId, 'job cancelled', { job_id: job.id, op: job.op, was: 'running' })
  }
  return job
}

export function stats() {
  return { running, queued: queue.length }
}

/** Forget finished jobs older than the TTL. */
export function expire() {
  const cutoff = Date.now() - jobTtlMs()
  for (const [id, job] of jobs) {
    if (job.finishedMs !== null && job.finishedMs < cutoff) jobs.delete(id)
  }
}

/**
 * Run `fn(dir)` with a fresh scratch directory that is removed afterwards.
 * `id` is the job id, or a throwaway one for synchronous calls.
 */
export async function withScratch(id, fn) {
  const name = id || `sync-${randomUUID()}`
  const dir = path.join(scratchRoot(), name)
  liveScratch.add(name)
  try {
    await fsp.mkdir(dir, { recursive: true })
    return await fn(dir)
  } finally {
    await fsp.rm(dir, { recursive: true, force: true }).catch((err) => {
      log.warn(null, 'scratch cleanup failed', { dir: name, error: err.message })
    })
    liveScratch.delete(name)
  }
}

/** Remove scratch directories that no live job or call owns. */
export async function sweepScratch() {
  const root = scratchRoot()
  let entries
  try {
    entries = await fsp.readdir(root)
  } catch (_) {
    return 0
  }
  let removed = 0
  for (const name of entries) {
    if (liveScratch.has(name)) continue
    await fsp.rm(path.join(root, name), { recursive: true, force: true }).catch(() => {})
    removed += 1
  }
  if (removed) log.info(null, 'stale scratch removed', { count: removed })
  return removed
}

/** Start the periodic expiry and sweep. Returns nothing; `stop()` undoes it. */
export function startTimers() {
  stopTimers()
  const expiry = setInterval(expire, 60_000)
  const sweep = setInterval(() => { sweepScratch().catch(() => {}) }, 5 * 60_000)
  expiry.unref()
  sweep.unref()
  timers = [expiry, sweep]
}

export function stopTimers() {
  for (const t of timers) clearInterval(t)
  timers = []
}

/** Kill everything (shutdown). */
export function abortAll() {
  for (const job of jobs.values()) {
    if (job.status === 'queued' || job.status === 'running') cancel(job.id)
  }
}

/** Tests only: forget every job. Running work is aborted first. */
export function _reset() {
  abortAll()
  jobs.clear()
  queue.length = 0
}
