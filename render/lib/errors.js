/**
 * The error kinds the API knows how to answer. Anything else is a 500 `internal`.
 */

export class HttpError extends Error {
  constructor(status, code, message) {
    super(message)
    this.name = 'HttpError'
    this.status = status
    this.code = code
  }
}

export class BadRequest extends HttpError {
  constructor(message) {
    super(400, 'bad_request', message)
    this.name = 'BadRequest'
  }
}

export class NotFound extends HttpError {
  constructor(message) {
    super(404, 'not_found', message)
    this.name = 'NotFound'
  }
}

export class FfmpegError extends Error {
  constructor(message, { exitCode = null, stderr = '' } = {}) {
    super(message)
    this.name = 'FfmpegError'
    this.status = 500
    this.code = 'ffmpeg_failed'
    this.exitCode = exitCode
    this.stderr = stderr
  }
}

/** Thrown inside a job when DELETE /jobs/:id killed it. Never reaches HTTP. */
export class Cancelled extends Error {
  constructor() {
    super('cancelled')
    this.name = 'Cancelled'
    this.code = 'cancelled'
  }
}

export const STDERR_TAIL = 2000

/** The body every error response and every failed job carries. */
export function errorBody(err) {
  if (err instanceof FfmpegError) {
    return { code: err.code, message: err.message, stderr_tail: String(err.stderr || '').slice(-STDERR_TAIL) }
  }
  if (err instanceof HttpError) return { code: err.code, message: err.message, stderr_tail: null }
  return { code: 'internal', message: err?.message || String(err), stderr_tail: null }
}

export function statusOf(err) {
  return err instanceof HttpError || err instanceof FfmpegError ? err.status : 500
}
