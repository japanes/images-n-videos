/**
 * Text on a picture (module 06): the full-screen tool opened from a picture in
 * the chat. Pure helpers: words and layers, box math of the canvas, request
 * bodies of the paid steps, prices, error texts, the jobs link.
 *
 * Boxes are fractions of the picture (0..1), the same as the backend keeps.
 * Layers go bottom first. The canvas itself is the server's drawing (Pillow),
 * the boxes are drawn over it.
 */
import { chatErrorText, chatItemError } from './chatView.js'

export const TEXT_LANGUAGES = ['ru', 'uk', 'en']
export const TEXT_ROLES = ['headline', 'body', 'accent']
export const TEXT_SIZES = ['sm', 'md', 'lg', 'xl']
export const TEXT_ALIGNS = ['left', 'center', 'right']
export const TEXT_VERTICALS = ['top', 'middle', 'bottom']
export const TEXT_SHAPES = ['rect', 'ellipse']
export const TEXT_TABS = ['words', 'layers', 'generate']
export const TEXT_DEFAULT_SIZE = { headline: 'xl', body: 'md', accent: 'lg' }
export const TEXT_MAX_TEXTS = 8
export const TEXT_MAX_TEXT = 600
export const TEXT_MAX_LAYERS = 30
export const TEXT_MAX_VARIANTS = 4
export const TEXT_MAX_BACKGROUNDS = 4
export const TEXT_MAX_PROMPT = 4000
export const TEXT_MAX_NOTE = 1000
export const TEXT_MAX_LAYOUT_TITLE = 80
export const TEXT_MIN_SIDE = 0.02
export const TEXT_SAVE_MS = 450 // a change is kept as a draft this long after the last touch
export const TEXT_ESTIMATE_MS = 400
export const TEXT_PREVIEW_SIDE = 1280
export const TEXT_FALLBACK_FONT = 'Roboto'
export const TEXT_HANDLES = ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w']
// Where the words of a block came from after «Place the text».
export const TEXT_PLACE_SOURCES = ['layer', 'zone', 'vision', 'fallback']
export const TEXT_ERROR_CODES = [
  'bad_image', 'bad_layer', 'builtin_layout', 'busy', 'empty_layout', 'empty_prompt', 'font_download_failed',
  'font_in_kit', 'fonts_unreachable', 'font_unreadable', 'no_picture', 'no_text', 'not_an_image', 'not_ready',
  'placement_empty', 'text_empty', 'too_long', 'too_many_layers', 'too_many_layouts', 'too_many_texts', 'no_design',
]
// Built-in layouts (their names live in the locale).
export const TEXT_BUILTIN_LAYOUTS = ['bottom_caption', 'top_title', 'center_card', 'bottom_band', 'corner_badge']

const has = (t, te, key) => (te ? te(key) : t(key) !== key)
const round4 = (v) => Math.round(v * 10000) / 10000
const clamp = (v, low, high) => Math.min(Math.max(v, low), high)

/** The language of the words: the interface language when the model writes in it. */
export function textDefaultLanguage(locale) {
  const code = String(locale || '').slice(0, 2).toLowerCase()
  return TEXT_LANGUAGES.includes(code) ? code : 'en'
}

// ── ids ──

/** A free id like `t3` / `l5` among the given items. */
export function textFreeId(items, prefix) {
  const taken = new Set((items || []).map((x) => String(x?.id)))
  let n = (items || []).length + 1
  while (taken.has(`${prefix}${n}`)) n += 1
  return `${prefix}${n}`
}

// ── words ──

/** A new empty block of words (at most 8). */
export function textNewBlock(texts, role = 'body') {
  const r = TEXT_ROLES.includes(role) ? role : 'body'
  return { id: textFreeId(texts, 't'), role: r, text: '', size: TEXT_DEFAULT_SIZE[r], locked: false }
}

export function textCanAddBlock(texts) {
  return (texts || []).length < TEXT_MAX_TEXTS
}

/** Remove a block and the text layers that show it (they would keep stale words otherwise). */
export function textRemoveBlock(texts, layers, id) {
  return {
    texts: (texts || []).filter((x) => x.id !== id),
    layers: (layers || []).filter((l) => !(l.type === 'text' && l.block_id === id)),
  }
}

