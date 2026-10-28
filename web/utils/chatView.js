/**
 * Pure helpers of the chat (module 15): roles of attached pictures, the
 * summary line of the composer, error texts, matching live events to messages
 * and the extension points other modules plug into (message kinds, composer
 * buttons, picture actions). Nothing here knows a model id.
 *
 * Every export starts with `chat` / `CHAT_` because Nuxt auto-imports
 * everything in web/utils and names must not clash with other modules.
 */
import { apiErrorText } from './apiErrorText.js'
import { parseTs } from './format.js'

export const CHAT_MODES = ['image', 'video']
export const CHAT_IMAGE_ROLES = ['reference', 'subject', 'base']
export const CHAT_VIDEO_ROLES = ['first', 'last', 'reference']
// Roles only one picture of a message can have (the backend says chat_role_twice otherwise).
export const CHAT_SINGLE_ROLES = ['base', 'first', 'last']
export const CHAT_DRAFT_SAVE_MS = 600
export const CHAT_PAGE_SIZE = 60
export const CHAT_LIST_SIZE = 50
export const CHAT_BUSY_ITEMS = ['queued', 'running']
export const CHAT_BUSY_MESSAGES = ['running', 'enhancing']
export const CHAT_LIMITS = { title: 120, text: 4000, attachments: 10 }

// Codes the chat itself answers with (texts in chat.errors).
export const CHAT_ERROR_CODES = [
  'chat_archived', 'chat_attachment_missing', 'chat_attachment_not_image', 'chat_base_alone',
  'chat_enhance_empty', 'chat_item_unknown', 'chat_not_request', 'chat_reply_gone', 'chat_reply_no_pictures',
  'chat_reply_not_ready', 'chat_reply_unknown', 'chat_role_twice', 'chat_role_unknown', 'chat_text_empty',
  'chat_text_too_long', 'chat_too_many_attachments', 'frame_gone', 'job_gone', 'video_gone',
]

const has = (t, te, key) => (te ? te(key) : t(key) !== key)

/** Details as placeholders: lists become "a, b, c". */
function params(details, message = '') {
  const out = { message }
  for (const [k, v] of Object.entries(details || {})) out[k] = Array.isArray(v) ? v.join(', ') : v
  return out
}

/** Error text: chat → studio → video → app-wide texts, then Google's own words, then a generic line. */
export function chatErrorText(err, t, te) {
  const code = err?.code || ''
  for (const key of [`chat.errors.${code}`, `studio.errors.${code}`, `video.errors.${code}`]) {
    if (code && has(t, te, key)) return t(key, params(err?.details, err?.message || ''))
  }
  return apiErrorText(err, t, te)
}

/** Text of a refusal code from an estimate (no message of its own). */
export function chatReasonText(code, t, te, details = {}) {
  if (!code) return ''
  return chatErrorText({ code, details, message: '' }, t, te)
}

/**
 * A failed message or result item: `text` in the person's language when the
 * code is known, `detail` with Google's own words (verbatim) when they differ.
 */
export function chatItemError(item, t, te) {
  const code = item?.error_code || ''
  const raw = String(item?.error || '').trim()
  const keys = [`chat.errors.${code}`, `studio.errors.${code}`, `video.errors.${code}`, `errors.${code}`]
  const known = code && keys.some((k) => has(t, te, k))
  if (!known) return { text: raw || code || t('errors.generic', { code: '' }), detail: '' }
  const text = chatReasonText(code, t, te)
  return { text, detail: raw && raw !== text ? raw : '' }
}

/** A warning code of an estimate in words (chat → video → studio texts), or the code itself. */
export function chatWarningText(code, t, te) {
  for (const key of [`chat.warnings.${code}`, `video.warnings.${code}`, `studio.warnings.${code}`]) {
    if (code && has(t, te, key)) return t(key)
  }
  return String(code || '')
}

