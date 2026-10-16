/**
 * Pure helpers of the video module (11): limits, model choices, settings that
 * fit a model, camera move groups, extension plans, clip errors and error texts.
 * Nothing here knows a model id: models come from GET /api/video/models.
 *
 * Every export starts with `video` / `VIDEO_` because Nuxt auto-imports
 * everything in web/utils and names must not clash with other modules.
 */
import { apiErrorText } from './apiErrorText.js'

// Mirrors of the backend limits (app/vf/modules/video/runs.py, extend.py, storyboard.py).
export const VIDEO_LIMITS = {
  title: 200, niche: 120, platform: 60, brief: 4000, references: 14, steps: 10, stepText: 2000,
  minPanels: 2, maxPanels: 12,
}
export const VIDEO_AUTOSAVE_MS = 600
export const VIDEO_EDITABLE = [
  'title', 'niche', 'platform', 'brief', 'first_frame_id', 'last_frame_id', 'references', 'model_id', 'duration',
  'resolution', 'aspect', 'camera_move', 'sound',
]
export const VIDEO_CAMERA_GROUPS = ['basic', 'advanced', 'framing']
export const VIDEO_STAGES = ['draft', 'take', 'extend', 'done']
export const VIDEO_STATUSES = ['idle', 'running', 'paused', 'done', 'error']
export const VIDEO_CLIP_KINDS = ['take', 'extend', 'continue']
export const VIDEO_CLIP_STATUSES = ['queued', 'running', 'done', 'error', 'cancelled', 'stopped']
export const VIDEO_STEP_STATUSES = ['pending', 'running', 'done', 'error', 'stopped']
export const VIDEO_PLAN_STATUSES = ['running', 'paused', 'done', 'error', 'stopped']
export const VIDEO_WARNINGS = ['frame_shadows_references']
export const VIDEO_IMAGE_ACCEPT = 'image/png,image/jpeg,image/webp'

// Error codes the video API answers with (its own texts are in video.errors.*).
export const VIDEO_ERROR_CODES = [
  'video_busy', 'video_field_unknown', 'video_text_too_long', 'video_frame_not_image', 'video_too_many_references',
  'video_brief_empty', 'video_first_frame_unsupported', 'video_last_frame_needs_first',
  'video_last_frame_unsupported', 'video_camera_unknown', 'video_extend_unsupported', 'video_extend_no_steps',
  'video_extend_too_many', 'video_extend_length_unsupported', 'video_extend_no_video', 'video_extend_no_plan',
  'video_aspect_unsupported', 'video_nothing_to_undo', 'video_interrupted', 'video_input_too_large',
  'video_extend_format', 'video_niche_empty', 'video_brief_exists', 'video_brief_busy', 'video_brief_bad_answer',
  'video_no_previous_brief', 'video_storyboard_empty', 'video_storyboard_busy', 'video_storyboard_none',
  'video_frame_at',
]

const has = (t, te, key) => (te ? te(key) : t(key) !== key)

/** Details as placeholders: lists become "a, b, c". */
function params(details, message = '') {
  const out = { message }
  for (const [k, v] of Object.entries(details || {})) out[k] = Array.isArray(v) ? v.join(', ') : v
  return out
}

/** Error text: the video's own `video.errors.<code>` first, then the app-wide one. */
export function videoErrorText(err, t, te) {
  const key = `video.errors.${err?.code || 'unknown'}`
  if (has(t, te, key)) return t(key, params(err?.details, err?.message || ''))
  return apiErrorText(err, t, te)
}

/** Text of a refusal or a "why not" code (take.refusal, extend.reason); the raw code when nothing knows it. */
export function videoReasonText(code, t, te, details = {}) {
  for (const key of [`video.errors.${code}`, `errors.${code}`]) {
    if (code && has(t, te, key)) return t(key, params(details))
  }
  return String(code || '')
}

/**
 * A failed clip: `text` in the person's language when the code is known,
 * `detail` with Google's own words (verbatim) when there are any. The module's
 * own codes carry only an English copy of the text, so no detail for them.
 */
export function videoClipError(clip, t, te) {
  const code = clip?.error_code || ''
  const raw = String(clip?.error || '').trim()
  const known = code && [`video.errors.${code}`, `errors.${code}`].some((k) => has(t, te, k))
  if (!known) return { text: raw || code, detail: '' }
  const text = videoReasonText(code, t, te)
  return { text, detail: VIDEO_ERROR_CODES.includes(code) || raw === text ? '' : raw }
}

/** Does a `video.updated` / `video.deleted` event concern this video? */
export function videoEventMatches(data, runId) {
  if (!data || runId == null) return false
  return Number(data.id) === Number(runId)
}

export function videoModelById(models, id) {
  return (models || []).find((m) => m.id === id) || null
}

/** Video models a person can pick: available ones, plus the one already chosen. */
export function videoModelChoices(models, current = null) {
  return (models || []).filter((m) => m.available !== false || m.id === current)
}

/** '720p' -> 720, '4k' -> 4000: to compare sizes. */
export function videoResolutionRank(name) {
  const digits = String(name || '').replace(/\D/g, '')
  const value = Number(digits || 0)
  return /k$/i.test(String(name || '')) ? value * 1000 : value
}

export function videoResolutionsFor(model) {
  return Object.keys(model?.resolutions || {})
}

