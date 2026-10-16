/**
 * Pure helpers of the clip editor (module 12): time arithmetic over the edit
 * list, layer and subtitle helpers for the browser preview, undo history and
 * error texts. The backend (app/vf/modules/clip/state.py) is the authority:
 * it cleans every saved state, these helpers only mirror it for the screen.
 *
 * Every export starts with `clip` because files in utils/ are auto-imported
 * into the whole app.
 *
 * Opening the editor from another screen:
 *
 *   navigateTo(clipEditorRoute(file.id))   // "/clip/new?file=<id>"
 */
import { apiErrorText } from './apiErrorText.js'

export const CLIP_ASPECTS = ['', '9:16', '1:1', '4:5', '16:9']
export const CLIP_ASPECT_SIZES = { '9:16': [1080, 1920], '1:1': [1080, 1080], '16:9': [1920, 1080], '4:5': [1080, 1350] }
export const CLIP_CROP_MODES = ['cover', 'blur', 'pad']
export const CLIP_TRACK_ROLES = ['music', 'voice', 'sfx']
export const CLIP_SUBTITLE_MODES = ['', 'line', 'word']
export const CLIP_SUBTITLE_POSITIONS = ['', 'bottom', 'middle', 'top']
export const CLIP_BUILTIN_FONTS = ['DejaVu Sans', 'DejaVu Serif', 'DejaVu Sans Mono', 'Liberation Sans',
  'Liberation Serif', 'Liberation Mono']
export const CLIP_STT_MODELS = ['large-v3-turbo', 'small']
export const CLIP_STT_LANGUAGES = ['auto', 'ru', 'uk', 'en']
export const CLIP_MAX_LAYERS = 40
export const CLIP_MAX_IMAGE_LAYERS = 16
export const CLIP_MAX_TRACKS = 8
export const CLIP_MAX_CUTS = 48
export const CLIP_MAX_REMOVED = 48
export const CLIP_MAX_PIECES = 24 // kept pieces per export (server MAX_PIECES)
export const CLIP_MIN_SEGMENT = 0.05
export const CLIP_MIN_CLIP = 0.1
export const CLIP_SAVE_DELAY_MS = 1200
export const CLIP_HISTORY_LIMIT = 50
// libass sizes a font by its full line height (ascent + descent); CSS by the em.
// For the DejaVu / Liberation families that line is about 1.16 em.
export const CLIP_ASS_LINE = 1.16
const SUB_HOLD_S = 0.35
const SUB_MAX_GAP_S = 0.8

/** Where the editor opens for a video file: it finds or creates the project. */
export function clipEditorRoute(fileId) {
  return `/clip/new?file=${encodeURIComponent(String(fileId))}`
}

export function clipProjectRoute(projectId) {
  return `/clip/${encodeURIComponent(String(projectId))}`
}

const round3 = (v) => Math.round(v * 1000) / 1000
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v))

