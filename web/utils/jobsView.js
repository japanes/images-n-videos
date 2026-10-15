/**
 * Pure helpers of the jobs page: filters, live merging, durations, error text.
 */
import { parseTs } from './format.js'

export const ACTIVE = ['queued', 'running']
export const FINISHED = ['done', 'error', 'cancelled', 'interrupted']

/** Status tabs of the page → statuses they show (the backend uses the same names). */
export const STATUS_TABS = {
  all: [],
  active: ACTIVE,
  problems: ['error', 'interrupted'],
  done: ['done'],
  cancelled: ['cancelled'],
}

/** Groups the core knows (jobs.GROUP_DEFAULTS); others show their raw name. */
export const KNOWN_GROUPS = ['image', 'avatar', 'video', 'render', 'stt', 'text', 'default']

export const STATUS_TONE = {
  queued: 'bg-slate-100 text-slate-700 dark:bg-slate-700 dark:text-slate-200',
  running: 'bg-sky-100 text-sky-800 dark:bg-sky-500/15 dark:text-sky-200',
  done: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-200',
  error: 'bg-rose-100 text-rose-800 dark:bg-rose-500/15 dark:text-rose-200',
  interrupted: 'bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-200',
  cancelled: 'bg-slate-100 text-slate-500 dark:bg-slate-700 dark:text-slate-300',
}

export const isActive = (job) => ACTIVE.includes(job?.status)

/** Would this job show under the current filters? Mirrors the backend's /list. */
export function jobMatches(job, { status = 'all', group = '', kind = '', q = '', refType = '', refId = null } = {}) {
  if (!job) return false
  const statuses = status === 'finished' ? FINISHED : (STATUS_TABS[status] ?? [status])
  if (statuses.length && !statuses.includes(job.status)) return false
  if (group && job.group_name !== group) return false
  if (kind && job.kind !== kind) return false
  if (refType && job.ref_type !== refType) return false
  if (refId !== null && refId !== undefined && refId !== '' && Number(job.ref_id) !== Number(refId)) return false
  const text = String(q || '').trim().toLowerCase()
  if (text) {
    const hay = `${job.title || ''}\n${job.kind || ''}`.toLowerCase()
    if (!hay.includes(text) && String(job.id) !== text) return false
  }
  return true
}

/**
 * Apply a live `job.updated` event to the shown list (newest first).
 * A job already shown is updated in place, even if it no longer matches the
 * filter (rows do not jump away under the cursor). A new job that matches and
 * is newer than everything shown goes on top. Returns true if anything changed.
 */
export function mergeJob(items, job, filters) {
  if (!job || job.id === undefined) return false
  const i = items.findIndex((x) => x.id === job.id)
  if (i >= 0) {
    const next = { ...items[i], ...job }
    next.cancellable = ACTIVE.includes(next.status)
    next.retryable = ['error', 'interrupted', 'cancelled'].includes(next.status)
    items.splice(i, 1, next)
    return true
  }
  if (!jobMatches(job, filters)) return false
  const newest = items.length ? items[0].id : 0
  if (items.length && job.id < newest) return false
  items.unshift({
    known: true,
    ...job,
    cancellable: ACTIVE.includes(job.status),
    retryable: ['error', 'interrupted', 'cancelled'].includes(job.status),
  })
  return true
}

/** Apply a `job.progress` event. */
export function applyProgress(items, p) {
  const job = items.find((x) => x.id === p?.id)
  if (!job) return false
  job.progress = p.progress
  job.progress_note = p.note
  return true
}

/** Seconds the job has been working (or worked), or null before it started. */
export function jobSeconds(job, nowMs = Date.now()) {
  const start = parseTs(job?.started_at)
  if (!start) return null
  const end = isActive(job) ? null : parseTs(job.finished_at)
  return Math.max(0, Math.round(((end ? end.getTime() : nowMs) - start.getTime()) / 1000))
}

/**
 * Short readable error: a localized `errors.<code>` when the app has one,
 * otherwise the text as it came (Google's wording stays verbatim).
 */
export function jobErrorText(job, t, te) {
  const code = job?.error_code
  if (code) {
    const key = `errors.${code}`
    if (te ? te(key) : t(key) !== key) return t(key, { message: job.error || '' })
  }
  if (job?.error) return job.error
  return code ? t('errors.generic', { code }) : ''
}

/** Show the raw text under "details" only when the short line hides it. */
export function hasErrorDetails(job, shortText) {
  return !!job?.error && job.error !== shortText
}

/** Percent 0–100 for the progress bar, or null when the job gave no number. */
export function progressPercent(job) {
  const v = Number(job?.progress)
  if (job?.progress === null || job?.progress === undefined || Number.isNaN(v)) return null
  return Math.max(0, Math.min(100, Math.round(v * 100)))
}