/** Lengths (seconds) the model makes at this size; every length it knows when the size is unknown. */
export function videoDurationsFor(model, resolution) {
  const table = model?.resolutions || {}
  const key = String(resolution || '').toLowerCase()
  if (key && Array.isArray(table[key])) return [...table[key]]
  const all = new Set(Object.values(table).flat())
  return [...all].sort((a, b) => a - b)
}

/** The allowed length closest to `value` (a tie goes to the longer one). */
export function videoSnapDuration(value, allowed) {
  if (!allowed?.length) return null
  if (value === null || value === undefined || value === '') return allowed[0]
  const v = Number(value)
  return [...allowed].sort((a, b) => (Math.abs(a - v) - Math.abs(b - v)) || (b - a))[0]
}

/** Settings brought inside what the model allows (same rule as the backend). */
export function videoFitSettings(model, { duration, resolution, aspect } = {}) {
  const names = videoResolutionsFor(model)
  const res = names.includes(String(resolution || '').toLowerCase()) ? String(resolution).toLowerCase() : (names[0] || '720p')
  const shapes = model?.aspects?.length ? model.aspects : ['9:16', '16:9']
  return {
    resolution: res,
    duration: videoSnapDuration(duration, videoDurationsFor(model, res)),
    aspect: shapes.includes(aspect) ? aspect : shapes[0],
  }
}

/** Camera moves by group, in the order of `categories`: [{ name, codes }]. Empty groups are left out. */
export function videoCameraGroups(moves, categories = VIDEO_CAMERA_GROUPS) {
  const groups = (categories || []).map((name) => ({ name, codes: [] }))
  const byName = Object.fromEntries(groups.map((g) => [g.name, g]))
  for (const m of moves || []) {
    if (!m?.code) continue
    const g = byName[m.category] || byName[groups[groups.length - 1]?.name]
    if (g) g.codes.push(m.code)
  }
  return groups.filter((g) => g.codes.length)
}

/** Warnings about what the take leaves out, computed from the form (the server sends the same in take.warnings). */
export function videoAttachWarnings(model, { first_frame_id: first, references } = {}) {
  if (first && model?.frame_shadows_references && (references || []).length) return ['frame_shadows_references']
  return []
}

/** { done, total, errors, current, running, paused } over an extension plan. */
export function videoPlanProgress(plan) {
  const steps = plan?.steps || []
  const out = { done: 0, total: steps.length, errors: 0, current: null, running: false, paused: false }
  steps.forEach((s, i) => {
    if (s.status === 'done') out.done++
    if (s.status === 'error') out.errors++
    if (s.status === 'running' && out.current === null) out.current = i
  })
  out.running = plan?.status === 'running'
  out.paused = plan?.status === 'paused'
  return out
}

/** Steps as the API takes them: [{ text, seconds }]; an empty text means "the brief of the video". */
export function videoStepsBody(steps) {
  return (steps || []).map((s) => ({ text: String(s?.text || '').trim(), seconds: Number(s?.seconds) || 0 }))
}

/** The worst case price of a plan from the estimate (each piece re-sends the tail). */
export function videoPlanTotal(estimate) {
  if (!estimate?.pieces) return null
  return estimate.total_usd ?? estimate.pieces.reduce((sum, p) => sum + (Number(p.estimate_usd) || 0), 0)
}

/** The clip that is being made right now, or null. */
export function videoRunningClip(run) {
  return (run?.clips || []).find((c) => c.running) || null
}

/** The latest failed clip when the run stopped on an error, or null. */
export function videoFailedClip(run) {
  if (run?.status !== 'error') return null
  const clips = [...(run?.clips || [])].reverse()
  return clips.find((c) => c.status === 'error') || null
}

/** The version shown now (current_version), or the last one. */
export function videoCurrentVersion(run) {
  const list = run?.versions || []
  return list.find((v) => v.number === run?.current_version) || list[list.length - 1] || null
}

/** '9:16' -> '9 / 16' for the CSS aspect-ratio property ('16 / 9' when unknown). */
export function videoAspectRatio(aspect) {
  const m = String(aspect || '').match(/^(\d+):(\d+)$/)
  return m ? `${m[1]} / ${m[2]}` : '16 / 9'
}

export function videoFileUrl(file) {
  return file?.url || (file?.id ? `/files/${file.id}` : '')
}

export function videoDownloadUrl(file) {
  const url = videoFileUrl(file)
  return url ? `${url}?download=1` : ''
}

export function videoThumbUrl(id, width = 480) {
  return id ? `/files/${id}?w=${width}` : ''
}

/** "4.0" -> "4", 7.25 -> "7.3": seconds as shown next to a video. */
export function videoSeconds(value) {
  const v = Math.round((Number(value) || 0) * 10) / 10
  return String(Number.isInteger(v) ? v : v.toFixed(1))
}

/** A short string that changes whenever the run changes: put it in price requests so they are asked again. */
export function videoRunRevision(run) {
  if (!run) return ''
  const clips = (run.clips || []).map((c) => `${c.id}:${c.status}`)
  return [run.updated_at || '', run.current_version || '', ...clips].join('|')
}

/** Does a text box hold something the person typed (not only spaces)? */
export function videoHasText(value) {
  return Boolean(String(value || '').trim())
}