/** 65.25 -> "1:05.2"; 3725 -> "1:02:05.0"; tenths=false drops the fraction. */
export function clipFormatTime(seconds, { tenths = true } = {}) {
  const v = Math.max(0, Number(seconds) || 0)
  const whole = tenths ? Math.floor(v) : Math.round(v)
  const h = Math.floor(whole / 3600)
  const m = Math.floor((whole % 3600) / 60)
  const s = String(whole % 60).padStart(2, '0')
  const base = h ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`
  if (!tenths) return base
  return `${base}.${Math.floor((v - whole) * 10 + 1e-6)}`
}

/** "1:05.2", "65.2", "1:02:05" -> seconds; anything else -> null. */
export function clipParseTime(text) {
  const raw = String(text ?? '').trim().replace(',', '.')
  if (!raw) return null
  const parts = raw.split(':')
  if (parts.length > 3 || parts.some((p) => !/^\d+(\.\d+)?$/.test(p))) return null
  return round3(parts.reduce((acc, p) => acc * 60 + Number(p), 0))
}

/** End of the clip on the source time line (trim end, else the whole video). */
export function clipTrimEnd(state, duration) {
  const end = state?.trim?.end
  return end === null || end === undefined ? Number(duration) || 0 : Number(end)
}

/** Kept pieces of the source: trim minus removed ranges (mirror of state.segments). */
export function clipSegments(state, duration) {
  const start = Number(state?.trim?.start) || 0
  const end = clipTrimEnd(state, duration)
  const removed = [...(state?.removed || [])].map(([a, b]) => [Number(a), Number(b)]).sort((x, y) => x[0] - y[0])
  const out = []
  let cursor = start
  for (const [a, b] of removed) {
    if (b <= cursor) continue
    if (a >= end) break
    if (a > cursor) out.push([cursor, Math.min(a, end)])
    cursor = Math.max(cursor, b)
  }
  if (cursor < end) out.push([cursor, end])
  return out.filter(([a, b]) => b - a >= CLIP_MIN_SEGMENT).map(([a, b]) => [round3(a), round3(b)])
}

export function clipOutputDuration(segs) {
  return round3((segs || []).reduce((sum, [a, b]) => sum + (b - a), 0))
}

/** Source time -> time in the result, or null when that moment is cut away. */
export function clipToOutput(t, segs) {
  let offset = 0
  for (const [a, b] of segs || []) {
    if (t >= a && t <= b) return round3(offset + t - a)
    offset += b - a
  }
  return null
}

/**
 * Where playback should continue from source time `t` so the screen plays what
 * the export will contain: `t` itself inside a kept piece, the start of the next
 * kept piece otherwise, null after the end.
 */
export function clipNextKept(t, segs) {
  for (const [a, b] of segs || []) {
    if (t < a) return a
    if (t < b - 0.01) return t
  }
  return null
}

/** Copy of `removed` with [a, b] added and overlapping ranges merged. */
export function clipAddRemoved(removed, a, b) {
  const lo = Math.min(a, b)
  const hi = Math.max(a, b)
  if (hi - lo < CLIP_MIN_SEGMENT) return [...(removed || [])].map((r) => [...r])
  const all = [...(removed || []).map((r) => [Number(r[0]), Number(r[1])]), [round3(lo), round3(hi)]]
    .sort((x, y) => x[0] - y[0])
  const out = []
  for (const r of all) {
    const last = out[out.length - 1]
    if (last && r[0] <= last[1]) last[1] = Math.max(last[1], r[1])
    else out.push([...r])
  }
  return out
}

/** The removed range under time `t`, as an index, or -1. */
export function clipRemovedAt(removed, t) {
  return (removed || []).findIndex(([a, b]) => t >= a && t <= b)
}

/** Split marks: adds a mark at `t`, or drops the one within `near` seconds of it. */
export function clipToggleCut(cuts, t, near = 0.15) {
  const list = [...(cuts || [])]
  const i = list.findIndex((c) => Math.abs(c - t) <= near)
  if (i >= 0) {
    list.splice(i, 1)
    return list
  }
  if (list.length >= CLIP_MAX_CUTS) return list
  return [...list, round3(t)].sort((x, y) => x - y)
}

/** Split marks moved to result time, the way an export "in parts" uses them (server `part_points`). */
export function clipPartPoints(cuts, segs) {
  const total = clipOutputDuration(segs)
  const points = []
  for (const c of cuts || []) {
    const t = clipToOutput(Number(c), segs)
    if (t !== null && t > CLIP_MIN_SEGMENT && t < total - CLIP_MIN_SEGMENT) points.push(t)
  }
  const out = []
  for (const p of points.sort((a, b) => a - b)) {
    if (!out.length || p - out[out.length - 1] >= CLIP_MIN_SEGMENT) out.push(p)
  }
  return out.slice(0, CLIP_MAX_CUTS)
}

/** Frame of the result: the chosen aspect's size, else the source size (even numbers). */
export function clipFrameSize(state, source) {
  const preset = CLIP_ASPECT_SIZES[state?.crop?.aspect || '']
  if (preset) return { width: preset[0], height: preset[1] }
  const even = (n) => {
    const v = Math.max(2, Math.round(n))
    return v % 2 ? v - 1 : v
  }
  const w = Number(source?.width) || 0
  const h = Number(source?.height) || 0
  if (w && h) return { width: even(w), height: even(h) }
  return { width: 1920, height: 1080 }
}

function newId() {
  return Math.random().toString(36).slice(2, 12)
}

/** A new text layer on screen from `start` (seconds of the source) to the end. */
export function clipNewTextLayer(text, start = 0, extra = {}) {
  return {
    id: newId(), type: 'text', start: round3(Math.max(0, start)), end: null, x: 0.5, y: 0.2, visible: true,
    text, font: CLIP_BUILTIN_FONTS[0], font_file_id: null, size: 0.06, color: '#FFFFFF', bold: true,
    italic: false, outline: true, plate: false, plate_color: '#000000', plate_opacity: 0.6, ...extra,
  }
}

/** A new picture layer (logo, sticker) in the top right corner. */
export function clipNewImageLayer(fileId, start = 0, extra = {}) {
  return {
    id: newId(), type: 'image', start: round3(Math.max(0, start)), end: null, x: 0.85, y: 0.12, visible: true,
    file_id: fileId, width: 0.18, opacity: 1, ...extra,
  }
}

export function clipNewTrack(fileId, extra = {}) {
  return { id: newId(), file_id: fileId, role: 'music', volume: 0.8, delay: 0, fade_in: 0, fade_out: 0, duck: false, ...extra }
}

/** Is the layer on screen at source time `t`? */
export function clipLayerActive(layer, t) {
  if (!layer || layer.visible === false) return false
  const end = layer.end === null || layer.end === undefined ? Infinity : layer.end
  return t >= (layer.start || 0) && t <= end
}

/** Copy of `list` with the item at `from` moved by `step` places (out of range -> plain copy). */
export function clipMove(list, from, step) {
  const out = [...(list || [])]
  const to = from + step
  if (from < 0 || from >= out.length || to < 0 || to >= out.length) return out
  const [item] = out.splice(from, 1)
  out.splice(to, 0, item)
  return out
}

/** Can one more layer of this type be added (backend limits)? */
export function clipCanAddLayer(layers, type) {
  const list = layers || []
  if (list.length >= CLIP_MAX_LAYERS) return false
  if (type === 'image') return list.filter((l) => l.type === 'image').length < CLIP_MAX_IMAGE_LAYERS
  return true
}

// ── subtitles ───────────────────────────────────────────────────────────────

/** The word stream cut into on-screen lines (mirror of subtitles.group_lines). */
export function clipGroupLines(words, maxWords = 4) {
  const limit = Math.max(1, Number(maxWords) || 1)
  const lines = []
  let current = []
  for (const word of words || []) {
    if (current.length) {
      const last = current[current.length - 1]
      const gap = word.start - last.end
      const endsSentence = /[.!?…]$/.test(last.text)
      if (current.length >= limit || gap > SUB_MAX_GAP_S || endsSentence) {
        lines.push(current)
        current = []
      }
    }
    current.push(word)
  }
  if (current.length) lines.push(current)
  return lines
}

/**
 * What the captions show at source time `t`: `{ words, lit }` (lit = index of
 * the spoken word) or null. `mode` "word" shows one word at a time.
 */
export function clipCaptionAt(words, t, { mode = 'line', maxWords = 4 } = {}) {
  const list = words || []
  if (!list.length) return null
  if (mode === 'word') {
    for (let i = 0; i < list.length; i++) {
      const w = list[i]
      const next = list[i + 1]
      const end = next && next.start - w.end <= SUB_MAX_GAP_S ? next.start : w.end + SUB_HOLD_S
      if (t >= w.start && t < end) return { words: [w], lit: 0 }
    }
    return null
  }
  const lines = clipGroupLines(list, maxWords)
  for (let li = 0; li < lines.length; li++) {
    const line = lines[li]
    let end = line[line.length - 1].end + SUB_HOLD_S
    if (lines[li + 1]) end = Math.min(end, lines[li + 1][0].start)
    if (t >= line[0].start && t < end) {
      let lit = 0
      for (let wi = 0; wi < line.length; wi++) if (t >= line[wi].start) lit = wi
      return { words: line, lit }
    }
  }
  return null
}

/**
 * New words for an edited caption line. Same number of words: only the texts
 * change. Otherwise the line's time span is shared out by word length.
 */
export function clipRetimeLine(line, text) {
  const tokens = String(text ?? '').split(/\s+/).map((s) => s.trim()).filter(Boolean).map((s) => s.slice(0, 100))
  if (!line?.length || !tokens.length) return []
  if (tokens.length === line.length) return line.map((w, i) => ({ ...w, text: tokens[i] }))
  const start = line[0].start
  const span = Math.max(0.06 * tokens.length, line[line.length - 1].end - start)
  const total = tokens.reduce((sum, w) => sum + w.length + 1, 0)
  let at = start
  return tokens.map((word) => {
    const len = (span * (word.length + 1)) / total
    const out = { text: word, start: round3(at), end: round3(at + len) }
    at += len
    return out
  })
}

/** Replace one line (by index in clipGroupLines) inside the word list. */
export function clipReplaceLine(words, maxWords, index, text) {
  const lines = clipGroupLines(words, maxWords)
  if (index < 0 || index >= lines.length) return [...(words || [])]
  lines[index] = clipRetimeLine(lines[index], text)
  return lines.flat()
}

/** The preset after the editor's own position and mode choices. */
export function clipEffectivePreset(preset, subtitles) {
  if (!preset) return null
  const out = { ...preset }
  const pos = subtitles?.position
  if (pos === 'bottom') out.alignment = 2
  if (pos === 'middle') { out.alignment = 5; out.margin_v_ratio = 0 }
  if (pos === 'top') out.alignment = 8
  if ((pos === 'bottom' || pos === 'top') && !out.margin_v_ratio) out.margin_v_ratio = 0.1
  out.mode = subtitles?.mode || preset.mode || 'line'
  return out
}

/** Relative brightness of a #RRGGBB color, 0 (black) .. 1 (white). */
export function clipLuma(hex) {
  const m = String(hex || '').match(/^#?([0-9a-f]{6})$/i)
  if (!m) return 0
  const n = parseInt(m[1], 16)
  return (0.2126 * ((n >> 16) & 255) + 0.7152 * ((n >> 8) & 255) + 0.0722 * (n & 255)) / 255
}

/** Uploaded fonts of a brand snapshot (they have a file), display font first. */
export function clipBrandFonts(brand) {
  const fonts = (brand?.fonts || []).filter((f) => f.file_id && f.family)
  return [...fonts.filter((f) => f.category === 'display'), ...fonts.filter((f) => f.category !== 'display')]
}

/** The brand kit folded into a preset that asks for it (mirror of subtitles.resolve_brand). */
export function clipResolveBrand(preset, brand) {
  if (!preset?.use_brand || !brand) return preset
  const out = { ...preset }
  const font = clipBrandFonts(brand)[0]
  if (font) {
    out.font_family = font.family
    out.font_file_id = font.file_id
  }
  const hexes = (brand.colors || []).map((c) => c.hex).filter(Boolean)
  if (hexes.length) {
    out.highlight_color = hexes[0]
    const darkest = hexes.reduce((a, b) => (clipLuma(b) < clipLuma(a) ? b : a))
    out.outline_color = clipLuma(darkest) < 0.45 ? darkest : '#000000'
  }
  return out
}

// ── browser preview styles ─────────────────────────────────────────────────

function rgba(hex, alpha) {
  const m = String(hex || '').match(/^#?([0-9a-f]{6})$/i)
  if (!m) return `rgba(0,0,0,${alpha})`
  const n = parseInt(m[1], 16)
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`
}

