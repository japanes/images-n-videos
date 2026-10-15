/**
 * The HTTP API. Plain node:http: a dozen routes do not need a framework, and
 * zero runtime dependencies means nothing to audit or update in this image.
 *
 *   GET    /health
 *   POST   /probe | /frame | /match              → 200, answered inline
 *   POST   /preview | /trim | /split | /crop |
 *          /concat | /compose | /burn | /mix |
 *          /split-audio                          → 202 { job_id }
 *   GET    /jobs/:id                             → the job
 *   DELETE /jobs/:id                             → cancel it
 *
 * Errors are always `{ error: { code, message, stderr_tail } }`.
 */

import fs from 'node:fs'
import fsp from 'node:fs/promises'
import http from 'node:http'

import { dataDir, version } from './config.js'
import { BadRequest, Cancelled, HttpError, NotFound, errorBody, statusOf } from './errors.js'
import * as jobs from './jobs.js'
import * as log from './log.js'
import { Workspace } from './ops/common.js'
import { JOBS, SYNC } from './ops/index.js'
import { ffmpegVersion } from './run.js'

const BODY_LIMIT = 2 * 1024 * 1024

/** X-Batch-Id is echoed into logs and headers, so only a tame subset passes. */
export function cleanBatchId(value) {
  if (typeof value !== 'string') return null
  const cleaned = value.trim().replace(/[^\w.:-]/g, '_').slice(0, 128)
  return cleaned || null
}

function send(res, status, body, batchId) {
  const text = JSON.stringify(body)
  const headers = {
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(text),
    'cache-control': 'no-store',
  }
  if (batchId) headers['x-batch-id'] = batchId
  res.writeHead(status, headers)
  res.end(text)
}

function readJson(req) {
  return new Promise((resolve, reject) => {
    const chunks = []
    let size = 0
    let tooBig = false
    req.on('data', (chunk) => {
      size += chunk.length
      if (size > BODY_LIMIT) {
        tooBig = true
        chunks.length = 0
        return
      }
      if (!tooBig) chunks.push(chunk)
    })
    req.on('error', reject)
    req.on('end', () => {
      if (tooBig) {
        reject(new BadRequest('request body is larger than 2 MB'))
        return
      }
      const text = Buffer.concat(chunks).toString('utf8').trim()
      if (!text) {
        resolve({})
        return
      }
      let parsed
      try {
        parsed = JSON.parse(text)
      } catch (_) {
        reject(new BadRequest('request body is not valid JSON'))
        return
      }
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        reject(new BadRequest('request body must be a JSON object'))
        return
      }
      resolve(parsed)
    })
  })
}

async function health() {
  const body = { ok: true, version: version(), ffmpeg: null, queue: jobs.stats() }
  try {
    body.ffmpeg = await ffmpegVersion()
  } catch (err) {
    body.ok = false
    body.error = `ffmpeg is not available: ${err.message}`
  }
  try {
    await fsp.access(dataDir(), fs.constants.W_OK)
  } catch (_) {
    body.ok = false
    body.error = body.error || 'data directory is missing or not writable'
  }
  return body
}

async function runSync(op, params, batchId, res) {
  // A caller that hangs up does not get to leave ffmpeg running.
  const controller = new AbortController()
  const onClose = () => {
    if (!res.writableEnded) controller.abort()
  }
  res.on('close', onClose)
  try {
    if (op.scratch === false) return await op.run(params, null)
    return await jobs.withScratch(null, (dir) => op.run(params, new Workspace({ dir, signal: controller.signal, batchId })))
  } finally {
    res.off('close', onClose)
  }
}

function submitJob(name, op, params, batchId) {
  return jobs.submit(name, (ctx) => jobs.withScratch(ctx.jobId, (dir) => op.run(params, new Workspace({
    dir,
    signal: ctx.signal,
    onProgress: ctx.progress,
    batchId: ctx.batchId,
  }))), { batchId })
}

async function route(req, res, batchId) {
  const url = new URL(req.url, 'http://render')
  const parts = url.pathname.split('/').filter(Boolean)
  const method = req.method

  if (url.pathname === '/health') {
    if (method !== 'GET') throw new HttpError(405, 'method_not_allowed', 'use GET')
    const body = await health()
    return [body.ok ? 200 : 503, body]
  }

  if (parts[0] === 'jobs' && parts.length === 2) {
    if (method === 'GET') {
      const job = jobs.get(parts[1])
      if (!job) throw new NotFound('no such job (unknown, or finished more than an hour ago)')
      return [200, jobs.toJSON(job)]
    }
    if (method === 'DELETE') {
      const job = jobs.cancel(parts[1])
      if (!job) throw new NotFound('no such job (unknown, or finished more than an hour ago)')
      return [200, jobs.toJSON(job)]
    }
    throw new HttpError(405, 'method_not_allowed', 'use GET or DELETE')
  }

  if (parts.length === 1 && (Object.hasOwn(SYNC, parts[0]) || Object.hasOwn(JOBS, parts[0]))) {
    if (method !== 'POST') throw new HttpError(405, 'method_not_allowed', 'use POST')
    const body = await readJson(req)
    if (Object.hasOwn(SYNC, parts[0])) {
      const op = SYNC[parts[0]]
      const params = await op.validate(body)
      return [200, await runSync(op, params, batchId, res)]
    }
    const op = JOBS[parts[0]]
    const params = await op.validate(body)
    const job = submitJob(parts[0], op, params, batchId)
    return [202, { job_id: job.id }]
  }

  throw new NotFound(`no such route: ${method} ${url.pathname}`)
}

export function createApp() {
  return http.createServer((req, res) => {
    const startedAt = Date.now()
    const batchId = cleanBatchId(req.headers['x-batch-id'])
    // Health checks and job polls arrive several times a second while a clip
    // renders; a line each would bury the rest. Jobs log their own start and
    // end, and a failed poll is still logged below.
    const quiet = req.method === 'GET' && (req.url === '/health' || req.url.startsWith('/jobs/'))
    route(req, res, batchId)
      .then(([status, body]) => {
        send(res, status, body, batchId)
        if (!quiet) log.info(batchId, 'request', { method: req.method, path: req.url, status, ms: Date.now() - startedAt })
      })
      .catch((err) => {
        if (err instanceof Cancelled) {
          // The caller hung up; there is nobody to answer.
          log.info(batchId, 'request abandoned', { method: req.method, path: req.url, ms: Date.now() - startedAt })
          if (!res.headersSent) res.destroy()
          return
        }
        const status = statusOf(err)
        const body = errorBody(err)
        if (!res.headersSent) send(res, status, { error: body }, batchId)
        const level = status >= 500 ? 'error' : 'info'
        log[level](batchId, 'request failed', {
          method: req.method,
          path: req.url,
          status,
          code: body.code,
          error: body.message,
          stderr_tail: body.stderr_tail ? body.stderr_tail.slice(-600) : undefined,
          ms: Date.now() - startedAt,
        })
      })
  })
}