/** Text layers tied to a block show its words and role (the backend does the same). */
export function textBindTexts(layers, texts) {
  const byId = new Map((texts || []).map((x) => [x.id, x]))
  return (layers || []).map((l) => {
    if (l.type !== 'text' || !l.block_id) return l
    const block = byId.get(l.block_id)
    return block ? { ...l, text: block.text, role: block.role } : { ...l, block_id: null }
  })
}

/** Blocks with words that no visible layer shows yet. */
export function textUnplaced(texts, layers) {
  const shown = new Set((layers || []).filter((l) => l.type === 'text' && l.block_id).map((l) => l.block_id))
  return (texts || []).filter((x) => String(x.text || '').trim() && !shown.has(x.id))
}

/** Put a picked variant into a block. */
export function textPutVariant(texts, id, line) {
  return (texts || []).map((x) => (x.id === id ? { ...x, text: String(line || '').slice(0, TEXT_MAX_TEXT) } : x))
}

// ── layers ──

const BOX_TEXT = { x: 0.06, y: 0.66, w: 0.88, h: 0.28 }
const BOX_LOGO = { x: 0.78, y: 0.86, w: 0.16, h: 0.1 }
const BOX_SHAPE = { x: 0.1, y: 0.7, w: 0.8, h: 0.2 }

/** A new text layer, tied to a block when one is given. */
export function textNewTextLayer(layers, block = null, font = null) {
  const role = block?.role && TEXT_ROLES.includes(block.role) ? block.role : 'body'
  return {
    id: textFreeId(layers, 'l'), type: 'text', block_id: block?.id || null, role,
    text: block?.text || '', font: font?.file_id || font?.family ? { file_id: font.file_id || null, family: font.family || '' } : null,
    size: block?.size || TEXT_DEFAULT_SIZE[role], font_size: null, color: '#FFFFFF', align: 'center',
    vertical: 'middle', bold: role === 'headline', uppercase: false, line_height: 1.28, scrim: false, shadow: false,
    ...BOX_TEXT, visible: true, opacity: 1,
  }
}

export function textNewLogoLayer(layers, fileId = null) {
  return { id: textFreeId(layers, 'l'), type: 'logo', file_id: fileId || null, ...BOX_LOGO, visible: true, opacity: 1 }
}

export function textNewShapeLayer(layers, shape = 'rect') {
  return {
    id: textFreeId(layers, 'l'), type: 'shape', shape: TEXT_SHAPES.includes(shape) ? shape : 'rect',
    fill: '#111111', radius: 0, ...BOX_SHAPE, visible: true, opacity: 0.6,
  }
}

export function textCanAddLayer(layers) {
  return (layers || []).length < TEXT_MAX_LAYERS
}

/** Change one layer; a box change is kept inside the picture. */
export function textPatchLayer(layers, id, patch) {
  return (layers || []).map((l) => {
    if (l.id !== id) return l
    const next = { ...l, ...patch }
    return { ...next, ...textClampBox(next) }
  })
}

export function textRemoveLayer(layers, id) {
  return (layers || []).filter((l) => l.id !== id)
}

/** Move a layer one step up (+1, drawn later, on top) or down (-1). */
export function textMoveLayer(layers, id, dir) {
  const out = [...(layers || [])]
  const i = out.findIndex((l) => l.id === id)
  const j = i + (dir > 0 ? 1 : -1)
  if (i < 0 || j < 0 || j >= out.length) return out
  ;[out[i], out[j]] = [out[j], out[i]]
  return out
}

/** A layout of one's own keeps the boxes, not the words. */
export function textLayoutTemplate(layers) {
  return (layers || []).map((l) => (l.type === 'text' ? { ...l, text: '', block_id: null } : { ...l }))
}

/** The name of a layout: built-in ones from the locale. */
export function textLayoutTitle(layout, t, te) {
  const key = `text.layouts.${layout?.code}`
  if (layout?.builtin && layout?.code && has(t, te, key)) return t(key)
  return layout?.title || layout?.code || ''
}

/** What a layer is called in the list. */
export function textLayerLabel(layer, t) {
  if (layer?.type === 'text') {
    const words = String(layer.text || '').replace(/\s+/g, ' ').trim()
    return words ? (words.length > 32 ? `${words.slice(0, 31)}…` : words) : t('text.layers.emptyText')
  }
  if (layer?.type === 'logo') return t('text.layers.logo')
  return layer?.shape === 'ellipse' ? t('text.layers.ellipse') : t('text.layers.rect')
}

// ── box math (fractions of the picture) ──