function outlineShadow(color, px) {
  if (px <= 0) return 'none'
  const r = Math.max(1, Math.round(px * 10) / 10)
  return [`${-r}px 0`, `${r}px 0`, `0 ${-r}px`, `0 ${r}px`, `${-r}px ${-r}px`, `${r}px ${r}px`,
    `${-r}px ${r}px`, `${r}px ${-r}px`].map((o) => `${o} 0 ${color}`).join(', ')
}

/** CSS for a text layer drawn over a frame of `frameHeight` screen pixels. */
export function clipTextStyle(layer, frameHeight) {
  const px = ((Number(layer.size) || 0.05) * frameHeight) / CLIP_ASS_LINE
  const style = {
    left: `${(layer.x ?? 0.5) * 100}%`,
    top: `${(layer.y ?? 0.5) * 100}%`,
    fontFamily: `"${layer.font || CLIP_BUILTIN_FONTS[0]}", sans-serif`,
    fontSize: `${px}px`,
    lineHeight: CLIP_ASS_LINE,
    color: layer.color || '#FFFFFF',
    fontWeight: layer.bold ? 700 : 400,
    fontStyle: layer.italic ? 'italic' : 'normal',
    textShadow: layer.outline && !layer.plate ? outlineShadow('#000000', px * 0.08) : 'none',
  }
  if (layer.plate) {
    style.background = rgba(layer.plate_color, layer.plate_opacity ?? 0.6)
    style.padding = `0 ${px * 0.25}px`
  }
  return style
}

