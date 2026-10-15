/**
 * JSON lines to stdout, nothing else.
 *
 * `docker compose logs render` is the only place these go: no log files on the
 * volume. Every line carries the batch id the app sent in X-Batch-Id, so one
 * grep follows a clip through app and render.
 *
 * Never logged: subtitle text, file contents, environment. Relative paths on
 * the data volume are fine — they are the app's own file names.
 *
 * RENDER_LOG_LEVEL (info | warn | error | silent, default info) drops the
 * quieter lines; the tests run with `silent` unless told otherwise.
 */

const LEVELS = { info: 10, warn: 20, error: 30, silent: 100 }

function threshold() {
  return LEVELS[String(process.env.RENDER_LOG_LEVEL || 'info').toLowerCase()] ?? LEVELS.info
}

function write(level, batchId, msg, extra = {}) {
  if (LEVELS[level] < threshold()) return
  const line = { ts: new Date().toISOString(), level, svc: 'render', batch_id: batchId || null, msg }
  for (const [key, value] of Object.entries(extra)) {
    if (value !== undefined) line[key] = value
  }
  let text
  try {
    text = JSON.stringify(line)
  } catch (_) {
    text = JSON.stringify({ ts: line.ts, level, svc: 'render', batch_id: line.batch_id, msg })
  }
  process.stdout.write(`${text}\n`)
}

export const info = (batchId, msg, extra) => write('info', batchId, msg, extra)
export const warn = (batchId, msg, extra) => write('warn', batchId, msg, extra)
export const error = (batchId, msg, extra) => write('error', batchId, msg, extra)
