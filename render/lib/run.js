/**
 * Spawning ffmpeg and ffprobe.
 *
 * No shell: arguments go straight to execve, so nothing in a request can become
 * a command. Every process has a timeout and dies with SIGKILL when its job is
 * cancelled. stderr is kept as a rolling tail — ffmpeg is chatty, and only the
 * end says why it failed.
 */

import { spawn } from 'node:child_process'

import { ffmpegTimeoutMs } from './config.js'
import { Cancelled, FfmpegError } from './errors.js'

const TAIL = 8000

/** `time=00:01:02.50` → 62.5, or null. ffmpeg writes progress lines with \r. */
export function parseProgressTime(chunk) {
  const all = [...String(chunk).matchAll(/time=\s*(-?\d+):(\d{2}):(\d{2}(?:\.\d+)?)/g)]
  if (!all.length) return null
  const [, h, m, s] = all[all.length - 1]
  const seconds = Number(h) * 3600 + Number(m) * 60 + Number(s)
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : null
}

/**
 * Run a binary. Resolves `{ stdout, stderr }` (stdout only when `capture`),
 * rejects with FfmpegError on a non-zero exit or timeout, with Cancelled when
 * `signal` aborts.
 */
export function run(bin, args, { cwd, signal, capture = false, timeoutMs, onStderr } = {}) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new Cancelled())
      return
    }
    const child = spawn(bin, args, { cwd, stdio: ['ignore', capture ? 'pipe' : 'ignore', 'pipe'] })
    let stderr = ''
    const out = []
    let settled = false
    let reason = null

    const kill = (why) => {
      if (reason) return
      reason = why
      child.kill('SIGKILL')
    }
    const onAbort = () => kill('cancelled')
    signal?.addEventListener('abort', onAbort, { once: true })
    const timer = setTimeout(() => kill('timeout'), timeoutMs ?? ffmpegTimeoutMs())

    child.stderr.on('data', (chunk) => {
      stderr = (stderr + chunk.toString()).slice(-TAIL)
      if (onStderr) onStderr(chunk)
    })
    if (capture) child.stdout.on('data', (chunk) => out.push(chunk))

    const finish = (err, value) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      signal?.removeEventListener('abort', onAbort)
      if (err) reject(err)
      else resolve(value)
    }

    child.on('error', (err) => {
      finish(new FfmpegError(`${bin} could not start: ${err.message}`, { stderr }))
    })
    child.on('close', (code) => {
      if (reason === 'cancelled') return finish(new Cancelled())
      if (reason === 'timeout') {
        return finish(new FfmpegError(`${bin} timed out`, { exitCode: code, stderr }))
      }
      if (code !== 0) {
        const last = stderr.trim().split('\n').filter(Boolean).pop() || ''
        return finish(new FfmpegError(`${bin} exited with code ${code}: ${last.slice(0, 300)}`, { exitCode: code, stderr }))
      }
      finish(null, { stdout: capture ? Buffer.concat(out).toString() : '', stderr })
    })
  })
}

/**
 * ffmpeg with the flags every call wants. `duration` (seconds of output
 * expected) turns the `time=` progress lines into a 0..1 fraction for
 * `onProgress`.
 */
export function ffmpeg(args, { cwd, signal, capture = false, timeoutMs, duration, onProgress } = {}) {
  const onStderr = onProgress && duration > 0
    ? (chunk) => {
      const t = parseProgressTime(chunk)
      if (t !== null) onProgress(Math.min(1, t / duration))
    }
    : undefined
  return run('ffmpeg', ['-hide_banner', '-nostdin', '-y', ...args], { cwd, signal, capture, timeoutMs, onStderr })
}

export function ffprobe(args, { cwd, signal, timeoutMs = 60_000 } = {}) {
  return run('ffprobe', args, { cwd, signal, capture: true, timeoutMs })
}

let versionCache = null

/** The version token from `ffmpeg -version`, e.g. "5.1.6-0+deb12u1". Throws if ffmpeg is missing. */
export async function ffmpegVersion() {
  if (versionCache) return versionCache
  const { stdout } = await run('ffmpeg', ['-version'], { capture: true, timeoutMs: 10_000 })
  const first = stdout.split('\n')[0] || ''
  const match = /ffmpeg version (\S+)/.exec(first)
  versionCache = match ? match[1] : first.trim()
  return versionCache
}
