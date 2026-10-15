/**
 * Media library helpers (module 10). Pure functions, so tests can import them
 * directly; the page and components use them through Nuxt auto-imports.
 *
 * Every export starts with `media` because composables are auto-imported
 * into the whole app.
 *
 * Uploading from another screen:
 *
 *   const item = await mediaUploadFile(file, { kinds: ['image'], onProgress: (p) => { … } })
 *
 * It posts to `POST /api/media/upload?kinds=…` and resolves with the library
 * item (or rejects with an ApiError, shown with `apiErrorText`).
 */
import { ApiError } from './useApi.js'

export const MEDIA_KINDS = ['image', 'video', 'audio']
export const MEDIA_SOURCES = ['upload', 'generation', 'avatar', 'editor', 'export']
export const MEDIA_PAGE_SIZE = 40

const DAY_RE = /^(\d{4})-(\d{2})-(\d{2})$/

/** Filters of the library screen from the route query (anything odd is dropped). */
export function mediaFiltersFromQuery(q = {}) {
  const str = (v) => (typeof v === 'string' ? v : '')
  const kind = MEDIA_KINDS.includes(q.kind) ? q.kind : ''
  const source = MEDIA_SOURCES.includes(q.source) ? q.source : ''
  const from = DAY_RE.test(str(q.from)) ? q.from : ''
  const to = DAY_RE.test(str(q.to)) ? q.to : ''
  const page = Number.parseInt(str(q.page), 10)
  return { kind, source, q: str(q.q).trim(), from, to, page: page > 0 ? page : 1 }
}

/** Route query for the filters; defaults are left out so links stay short. */
export function mediaFiltersToQuery(f) {
  const out = {}
  for (const key of ['kind', 'source', 'q', 'from', 'to']) if (f[key]) out[key] = f[key]
  if (f.page > 1) out.page = String(f.page)
  return out
}

export function mediaHasFilters(f) {
  return !!(f.kind || f.source || f.q || f.from || f.to)
}

/**
 * Start of a local calendar day as a UTC ISO timestamp: the person picks days
 * in their own time zone, the server stores UTC. `addDays` moves the day.
 */
export function mediaLocalDayStart(day, addDays = 0) {
  const m = DAY_RE.exec(day || '')
  if (!m) return null
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]) + addDays)
  return Number.isNaN(d.getTime()) ? null : d.toISOString()
}

/** Query for `GET /api/media/files`. The "to" day is included: the server bound is exclusive. */
export function mediaListParams(f, limit = MEDIA_PAGE_SIZE) {
  const params = { page: f.page || 1, limit }
  if (f.kind) params.kind = f.kind
  if (f.source) params.source = f.source
  if (f.q) params.q = f.q
  const from = mediaLocalDayStart(f.from)
  const to = mediaLocalDayStart(f.to, 1)
  if (from) params.date_from = from
  if (to) params.date_to = to
  return params
}

/** What the person sees as the file's name. */
export function mediaDisplayName(item) {
  if (!item) return ''
  return item.title || item.original_name || `#${item.id}`
}

/** A link of a usage only when it is a path inside the app. */
export function mediaUsageLink(usage) {
  const url = usage?.url
  return typeof url === 'string' && url.startsWith('/') && !url.startsWith('//') ? url : null
}

export function mediaKindOfMime(mime) {
  const head = String(mime || '').split('/')[0]
  return ['image', 'video', 'audio', 'font'].includes(head) ? head : null
}

// Types the browser may report that the server refuses anyway (it checks the bytes).
const REFUSED_MIMES = ['image/heic', 'image/heif', 'image/avif', 'image/svg+xml', 'video/x-matroska']

/**
 * Quick check before sending, from what the browser knows (type and size).
 * Returns null or `{ code, details }` in the shape of a backend error. The
 * server checks again by the file's bytes, so an unknown browser type passes.
 */
export function mediaCheckFile(file, limits, kinds = MEDIA_KINDS) {
  if (!file || !file.size) return { code: 'upload_empty', details: {} }
  const mime = String(file.type || '').toLowerCase()
  if (REFUSED_MIMES.includes(mime)) return { code: 'unsupported_type', details: { kinds } }
  const kind = mediaKindOfMime(mime)
  if (kind && !kinds.includes(kind)) return { code: 'unsupported_type', details: { kinds } }
  const maxMb = limits?.max_mb || {}
  const limit = kind ? maxMb[kind] : Math.max(0, ...kinds.map((k) => Number(maxMb[k]) || 0))
  if (limit && file.size > limit * 1024 * 1024) {
    return { code: 'file_too_large', details: { kind: kind || '', max_mb: limit } }
  }
  return null
}

function xhrError(xhr) {
  let body = null
  try { body = JSON.parse(xhr.responseText) } catch { /* not JSON */ }
  const e = body?.error
  if (e && typeof e === 'object') {
    return new ApiError({ code: e.code, message: e.message, details: e.details, status: xhr.status })
  }
  return new ApiError({ code: xhr.status ? `http_${xhr.status}` : 'network', status: xhr.status })
}

/**
 * Upload one file with progress (fetch cannot report upload progress).
 * opts: { kinds?: string[], title?, onProgress?(fraction), signal?: AbortSignal }
 */
export function mediaUploadFile(file, { kinds, title, onProgress, signal } = {}) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new ApiError({ code: 'aborted' }))
      return
    }
    const xhr = new XMLHttpRequest()
    const query = kinds && kinds.length ? `?kinds=${encodeURIComponent(kinds.join(','))}` : ''
    xhr.open('POST', `/api/media/upload${query}`)
    xhr.responseType = 'text'
    if (onProgress) {
      xhr.upload.onprogress = (e) => { if (e.lengthComputable && e.total) onProgress(e.loaded / e.total) }
    }
    const onAbort = () => xhr.abort()
    signal?.addEventListener('abort', onAbort, { once: true })
    const done = () => signal?.removeEventListener('abort', onAbort)
    xhr.onload = () => {
      done()
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText))
        } catch {
          reject(new ApiError({ code: 'network', status: xhr.status }))
        }
      } else {
        reject(xhrError(xhr))
      }
    }
    xhr.onerror = () => { done(); reject(new ApiError({ code: 'network' })) }
    xhr.onabort = () => { done(); reject(new ApiError({ code: 'aborted' })) }
    const form = new FormData()
    form.append('file', file)
    if (title) form.append('title', title)
    xhr.send(form)
  })
}

/** Video or sound still being processed (poster, preview, length). */
export function mediaIngestBusy(item) {
  const status = item?.ingest?.status
  return status === 'queued' || status === 'running'
}

export function mediaIngestFailed(item) {
  const status = item?.ingest?.status
  return status === 'error' || status === 'interrupted'
}

/** Apply a `file.updated` event (core file fields) to an item in the list. */
export function mediaMergeFile(items, file) {
  const i = items.findIndex((x) => x.id === file?.id)
  if (i < 0) return false
  items[i] = { ...items[i], ...file }
  return true
}

/** Apply a `job.updated` event of a `media.ingest` job to the file it belongs to. */
export function mediaApplyIngestJob(items, job) {
  if (job?.kind !== 'media.ingest' || job.ref_type !== 'file') return false
  const i = items.findIndex((x) => x.id === job.ref_id)
  if (i < 0) return false
  items[i] = {
    ...items[i],
    ingest: { ...(items[i].ingest || {}), status: job.status, error_code: job.error_code, error: job.error },
  }
  return true
}

/** Readable "1920 × 1080". */
export function mediaSizeText(item) {
  return item?.width && item?.height ? `${item.width} × ${item.height}` : ''
}
