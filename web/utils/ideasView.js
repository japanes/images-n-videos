/**
 * Shot ideas (module 05) in the chat: the «Ideas» window and the card it posts.
 *
 * The window is a brief, a setting («place and light») and three switches; one
 * press writes a concept and a prompt per frame (POST /api/ideas/sets). The card
 * in the feed is the set itself (`message.data` is its view).
 */
import { chatErrorText, chatItemError } from './chatView.js'

export const IDEAS_LANGUAGES = ['ru', 'uk', 'en']
export const IDEAS_MAX_COUNT = 10
export const IDEAS_MAX_PICTURES = 6 // in each group: product pictures, pictures for the look
export const IDEAS_ESTIMATE_MS = 400
// Suggestions for «Where it will live»; the field takes any text.
export const IDEAS_PLATFORMS = ['Instagram', 'Pinterest', 'Behance', 'TikTok', 'YouTube', 'Facebook', 'Etsy', 'Amazon']
// Text fields of the brief, in the order the window shows them.
export const IDEAS_TEXT_FIELDS = ['niche', 'brand', 'want', 'goal', 'audience', 'platform', 'idea', 'requirements']
export const IDEAS_PICTURE_GROUPS = ['product', 'visual']
export const IDEAS_ERROR_CODES = [
  'ideas_niche_empty', 'ideas_bad_count', 'ideas_bad_language', 'ideas_too_many_pictures', 'ideas_not_a_picture',
  'ideas_scene_unknown', 'ideas_card_unknown', 'ideas_not_ready', 'ideas_prompt_empty', 'ideas_nothing_to_draw',
  'ideas_busy', 'ideas_empty',
]
const NICHE_MAX = 200

const has = (t, te, key) => (te ? te(key) : t(key) !== key)

/** The language of the names: the interface language when the model can write in it. */
export function ideasDefaultLanguage(locale) {
  const code = String(locale || '').slice(0, 2).toLowerCase()
  return IDEAS_LANGUAGES.includes(code) ? code : 'en'
}

/**
 * An empty window. The niche search starts off (it is paid; open question 11),
 * the first frame is drawn at once, product pictures go into the frames.
 */
export function ideasEmptyForm(locale = 'en') {
  return {
    niche: '', brand: '', want: '', goal: '', audience: '', platform: '', idea: '', requirements: '',
    count: 0, language: ideasDefaultLanguage(locale),
    product: [], productNote: '', visual: [], visualNote: '',
    scene: {}, research: false, drawFirst: true, productToFrames: true,
  }
}

/** The composer's text becomes the niche when the window opens with an empty one (seen and editable). */
export function ideasPrefill(form, text) {
  const value = String(text || '').replace(/\s+/g, ' ').trim()
  if (!form.niche && value) form.niche = value.slice(0, NICHE_MAX)
  return form
}

const ids = (files) => (files || []).map((f) => Number(f?.id)).filter((id) => Number.isInteger(id) && id > 0)

/** The brief as the backend takes it. */
export function ideasBriefBody(form) {
  const out = {}
  for (const k of IDEAS_TEXT_FIELDS) out[k] = String(form[k] || '').trim()
  return {
    ...out,
    count: Number(form.count) || 0,
    language: form.language,
    product_refs: ids(form.product),
    product_note: String(form.productNote || '').trim(),
    visual_refs: ids(form.visual),
    visual_note: String(form.visualNote || '').trim(),
  }
}

/** The product pictures go into the frames only when there are some and the switch is on. */
export function ideasProductToFrames(form) {
  return Boolean(form.productToFrames) && ids(form.product).length > 0
}

/**
 * POST /api/ideas/sets (and its estimate). `off` names switches the estimate
 * refused (a model switched off…): they are shown off and sent off.
 */
export function ideasStartBody(form, chatId, off = {}) {
  const scene = {}
  for (const [axis, items] of Object.entries(form.scene || {})) if (items?.length) scene[axis] = [...items]
  return {
    chat_id: chatId,
    brief: ideasBriefBody(form),
    scene,
    research: Boolean(form.research) && !off.research,
    draw_first: Boolean(form.drawFirst) && !off.drawFirst,
    product_to_frames: ideasProductToFrames(form),
  }
}

/**
 * The price on «Write ideas»: the ideas plus the parts that are on and not refused
 * (null until the estimate is known).
 */