/** `{x, y, w, h}` kept inside the picture, each side at least 0.02. */
export function textClampBox(box) {
  const w = round4(clamp(Number(box?.w) || TEXT_MIN_SIDE, TEXT_MIN_SIDE, 1))
  const h = round4(clamp(Number(box?.h) || TEXT_MIN_SIDE, TEXT_MIN_SIDE, 1))
  const x = round4(clamp(Number(box?.x) || 0, 0, 1 - w))
  const y = round4(clamp(Number(box?.y) || 0, 0, 1 - h))
  return { x, y, w, h }
}

/** The box moved by (dx, dy), stopped at the picture's edges. */
export function textMoveBox(box, dx, dy) {
  return textClampBox({ ...box, x: Number(box.x) + dx, y: Number(box.y) + dy })
}

/**
 * The box with one handle dragged by (dx, dy): `n`/`s`/`e`/`w` move one edge,
 * corners move two. The opposite edges stay put; a side never gets under 0.02.
 */
export function textResizeBox(box, handle, dx, dy) {
  let left = Number(box.x)
  let top = Number(box.y)
  let right = left + Number(box.w)
  let bottom = top + Number(box.h)
  const h = String(handle || '')
  if (h.includes('w')) left = clamp(left + dx, 0, right - TEXT_MIN_SIDE)
  if (h.includes('e')) right = clamp(right + dx, left + TEXT_MIN_SIDE, 1)
  if (h.includes('n')) top = clamp(top + dy, 0, bottom - TEXT_MIN_SIDE)
  if (h.includes('s')) bottom = clamp(bottom + dy, top + TEXT_MIN_SIDE, 1)
  return textClampBox({ x: left, y: top, w: right - left, h: bottom - top })
}

/** CSS of a box over the canvas, in percent. */
export function textBoxStyle(box) {
  const pc = (v) => `${round4(Number(v) * 100)}%`
  return { left: pc(box.x), top: pc(box.y), width: pc(box.w), height: pc(box.h) }
}

/** Font size of a text layer on the canvas, as a share of the picture height. */
export function textFontShare(layer) {
  const ratios = { sm: 0.032, md: 0.045, lg: 0.06, xl: 0.082 }
  return Number(layer?.font_size) || ratios[layer?.size] || ratios.md
}

// ── paid steps: what each press sends ──

/** The panels' settings when the tool opens: the backend's switches default off, these are visible here. */
export function textEmptyForms(language = 'en') {
  return {
    write: { use_neighbours: false, use_brief: true, use_tone: true, max_chars: 0, note: '' },
    variants: {
      blockId: '', note: '', count: 3, use_system: true, use_rules: true, use_language: true,
      use_tone: false, use_brief: false, max_chars: 0, feedback: '',
    },
    humanize: { use_language: true },
    place: { vision: false, replace: false },
    background: { prompt: '', count: 2, no_lettering: true, use_current: false },
    language,
  }
}

const n0 = (v, high) => clamp(Math.round(Number(v) || 0), 0, high)

export function textWriteBody(forms) {
  const f = forms.write
  return {
    use_neighbours: Boolean(f.use_neighbours), use_brief: Boolean(f.use_brief), use_tone: Boolean(f.use_tone),
    max_chars: n0(f.max_chars, TEXT_MAX_TEXT), language: forms.language, note: String(f.note || '').trim(),
  }
}

export function textVariantsBody(forms) {
  const f = forms.variants
  return {
    note: String(f.note || '').trim(), count: clamp(Math.round(Number(f.count) || 1), 1, TEXT_MAX_VARIANTS),
    use_system: Boolean(f.use_system), use_rules: Boolean(f.use_rules), use_language: Boolean(f.use_language),
    use_tone: Boolean(f.use_tone), use_brief: Boolean(f.use_brief), max_chars: n0(f.max_chars, TEXT_MAX_TEXT),
    feedback: String(f.feedback || '').trim(), language: forms.language,
  }
}

/** Variants need something to write about: the typed line or a ticked block. */
export function textVariantsReady(forms) {
  const f = forms.variants
  return Boolean(String(f.note || '').trim() || f.use_language || f.use_rules || f.use_tone || f.use_brief
    || n0(f.max_chars, TEXT_MAX_TEXT) || String(f.feedback || '').trim())
}