/** CSS for a picture layer (its width is a share of the frame width). */
export function clipImageStyle(layer) {
  return {
    left: `${(layer.x ?? 0.5) * 100}%`,
    top: `${(layer.y ?? 0.5) * 100}%`,
    width: `${(layer.width || 0.2) * 100}%`,
    opacity: layer.opacity ?? 1,
  }
}

/** CSS for the caption box: font, colors and where the preset puts it. */
export function clipCaptionStyle(preset, frameWidth, frameHeight) {
  const p = preset || {}
  const px = ((Number(p.font_size_ratio) || 0.045) * frameHeight) / CLIP_ASS_LINE
  const align = Number(p.alignment) || 2
  const margin = (Number(p.margin_v_ratio) || 0) * frameHeight
  const style = {
    left: `${(Number(p.margin_h_ratio) || 0) * frameWidth}px`,
    right: `${(Number(p.margin_h_ratio) || 0) * frameWidth}px`,
    fontFamily: `"${p.font_family || CLIP_BUILTIN_FONTS[0]}", sans-serif`,
    fontSize: `${px}px`,
    lineHeight: CLIP_ASS_LINE,
    fontWeight: p.bold ? 700 : 400,
    fontStyle: p.italic ? 'italic' : 'normal',
    textTransform: p.uppercase ? 'uppercase' : 'none',
    color: p.primary_color || '#FFFFFF',
  }
  if (align === 8) style.top = `${margin}px`
  else if (align === 5) { style.top = '50%'; style.transform = 'translateY(-50%)' }
  else style.bottom = `${margin}px`
  if (Number(p.border_style) === 3) {
    style.boxColor = rgba(p.back_color, Number(p.back_opacity) || 0.65)
    style.textShadow = 'none'
  } else {
    style.textShadow = outlineShadow(p.outline_color || '#000000', px * (Number(p.outline_ratio) || 0))
  }
  return style
}