/** Warnings of the composer and of the estimate, each once. */
export function chatWarnings(...lists) {
  return [...new Set(lists.flat().filter(Boolean))]
}

// ── attached pictures ──────────────────────────────────────────────────────

export function chatRolesFor(mode, limits = null) {
  if (mode === 'video') return limits?.video_roles?.length ? limits.video_roles : CHAT_VIDEO_ROLES
  return limits?.image_roles?.length ? limits.image_roles : CHAT_IMAGE_ROLES
}

const takenBy = (attachments, role, except) => (attachments || []).some((a, i) => i !== except && a.role === role)

/** The role a newly attached picture gets: a reference; in video the first free frame. */
export function chatDefaultRole(mode, attachments = []) {
  if (mode !== 'video') return 'reference'
  if (!takenBy(attachments, 'first', -1)) return 'first'
  return 'reference'
}

/** The next role on a click on the thumbnail; single roles held by another picture are skipped. */
export function chatNextRole(attachments, index, mode, limits = null) {
  const roles = chatRolesFor(mode, limits)
  const now = attachments?.[index]?.role
  const start = roles.indexOf(now)
  for (let step = 1; step <= roles.length; step++) {
    const role = roles[(start + step + roles.length) % roles.length]
    if (CHAT_SINGLE_ROLES.includes(role) && takenBy(attachments, role, index)) continue
    return role
  }
  return now || roles[0]
}

/** Roles brought to the other mode: what the new mode does not know becomes its default. */
export function chatRolesForMode(attachments, mode, limits = null) {
  const roles = chatRolesFor(mode, limits)
  const out = []
  for (const a of attachments || []) {
    const keep = roles.includes(a.role) && !(CHAT_SINGLE_ROLES.includes(a.role) && takenBy(out, a.role, -1))
    out.push({ ...a, role: keep ? a.role : chatDefaultRole(mode, out) })
  }
  return out
}

/** Add pictures (file objects from a picker) to the draft; known ones are not added twice. */
export function chatAddPictures(attachments, files, mode, max = CHAT_LIMITS.attachments) {
  const out = [...(attachments || [])]
  for (const f of files || []) {
    const id = Number(f?.id ?? f?.file_id)
    if (!id || out.some((a) => Number(a.file_id) === id)) continue
    if (out.length >= max) break
    out.push({ file_id: id, role: chatDefaultRole(mode, out), file: f?.file || f })
  }
  return out
}

/** What the API takes: [{ file_id, role }]. */
export function chatAttachmentsBody(attachments) {
  return (attachments || []).map((a) => ({ file_id: Number(a.file_id), role: a.role || '' }))
}

// ── the composer ───────────────────────────────────────────────────────────

/** The body of POST /chats/{id}/send and /estimate from the composer state. */
export function chatSendBody({ mode, text, attachments, replyTo, replyIndex, enhance, region, extendSeconds } = {}) {
  const body = {
    mode: mode === 'video' ? 'video' : 'image',
    text: String(text || ''),
    attachments: replyTo ? [] : chatAttachmentsBody(attachments),
    reply_to: replyTo || null,
    reply_index: replyTo ? Number(replyIndex || 0) : 0,
    enhance: Boolean(enhance) && !replyTo,
  }
  if (replyTo && region) body.region = region
  if (replyTo && extendSeconds) body.extend_seconds = Number(extendSeconds)
  return body
}

/** Is there something to send (text, or an extension that may go without text)? */
export function chatCanSend({ text, replyKind } = {}) {
  return Boolean(String(text || '').trim()) || replyKind === 'video'
}

/**
 * Parts of the summary line under the composer: [{ key, text }]. A click on a
 * part opens that setting in the panel (`key` is the field id there).
 * `modelTitle(id)` gives a readable model name.
 */