export function textHumanizeBody(forms, texts) {
  const ids = (texts || []).filter((x) => String(x.text || '').trim() && !x.locked).map((x) => x.id)
  return { text_ids: ids, use_language: Boolean(forms.humanize.use_language), language: forms.language }
}

export function textPlaceBody(forms) {
  return { vision: Boolean(forms.place.vision), replace: Boolean(forms.place.replace) }
}

export function textBackgroundsBody(forms) {
  const f = forms.background
  return {
    prompt: String(f.prompt || '').trim().slice(0, TEXT_MAX_PROMPT),
    count: clamp(Math.round(Number(f.count) || 1), 1, TEXT_MAX_BACKGROUNDS),
    no_lettering: Boolean(f.no_lettering), use_current: Boolean(f.use_current),
  }
}

/** GET /api/text/estimate for the open design and the panels' counts. */
export function textEstimateQuery(designId, forms) {
  return {
    design_id: designId || undefined,
    variants: clamp(Math.round(Number(forms.variants.count) || 1), 1, TEXT_MAX_VARIANTS),
    backgrounds: clamp(Math.round(Number(forms.background.count) || 1), 1, TEXT_MAX_BACKGROUNDS),
    use_current: Boolean(forms.background.use_current),
  }
}

/** The price of one button: a number, or null when unknown or refused (the refusal is shown instead). */
export function textPrice(entry) {
  if (!entry || entry.refusal) return null
  const v = Number(entry.usd)
  return Number.isFinite(v) ? v : null
}

/** «Place the text»: free unless the paid look at the picture is on. */
export function textPlacePrice(est, forms) {
  if (!forms.place.vision) return 0
  return textPrice(est?.placement)
}

/** Words a block got from where, for the line under «Place the text». */
export function textPlaceSummary(placement) {
  const out = {}
  for (const src of Object.values(placement?.sources || {})) out[src] = (out[src] || 0) + 1
  return TEXT_PLACE_SOURCES.filter((s) => out[s]).map((s) => ({ source: s, n: out[s] }))
}

// ── backgrounds ──

export function textBackgroundsBusy(backgrounds) {
  return (backgrounds || []).some((b) => b.status === 'queued' || b.status === 'running')
}

// ── what the renderer had to do ──

/** Lines under the canvas: letters drawn with another font, letters left out, words that did not fit. */
export function textReportNotes(report) {
  const out = []
  if (!report) return out
  if (report.fallback_chars) out.push({ key: 'text.report.fallback', params: { chars: report.fallback_chars, font: TEXT_FALLBACK_FONT } })
  if (report.missing_chars) out.push({ key: 'text.report.missing', params: { chars: report.missing_chars } })
  if (report.clipped?.length) out.push({ key: 'text.report.clipped', params: { n: report.clipped.length }, plural: report.clipped.length })
  if (report.missing_files?.length) out.push({ key: 'text.report.missingFiles', params: { n: report.missing_files.length }, plural: report.missing_files.length })
  return out
}

/** The `X-Render-Report` header as an object (null when absent or broken). */
export function textParseReport(header) {
  if (!header) return null
  try {
    const value = JSON.parse(header)
    return value && typeof value === 'object' ? value : null
  } catch {
    return null
  }
}

// ── errors ──

/** Error text: the module's own texts first, then the chat's chain. */
export function textErrorText(err, t, te) {
  const code = err?.code || ''
  const key = `text.errors.${code}`
  if (code && has(t, te, key)) return t(key, { ...(err?.details || {}), message: err?.message || '' })
  return chatErrorText(err, t, te)
}

/** Text of a refusal code from an estimate. */
export function textReasonText(code, t, te) {
  return code ? textErrorText({ code, details: {}, message: '' }, t, te) : ''
}

/** A failed background: our text plus Google's own words when they differ. */
export function textBackgroundError(bg, t, te) {
  const code = bg?.error_code || ''
  if (code && has(t, te, `text.errors.${code}`)) {
    const text = textReasonText(code, t, te)
    const raw = String(bg?.error || '').trim()
    return { text, detail: raw && raw !== text ? raw : '' }
  }
  return chatItemError(bg, t, te)
}

// ── the jobs page ──

/** «Open» on a background job leads to the chat message the tool was opened from. */
export function textJobRoute(_id, job) {
  const chatId = job?.result_json?.chat_id
  if (!chatId) return null
  const messageId = job.result_json.message_id
  return messageId ? `/chat/${chatId}?message=${messageId}` : `/chat/${chatId}`
}