// ── undo ────────────────────────────────────────────────────────────────────

/**
 * Snapshot history for undo / redo. Snapshots are JSON strings, so a later
 * change of the live state cannot reach into the past.
 */
export function clipCreateHistory(limit = CLIP_HISTORY_LIMIT) {
  let stack = []
  let index = -1
  return {
    reset(state) {
      stack = [JSON.stringify(state)]
      index = 0
    },
    push(state) {
      const snap = JSON.stringify(state)
      if (stack[index] === snap) return false
      stack = stack.slice(0, index + 1)
      stack.push(snap)
      if (stack.length > limit + 1) stack = stack.slice(stack.length - limit - 1)
      index = stack.length - 1
      return true
    },
    undo() {
      if (index <= 0) return null
      index -= 1
      return JSON.parse(stack[index])
    },
    redo() {
      if (index >= stack.length - 1) return null
      index += 1
      return JSON.parse(stack[index])
    },
    canUndo: () => index > 0,
    canRedo: () => index >= 0 && index < stack.length - 1,
    size: () => stack.length,
  }
}

// ── errors and progress ────────────────────────────────────────────────────

/** Error text: the editor's own `clip.errors.<code>` first, then the app-wide one. */
export function clipErrorText(err, t, te) {
  const code = err?.code || err?.error_code
  const key = `clip.errors.${code}`
  if (code && (te ? te(key) : t(key) !== key)) return t(key, { ...(err?.details || {}) })
  if (err?.error_code && !err?.code) {
    return apiErrorText({ code: err.error_code, message: err.error || '' }, t, te)
  }
  return apiErrorText(err, t, te)
}

/** Seconds -> rounded "about" figure for the time estimate: 40 -> 40, 95 -> 100, 610 -> 600. */
export function clipRoundSeconds(seconds) {
  const s = Math.max(0, Number(seconds) || 0)
  if (s < 60) return Math.max(5, Math.round(s / 5) * 5)
  if (s < 600) return Math.round(s / 10) * 10
  return Math.round(s / 60) * 60
}

/** Model facts from the stt list: `{ name, size_mb, downloaded, downloading, progress, error }`. */
export function clipSttModel(models, name) {
  return (models || []).find((m) => m.name === name) || null
}

/** Clip jobs of this project that are still queued or running, newest first. */
export function clipActiveJobs(jobs, projectId, kind) {
  return (jobs || [])
    .filter((j) => j.ref_type === 'clip' && Number(j.ref_id) === Number(projectId))
    .filter((j) => (kind ? j.kind === kind : true))
    .filter((j) => j.status === 'queued' || j.status === 'running')
    .sort((a, b) => b.id - a.id)
}

export { clamp as clipClamp }
