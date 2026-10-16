/**
 * Avatars (module 09) in the chat: one person — photographed or invented — with
 * a written description (the identity), a chosen face and a pack of 36 shots.
 *
 * Every avatar lives in its own chat (chat kind "avatar"). The card of the
 * avatar and the batches it draws are chat messages: 'avatar.card',
 * 'avatar.identity', 'avatar.candidates', 'avatar.pack'
 * (components/chat/kinds/Avatar*.vue). The full-screen grid of 36 shots works
 * on the same avatar (components/avatars/AvatarGrid.vue).
 *
 * The view of an avatar is GET /api/avatars/:id (docs/dev/avatars-api.md).
 */
import { chatErrorText, chatItemError } from './chatView.js'

export const AVATAR_MODES = ['reference', 'description', 'auto']
export const AVATAR_STATES = ['no_identity', 'no_face', 'face_ready', 'unfinished', 'ready']
export const AVATAR_LIMITS = {
  name: 120, brief: 2000, identityMin: 200, identity: 6000, angle: 60, prompt: 4000, fix: 2000,
  photos: 12, describePhotos: 3, subjectPhotos: 4, candidatesMin: 1, candidatesMax: 6,
}
export const AVATAR_DEFAULT_CANDIDATES = 4
export const AVATAR_FACE_CODE = 'SHOT_01'
export const AVATAR_SHOT_COUNT = 36
// The grid groups the shots by the last part of the catalog category ('identity/full-36/angles').
export const AVATAR_CATEGORIES = ['portraits', 'angles', 'body', 'scenes', 'speech', 'emotions', 'gaze']
export const AVATAR_BUSY = ['queued', 'drawing']
export const AVATAR_TABS = ['person', 'face', 'shots']
export const AVATAR_ESTIMATE_MS = 400
export const AVATAR_UPLOAD_MAX_PX = 2048 // bigger photos are made smaller in the browser before upload
export const AVATAR_ERROR_CODES = [
  'avatar_brief_too_long', 'avatar_describe_busy', 'avatar_face_slot', 'avatar_fix_required', 'avatar_fix_too_long',
  'avatar_identity_empty', 'avatar_identity_exists', 'avatar_identity_locked', 'avatar_identity_too_long',
  'avatar_mark_not_allowed', 'avatar_mode_unknown', 'avatar_name_required', 'avatar_no_brief', 'avatar_no_face',
  'avatar_no_identity', 'avatar_no_photos', 'avatar_no_picture', 'avatar_nothing_to_draw', 'avatar_photo_busy',
  'avatar_photo_foreign', 'avatar_photo_limit', 'avatar_photos_unreadable', 'avatar_prompt_too_long',
  'avatar_shot_unknown', 'stuck', 'interrupted', 'bad_order', 'nothing_to_export',
]

const has = (t, te, key) => (te ? te(key) : t(key) !== key)

// ── errors ──

/** Text of an API error: the avatar texts first, then the chat ones. */
export function avatarsErrorText(err, t, te) {
  const code = err?.code || ''
  const key = `avatars.errors.${code}`
  if (code && has(t, te, key)) return t(key, { ...(err?.details || {}), message: err?.message || '' })
  return chatErrorText(err, t, te)
}

/** Text of a refusal code (from an estimate or a failed picture). */
export function avatarsReasonText(code, t, te) {
  return code ? avatarsErrorText({ code, details: {}, message: '' }, t, te) : ''
}

/**
 * A failed picture or message: our text plus Google's own words when they
 * differ. Pictures keep the words in `error_text`, messages in `error`.
 */
export function avatarsItemError(item, t, te) {
  const code = item?.error_code || ''
  const raw = String(item?.error ?? item?.error_text ?? '').trim()
  if (code && has(t, te, `avatars.errors.${code}`)) {
    const text = avatarsReasonText(code, t, te)
    return { text, detail: raw && raw !== text ? raw : '' }
  }
  return chatItemError({ error_code: code, error: raw }, t, te)
}

// ── the 36 shots ──

/** 'identity/full-36/angles' -> 'angles'. */
export function avatarsCategory(slug) {
  const parts = String(slug || '').split('/').filter(Boolean)
  return parts.length ? parts[parts.length - 1] : ''
}

/** The slots in groups for the grid, in the order of AVATAR_CATEGORIES (unknown groups last). */
export function avatarsGroupSlots(slots) {
  const groups = new Map()
  for (const s of slots || []) {
    const cat = avatarsCategory(s.category) || 'other'
    if (!groups.has(cat)) groups.set(cat, [])
    groups.get(cat).push(s)
  }
  const order = (c) => {
    const i = AVATAR_CATEGORIES.indexOf(c)
    return i < 0 ? AVATAR_CATEGORIES.length : i
  }
  return [...groups.entries()]
    .sort((a, b) => order(a[0]) - order(b[0]))
    .map(([category, list]) => ({ category, slots: list }))
}

