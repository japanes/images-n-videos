/**
 * Pure helpers of the image studio (module 04): limits, frame states, sizes,
 * the region box, overrides and error texts. Nothing here knows a model id.
 *
 * Every export starts with `studio` / `STUDIO_` because Nuxt auto-imports
 * everything in web/utils and names must not clash with other modules.
 */
import { apiErrorText } from './apiErrorText.js'

// Mirrors of the backend limits (app/vf/modules/studio/common.py).
export const STUDIO_ASPECTS = ['1:1', '4:5', '3:4', '2:3', '9:16', '5:4', '4:3', '3:2', '16:9', '21:9']
export const STUDIO_SIZES = ['1K', '2K', '4K']
export const STUDIO_MAX_FRAMES = 10
export const STUDIO_MAX_PICTURES = 14
export const STUDIO_LIMITS = { title: 120, brief: 4000, edit: 2000, feedback: 2000, focus: 300 }
export const STUDIO_BUSY = ['queued', 'drawing']
export const STUDIO_STATUSES = ['empty', 'queued', 'drawing', 'waiting', 'done', 'error']
export const STUDIO_IMAGE_ACCEPT = 'image/png,image/jpeg,image/webp'

// Error codes the studio API answers with (its own texts are in studio.errors.*).
export const STUDIO_ERROR_CODES = [
  'empty_file', 'bad_image_type', 'bad_file', 'too_many_pictures', 'frame_busy', 'frame_no_picture',
  'edit_text_required', 'pilot_not_ready', 'too_many_frames', 'too_many_images', 'bad_aspect', 'bad_size',
  'version_unknown', 'brief_required', 'too_many_text_blocks', 'bad_style', 'no_kit',
  'last_frame', 'bad_order', 'model_wrong_kind', 'nothing_to_export', 'stuck',
]

// Why "Generate all" left a frame out (skipped[].reason) besides plain error codes.
export const STUDIO_SKIP_REASONS = ['not_generated', 'frame_busy', 'pilot_not_ready']

// Where a frame's picture came from (frame.source, versions[].source).
export const STUDIO_SOURCES = ['generated', 'upload', 'library', 'avatar', 'video_frame', 'editor']

const has = (t, te, key) => (te ? te(key) : t(key) !== key)

/** Error text: the studio's own `studio.errors.<code>` first, then the app-wide one. */
export function studioErrorText(err, t, te) {
  const key = `studio.errors.${err?.code || 'unknown'}`
  if (has(t, te, key)) return t(key, { ...(err?.details || {}), message: err?.message || '' })
  return apiErrorText(err, t, te)
}

/** Text of a skip reason or a frame error code; the raw code when nothing knows it. */
export function studioReasonText(reason, t, te) {
  for (const key of [`studio.skip.${reason}`, `studio.errors.${reason}`, `errors.${reason}`]) {
    if (reason && has(t, te, key)) return t(key, { message: '' })
  }
  return String(reason || '')
}

/**
 * A failed frame's error: `text` in the person's language when the code is
 * known, `detail` with Google's own words (verbatim) when there are any.
 * The studio's own codes carry only an English copy of the text, so no detail.
 */
export function studioFrameError(frame, t, te) {
  const code = frame?.error_code || ''
  const raw = String(frame?.error_text || '').trim()
  const known = code && [`studio.skip.${code}`, `studio.errors.${code}`, `errors.${code}`].some((k) => has(t, te, k))
  if (!known) return { text: raw || code, detail: '' }
  const text = studioReasonText(code, t, te)
  return { text, detail: STUDIO_ERROR_CODES.includes(code) || raw === text ? '' : raw }
}

export function studioFrameBusy(frame) {
  return STUDIO_BUSY.includes(frame?.status)
}

/** 'empty' | 'queued' | 'drawing' | 'waiting' (Google asked to wait) | 'done' | 'error'. */
export function studioFrameState(frame) {
  const status = frame?.status || 'empty'
  if (status === 'drawing' && frame?.waiting) return 'waiting'
  return STUDIO_STATUSES.includes(status) ? status : 'empty'
}

/** { done, total, busy, errors } over a work's frames. */
export function studioWorkProgress(work) {
  const frames = work?.frames || []
  const out = { done: 0, total: frames.length, busy: 0, errors: 0 }
  for (const f of frames) {
    if (f.file_id) out.done++
    if (studioFrameBusy(f)) out.busy++
    if (f.status === 'error') out.errors++
  }
  return out
}

/** Sizes the model can draw, from its registry caps (1K when it says nothing). */
export function studioSizesFor(model) {
  const allowed = model?.caps?.allowed_resolutions
  const list = Array.isArray(allowed) ? STUDIO_SIZES.filter((s) => allowed.includes(s)) : []
  return list.length ? list : ['1K']
}

/** Image models a person can pick: on, not dropped from the registry. */
export function studioModelChoices(models) {
  return (models || []).filter((m) => m.kind === 'image' && m.enabled !== false && !m.removed)
}