export function chatSummaryParts(chat, mode, t, { modelTitle = (id) => id, estimate = null } = {}) {
  if (!chat) return []
  const title = (id) => (id ? modelTitle(id) || id : t('chat.summary.defaultModel'))
  if (mode === 'video') {
    const v = chat.video_settings || {}
    const parts = [{ key: 'mode', text: t('chat.modes.video') }, { key: 'model', text: title(v.model_id) }]
    if (v.resolution) parts.push({ key: 'resolution', text: v.resolution })
    if (v.duration) parts.push({ key: 'duration', text: t('chat.summary.seconds', { n: v.duration }) })
    if (v.aspect) parts.push({ key: 'aspect', text: v.aspect })
    parts.push({ key: 'sound', text: v.sound === false ? t('chat.summary.noSound') : t('chat.summary.sound') })
    return parts
  }
  const s = chat.image_settings || {}
  const count = Number(s.count || 1)
  const size = estimate?.extra?.image_size || s.image_size
  const parts = [
    { key: 'mode', text: t('chat.modes.image') },
    { key: 'model', text: title(s.model_id) },
    { key: 'aspect', text: s.aspect || '1:1' },
    { key: 'size', text: size || '1K' },
    { key: 'count', text: t('chat.summary.variants', { n: count }, count) },
  ]
  if (s.series && count > 1) parts.push({ key: 'series', text: t('chat.summary.series') })
  return parts
}

// ── messages and live updates ──────────────────────────────────────────────

export function chatItems(message) {
  return message?.data?.items || []
}

export function chatItemBusy(item) {
  return CHAT_BUSY_ITEMS.includes(item?.status)
}

/** Is a message still being made (so events about it matter)? */
export function chatMessageBusy(message) {
  if (!message) return false
  if (CHAT_BUSY_MESSAGES.includes(message.status)) return true
  return chatItems(message).some(chatItemBusy)
}

/**
 * Does a live event concern this message? `type` is the event name:
 * job.updated / job.progress (by job id), studio.updated (by work id),
 * video.updated / video.deleted (by video id).
 */
export function chatEventTouches(message, type, data) {
  if (!message || !data) return false
  const items = chatItems(message)
  if (type === 'job.updated' || type === 'job.progress') {
    return items.some((i) => i.job_id && Number(i.job_id) === Number(data.id))
  }
  if (type === 'studio.updated') {
    const work = message.refs?.work_id
    return (work && Number(work) === Number(data.work_id)) || items.some((i) => Number(i.work_id) === Number(data.work_id))
  }
  if (type === 'video.updated' || type === 'video.deleted') {
    return items.some((i) => i.run_id && Number(i.run_id) === Number(data.id))
  }
  return false
}

/** The message with the progress of a job put on its item (no request to the server). */
export function chatApplyProgress(message, { id, progress } = {}) {
  if (!message || id == null) return message
  let changed = false
  const items = chatItems(message).map((i) => {
    if (!i.job_id || Number(i.job_id) !== Number(id)) return i
    changed = true
    return { ...i, progress: Number(progress) || 0, status: i.status === 'queued' ? 'running' : i.status }
  })
  return changed ? { ...message, data: { ...message.data, items } } : message
}

/** Put fresh messages into the feed: replaced by id, new ones added, all by position. */
export function chatMergeMessages(list, incoming) {
  const byId = new Map((list || []).map((m) => [m.id, m]))
  for (const m of incoming || []) if (m?.id) byId.set(m.id, m)
  return [...byId.values()].sort((a, b) => (a.position - b.position) || (a.id - b.id))
}

/** The overall progress 0..1 of a result (average over busy and finished items), or null. */
export function chatProgress(message) {
  const items = chatItems(message)
  if (!items.length) return null
  const sum = items.reduce((acc, i) => acc + (chatItemBusy(i) ? Number(i.progress) || 0 : 1), 0)
  return Math.max(0, Math.min(1, sum / items.length))
}

/** Pictures of a series that wait for the first one to be approved. */
export function chatWaitingCount(message) {
  return chatItems(message).filter((i) => i.status === 'waiting').length
}