export function avatarsShotTitle(code, t, te, fallback = '') {
  const key = `avatars.shots.${code}`
  return code && has(t, te, key) ? t(key) : (fallback || code || '')
}

export function avatarsSlotBusy(slot) {
  return AVATAR_BUSY.includes(slot?.status)
}

/**
 * What a slot shows: 'busy' (a picture is being drawn; the old one stays until
 * the new one comes), 'done', 'error' (the last try failed and there is no
 * picture), 'empty'.
 */
export function avatarsSlotState(slot) {
  if (!slot) return 'empty'
  if (avatarsSlotBusy(slot)) return 'busy'
  if (slot.file_id) return 'done'
  if (slot.status === 'error') return 'error'
  return 'empty'
}

/** The pictures of a batch message, from the avatar view, in the message order. */
export function avatarsBatchPhotos(view, ids) {
  const all = [...(view?.slots || []), ...(view?.candidates || []), ...(view?.sources || [])]
  if (view?.face_photo) all.push(view.face_photo)
  const byId = new Map(all.map((p) => [Number(p.id), p]))
  return (ids || []).map((id) => byId.get(Number(id))).filter(Boolean)
}

/** How far a batch is: done (with a picture), busy, failed, total. */
export function avatarsBatchProgress(photos) {
  const out = { done: 0, busy: 0, failed: 0, total: (photos || []).length }
  for (const p of photos || []) {
    const state = avatarsSlotState(p)
    if (state === 'busy') out.busy += 1
    else if (state === 'done') out.done += 1
    else if (state === 'error') out.failed += 1
  }
  return out
}

/** The slots a pack would draw (empty and failed ones, not the face, not busy). */
export function avatarsEmptySlots(slots) {
  return (slots || []).filter((s) => s.shot_code !== AVATAR_FACE_CODE && !s.file_id && !avatarsSlotBusy(s))
}

// ── the person ──

/** What is wrong with a typed identity: '' when it can be saved. */
export function avatarsIdentityCheck(text) {
  const len = String(text || '').trim().length
  if (!len) return 'avatar_identity_empty'
  if (len < AVATAR_LIMITS.identityMin) return 'short'
  if (len > AVATAR_LIMITS.identity) return 'avatar_identity_too_long'
  return ''
}

/** Why «Describe» cannot start now ('' when it can). The server checks the same. */
export function avatarsDescribeBlock(view) {
  if (!view) return 'avatar_no_identity'
  if (view.identity_locked) return 'avatar_identity_locked'
  if (view.describing) return 'avatar_describe_busy'
  if (view.init_mode === 'reference' && !(view.sources || []).some((p) => p.file_id)) return 'avatar_no_photos'
  if (view.init_mode === 'description' && !String(view.brief || '').trim()) return 'avatar_no_brief'
  return ''
}

/** Why the face candidates cannot be drawn now ('' when they can). */
export function avatarsCandidatesBlock(view) {
  if (!view) return 'avatar_no_identity'
  if (!String(view.identity || '').trim()) return 'avatar_no_identity'
  if (view.describing) return 'avatar_describe_busy'
  return ''
}

/** Why the pack cannot be drawn now ('' when it can). */
export function avatarsPackBlock(view) {
  if (!view) return 'avatar_no_identity'
  if (!String(view.identity || '').trim()) return 'avatar_no_identity'
  if (!view.face) return 'avatar_no_face'
  if (!avatarsEmptySlots(view.slots).length) return 'avatar_nothing_to_draw'
  return ''
}

/** How many more photos of the person fit. */
export function avatarsPhotosLeft(view) {
  return Math.max(0, AVATAR_LIMITS.photos - (view?.sources || []).length)
}

/** The candidate count the backend keeps (1..6). */
export function avatarsCandidateCount(value) {
  const n = Math.round(Number(value))
  if (!Number.isFinite(n)) return AVATAR_DEFAULT_CANDIDATES
  return Math.min(AVATAR_LIMITS.candidatesMax, Math.max(AVATAR_LIMITS.candidatesMin, n))
}

/** The avatar a chat belongs to (an avatar chat), or null. */
export function avatarsChatAvatarId(chat) {
  if (chat?.kind !== 'avatar') return null
  const id = Number(chat?.meta?.avatar_id)
  return Number.isInteger(id) && id > 0 ? id : null
}

/** Picture file ids attached to the composer (to add them to the avatar as photos of the person). */
export function avatarsDraftFileIds(draft) {
  const ids = (draft?.attachments || [])
    .filter((a) => !a?.file?.mime || String(a.file.mime).startsWith('image/'))
    .map((a) => Number(a?.file_id))
    .filter((id) => Number.isInteger(id) && id > 0)
  return [...new Set(ids)]
}