/** '4:5' -> '4 / 5' for the CSS aspect-ratio property ('1 / 1' when unknown). */
export function studioAspectRatio(aspect) {
  const m = String(aspect || '').match(/^(\d+):(\d+)$/)
  return m ? `${m[1]} / ${m[2]}` : '1 / 1'
}

export function studioFileUrl(id) {
  return id ? `/files/${id}` : ''
}

export function studioFileThumb(id, width = 480) {
  return id ? `/files/${id}?w=${width}` : ''
}

/**
 * A short string that changes whenever the work or any frame changes. Put it in
 * price requests as `rev` so the price is asked again after a save.
 */
export function studioWorkRevision(work) {
  if (!work) return ''
  const frames = (work.frames || []).map((f) => `${f.id}:${f.updated_at || ''}:${f.status || ''}`)
  return [work.updated_at || '', ...frames].join('|')
}

/** Does a `studio.updated` event concern this work? */
export function studioEventMatches(data, workId) {
  if (!data || workId == null) return false
  return Number(data.work_id) === Number(workId)
}

/** Copy of `ids` with the one at `from` moved to `to` (out of range -> unchanged copy). */
export function studioMoveIds(ids, from, to) {
  const out = [...(ids || [])]
  if (from === to || from < 0 || to < 0 || from >= out.length || to >= out.length) return out
  const [id] = out.splice(from, 1)
  out.splice(to, 0, id)
  return out
}

/** Add or remove `id`; adding past `max` leaves the list as it was. */
export function studioTogglePicked(list, id, max = Infinity) {
  const out = [...(list || [])]
  const at = out.indexOf(id)
  if (at >= 0) out.splice(at, 1)
  else if (out.length < max) out.push(id)
  return out
}

const clamp01 = (v) => Math.min(1, Math.max(0, Number(v) || 0))

/**
 * Box between two points given as fractions of the picture ({x, y} in 0..1).
 * Null when it is too small to mean anything (under 1% either way).
 */
export function studioBoxFromPoints(a, b) {
  if (!a || !b) return null
  const x1 = clamp01(Math.min(a.x, b.x))
  const y1 = clamp01(Math.min(a.y, b.y))
  const x2 = clamp01(Math.max(a.x, b.x))
  const y2 = clamp01(Math.max(a.y, b.y))
  const w = x2 - x1
  const h = y2 - y1
  if (w < 0.01 || h < 0.01) return null
  const r = (v) => Math.round(v * 10000) / 10000
  return { x: r(x1), y: r(y1), w: r(w), h: r(h) }
}

/** CSS for an absolutely placed box over the picture. */
export function studioBoxStyle(box) {
  if (!box) return { display: 'none' }
  const pct = (v) => `${clamp01(v) * 100}%`
  return { left: pct(box.x), top: pct(box.y), width: pct(box.w), height: pct(box.h) }
}

/** Copy of a frame's overrides with `key` set; `undefined` removes it (the frame follows the work again). */
export function studioOverridesWith(overrides, key, value) {
  const out = { ...(overrides || {}) }
  if (value === undefined) delete out[key]
  else out[key] = value
  return out
}

/** Price request for a frame action; `rev` makes the price follow saved changes. */
export function studioEstimateRequest(action, { work, frame, ...rest } = {}) {
  const req = { action, ...rest }
  if (work) { req.work_id = work.id; req.rev = studioWorkRevision(work) }
  if (frame) { req.frame_id = frame.id; req.frame_rev = `${frame.updated_at || ''}:${frame.status || ''}` }
  return req
}

/** A library style's category name in the person's language (the library keeps Russian, uk/en when known). */
export function studioCategoryTitle(style, locale) {
  const path = style?.category_path || []
  const last = path[path.length - 1]
  if (!last) return ''
  return last[`title_${locale}`] || last.title || last.slug || ''
}

/**
 * The photo style picker's lists: `categories` in the order they first appear
 * and `groups` of styles that match the search words and the picked category
 * ('' means all). Search looks at the name, the description and the category.
 */
export function studioPhotoStyleGroups(items, { q = '', category = '' } = {}, locale = 'en') {
  const categories = []
  const byKey = new Map()
  for (const st of items || []) {
    const key = st.category || ''
    if (!byKey.has(key)) {
      const c = { key, title: studioCategoryTitle(st, locale), items: [] }
      byKey.set(key, c)
      categories.push(c)
    }
  }
  const words = String(q || '').trim().toLowerCase().split(/\s+/).filter(Boolean)
  for (const st of items || []) {
    const c = byKey.get(st.category || '')
    if (category && c.key !== category) continue
    const text = `${st.title || ''} ${st.description || ''} ${c.title}`.toLowerCase()
    if (words.every((w) => text.includes(w))) c.items.push(st)
  }
  return {
    categories: categories.map(({ key, title }) => ({ key, title })),
    groups: categories.filter((c) => c.items.length),
  }
}