/** Can a result be answered (edit a picture / extend a video)? */
export function chatItemReady(item) {
  return item?.status === 'done' && Boolean(item?.file_id)
}

/** «12:30» for today, «15 Oct, 12:30» for other days. */
export function chatTime(ts, locale = 'en', now = new Date()) {
  const d = parseTs(ts)
  if (!d) return ''
  if (d.toDateString() === now.toDateString()) return d.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' })
  return d.toLocaleString(locale, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}

/** Where a picture lives in the media library. */
export function chatMediaLink(fileId) {
  return fileId ? `/media?file=${fileId}` : ''
}

export function chatFileThumb(file) {
  return file?.thumb_url || file?.preview_url || file?.url || ''
}

/** '4:5' -> '4 / 5' for the CSS aspect-ratio property ('1 / 1' when unknown). */
export function chatAspectRatio(aspect) {
  const m = String(aspect || '').match(/^(\d+):(\d+)$/)
  return m ? `${m[1]} / ${m[2]}` : '1 / 1'
}

/** The CSS aspect ratio of a result tile: the file's own size, else the asked aspect. */
export function chatItemRatio(item, aspect = null) {
  const w = Number(item?.file?.width)
  const h = Number(item?.file?.height)
  return w > 0 && h > 0 ? `${w} / ${h}` : chatAspectRatio(aspect)
}

/** The first query value as a positive number, or null ('/chat?frame=12'). */
export function chatQueryId(value) {
  const raw = Array.isArray(value) ? value[0] : value
  const n = Number(raw)
  return Number.isInteger(n) && n > 0 ? n : null
}

/** Which result a `/chat?frame=|work=|video=` link points at: { key, id } or null. */
export function chatFindQuery(query) {
  for (const key of ['frame', 'work', 'video']) {
    const id = chatQueryId(query?.[key])
    if (id) return { key, id }
  }
  return null
}

// ── extension points ───────────────────────────────────────────────────────
//
// Other modules (05 ideas, 06 text on pictures, 09 avatars…) add to the chat
// from a Nuxt plugin, without changing the chat itself:
//
//   chatRegisterKind('avatar.card', AvatarCardComponent)   // or a file in components/chat/kinds/
//   chatRegisterComposerButton({ id: 'ideas', icon: 'sparkles', labelKey: 'ideas.chat.button',
//     modes: ['image'], onClick: (ctx) => … })
//   chatRegisterImageAction({ id: 'text', icon: 'text', labelKey: 'text.chat.action',
//     onClick: ({ message, item, index, room }) => … })

const kinds = new Map()
const composerButtons = new Map()
const imageActions = new Map()

/** 'avatar.card' -> 'AvatarCard': the file name under components/chat/kinds/. */
export function chatKindFileName(kind) {
  return String(kind || '')
    .split(/[._-]+/)
    .filter(Boolean)
    .map((part) => part[0].toUpperCase() + part.slice(1))
    .join('')
}

export function chatRegisterKind(kind, component) {
  if (kind && component) kinds.set(kind, component)
}

export function chatKindComponent(kind) {
  return kinds.get(kind) || null
}

function sorted(map, filter) {
  return [...map.values()].filter(filter).sort((a, b) => (a.order ?? 100) - (b.order ?? 100))
}

export function chatRegisterComposerButton(button) {
  if (button?.id) composerButtons.set(button.id, { modes: CHAT_MODES, ...button })
}

/** Composer buttons for a mode, in their `order`. */
export function chatComposerButtons(mode) {
  return sorted(composerButtons, (b) => !b.modes || b.modes.includes(mode))
}

export function chatRegisterImageAction(action) {
  if (action?.id) imageActions.set(action.id, action)
}

/** Extra actions under a finished picture, in their `order`. */
export function chatImageActions() {
  return sorted(imageActions, () => true)
}

/** For tests: forget everything registered. */
export function chatResetRegistries() {
  kinds.clear()
  composerButtons.clear()
  imageActions.clear()
}