/** The composer text with «@Name» added at the end (the avatar is called by its name). */
export function avatarsMention(text, name) {
  const who = String(name || '').trim()
  if (!who) return String(text || '')
  const base = String(text || '').replace(/\s+$/, '')
  return `${base ? `${base} ` : ''}@${who} `
}

/** A picture file at a given width (the files route makes the smaller copy). */
export function avatarsThumb(fileId, width = 480) {
  return fileId ? `/files/${fileId}?w=${width}` : ''
}

/** 'SHOT_07' -> 7 (0 when it is not a shot code). */
export function avatarsShotNumber(code) {
  const m = String(code || '').match(/^SHOT_(\d+)$/)
  return m ? Number(m[1]) : 0
}

/** The spend screen with the calls of one thing (an avatar, a picture, a chat message). */
export function avatarsSpendLink(refType, id) {
  return refType && id ? `/spend?ref_type=${refType}&ref_id=${id}&period=all` : ''
}

/** The card opens on the step the avatar is at. */
export function avatarsDefaultTab(view) {
  const state = view?.state
  if (!state || state === 'no_identity') return 'person'
  if (state === 'no_face') return 'face'
  return 'shots'
}

/**
 * What a shot can be put side by side with: the face, the photos of the person,
 * the earlier versions of this shot. [{ key, kind: 'face'|'photo'|'previous', n, file_id }]
 */
export function avatarsCompareChoices(slot, view) {
  const out = []
  const seen = new Set([Number(slot?.file_id) || 0])
  const add = (kind, fileId, n = 0) => {
    const id = Number(fileId)
    if (!id || seen.has(id)) return
    seen.add(id)
    out.push({ key: `${kind}:${id}`, kind, n, file_id: id })
  }
  add('face', view?.face?.id)
  ;(view?.sources || []).forEach((p, i) => add('photo', p.file_id, i + 1))
  const previous = [...(slot?.meta?.previous_file_ids || [])].reverse()
  previous.forEach((id, i) => add('previous', id, i + 1))
  return out
}

/** «About 2 minutes» for an estimate's time ('' when the estimate has none). */
export function avatarsTimeText(time, t) {
  if (!time || !(Number(time.seconds) > 0)) return ''
  const d = avatarsDuration(time.seconds)
  const key = `avatars.time.${d.key}`
  // hours come with a decimal ("1.5 h") and have one form; seconds and minutes are plural
  const text = d.key === 'hours' ? t(key, { n: d.n }) : t(key, { n: d.n }, d.n)
  return t('avatars.time.about', { time: text })
}

export function avatarsExportUrl(id) {
  return id ? `/api/avatars/${id}/export` : ''
}

/** The jobs page leads to the message the picture or description belongs to. */
export function avatarsJobRoute(id, job) {
  const chatId = job?.result_json?.chat_id
  if (!chatId) return null
  const messageId = job.result_json.message_id
  return messageId ? `/chat/${chatId}?message=${messageId}` : `/chat/${chatId}`
}

/** About how long: { key: 'seconds' | 'minutes' | 'hours', n } for avatars.time.<key>. */
export function avatarsDuration(seconds) {
  const s = Math.max(0, Math.round(Number(seconds) || 0))
  if (s < 90) return { key: 'seconds', n: Math.max(5, Math.round(s / 5) * 5) }
  if (s < 90 * 60) return { key: 'minutes', n: Math.round(s / 60) }
  return { key: 'hours', n: Math.round((s / 3600) * 10) / 10 }
}

/** The size a photo is made to before upload: the long side at most `max`. */
export function avatarsFitSize(width, height, max = AVATAR_UPLOAD_MAX_PX) {
  const w = Number(width) || 0
  const h = Number(height) || 0
  const long = Math.max(w, h)
  if (!long || long <= max) return { width: w, height: h, scale: 1 }
  const scale = max / long
  return { width: Math.round(w * scale), height: Math.round(h * scale), scale }
}

/**
 * A photo made smaller in the browser when its long side is over `max`
 * (JPEG, 0.92). Small photos, and anything the browser cannot read, go as they are.
 */
export async function avatarsShrinkPhoto(file, max = AVATAR_UPLOAD_MAX_PX) {
  if (typeof createImageBitmap !== 'function' || typeof document === 'undefined') return file
  if (!file?.type?.startsWith('image/') || file.type === 'image/gif') return file
  let bitmap = null
  try {
    bitmap = await createImageBitmap(file)
    const size = avatarsFitSize(bitmap.width, bitmap.height, max)
    if (size.scale >= 1) return file
    const canvas = document.createElement('canvas')
    canvas.width = size.width
    canvas.height = size.height
    canvas.getContext('2d').drawImage(bitmap, 0, 0, size.width, size.height)
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.92))
    if (!blob) return file
    const name = String(file.name || 'photo').replace(/\.[^.]+$/, '') + '.jpg'
    return new File([blob], name, { type: 'image/jpeg' })
  } catch {
    return file
  } finally {
    bitmap?.close?.()
  }
}