export function ideasTotal(est, form) {
  if (!est) return null
  let usd = Number(est.ideas_usd) || 0
  if (form?.research && !est.research_refusal) usd += Number(est.research_usd) || 0
  if (form?.drawFirst && !est.frame_refusal) usd += Number(est.frame_usd) || 0
  return Math.round(usd * 10000) / 10000
}

export function ideasCanSubmit(form) {
  return Boolean(String(form?.niche || '').trim())
}

/** Pick or unpick an item of an axis: one-item axes swap, others stop at their cap. */
export function ideasSceneToggle(scene, axisId, itemId, max = 1) {
  const current = [...(scene?.[axisId] || [])]
  const out = { ...(scene || {}) }
  if (current.includes(itemId)) out[axisId] = current.filter((id) => id !== itemId)
  else if (max <= 1) out[axisId] = [itemId]
  else if (current.length < max) out[axisId] = [...current, itemId]
  else return out
  if (!out[axisId].length) delete out[axisId]
  return out
}

export function ideasSceneCount(scene) {
  return Object.values(scene || {}).reduce((n, items) => n + (items?.length || 0), 0)
}

/** Add picked files to a group: each once, at most `max`. */
export function ideasAddPictures(list, files, max = IDEAS_MAX_PICTURES) {
  const out = [...(list || [])]
  for (const f of files || []) {
    if (out.length >= max) break
    if (f?.id && !out.some((x) => x.id === f.id)) out.push({ id: f.id, url: f.url || '', thumb_url: f.thumb_url || '' })
  }
  return out
}

// ── errors ──

/** Error text: the module's own texts first, then the chat's chain. */
export function ideasErrorText(err, t, te) {
  const code = err?.code || ''
  const key = `ideas.errors.${code}`
  if (code && has(t, te, key)) return t(key, { ...(err?.details || {}), message: err?.message || '' })
  return chatErrorText(err, t, te)
}

/** Text of a refusal code from an estimate. */
export function ideasReasonText(code, t, te) {
  return code ? ideasErrorText({ code, details: {}, message: '' }, t, te) : ''
}

/** A failed set (or a failed draw / search of it): our text plus Google's own words when they differ. */
export function ideasItemError(item, t, te) {
  const code = item?.error_code || ''
  if (code && has(t, te, `ideas.errors.${code}`)) {
    const text = ideasReasonText(code, t, te)
    const raw = String(item?.error || '').trim()
    return { text, detail: raw && raw !== text ? raw : '' }
  }
  return chatItemError(item, t, te)
}

// ── the card ──

/** 'researching' | 'writing' | 'done' | 'error' | 'cancelled'. */
export function ideasCardState(view) {
  const status = view?.status || 'running'
  if (status !== 'running') return status
  return view?.research && !view.research.done ? 'researching' : 'writing'
}

/** Cards that can be drawn: those with a prompt. */
export function ideasDrawable(view) {
  return (view?.images || []).filter((c) => String(c?.prompt || '').trim())
}

/** Only web links are shown as links. */
export function ideasSafeUrl(url) {
  return /^https?:\/\//i.test(String(url || '')) ? String(url) : ''
}

/** "example.com" of a source link. */
export function ideasSourceHost(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return String(url || '')
  }
}

/** The brief fields that went to the model, as [field, text] pairs, in the window's order. */
export function ideasSentFields(brief) {
  const out = []
  for (const k of IDEAS_TEXT_FIELDS) if (String(brief?.[k] || '').trim()) out.push([k, String(brief[k]).trim()])
  return out
}

/** The jobs page: «Open» on an ideas job leads to its card in the chat (known once the job is done). */
export function ideasJobRoute(id, job) {
  const chatId = job?.result_json?.chat_id
  if (!chatId) return null
  const messageId = job.result_json.message_id
  return messageId ? `/chat/${chatId}?message=${messageId}` : `/chat/${chatId}`
}

// ── the window's draft ──
// What was typed into the window and not sent stays for this tab, per chat.

const drafts = new Map()

export function ideasDraftKeep(chatId, form) {
  if (chatId) drafts.set(chatId, JSON.parse(JSON.stringify(form)))
}

export function ideasDraftTake(chatId) {
  const form = drafts.get(chatId) || null
  drafts.delete(chatId)
  return form
}
