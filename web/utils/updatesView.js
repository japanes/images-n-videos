/**
 * Pure helpers of the updates screen and the header notice: release notes
 * (Markdown) parsed into plain blocks that Vue renders as text — never as
 * HTML — plus labels, tones and small decisions shared by both places.
 */
import { apiErrorText } from './apiErrorText.js'

export const UPDATE_STATES = [
  'idle', 'checking', 'preparing', 'backing_up', 'pulling', 'applying', 'verifying', 'rolling_back', 'done', 'failed',
]
export const UPDATE_RESULTS = ['success', 'failed', 'rolled_back']
export const UPDATE_SOURCES = ['manual', 'auto', 'startup']
export const UPDATE_CHANNELS = ['stable', 'beta']

/** How often the screens ask the updater, in ms. */
export const POLL_ACTIVE_MS = 2500
export const POLL_IDLE_MS = 30_000
export const NOTICE_POLL_MS = 10 * 60_000

const NOTES_MAX_BLOCKS = 300
const CODE_MAX_CHARS = 5000

// ── links ────────────────────────────────────────────────────────────────────

/** Only plain web links leave the page; `javascript:`, `data:` and the rest are dropped. */
export function safeHref(url) {
  if (typeof url !== 'string') return null
  const value = url.trim()
  if (!/^https?:\/\/[^\s/]+/i.test(value)) return null
  if (/[\s<>"'`\\]/.test(value)) return null
  for (const ch of value) if (ch.charCodeAt(0) < 32 || ch.charCodeAt(0) === 127) return null
  return value
}

// ── inline Markdown ──────────────────────────────────────────────────────────

const INLINE_RE = new RegExp([
  '`(?<code>[^`\\n]+)`',
  '\\[(?<label>[^\\]\\n]+)\\]\\((?<href>[^)\\s]+)(?:\\s+"[^"]*")?\\)',
  '\\*\\*(?<strong>[^*\\n]+)\\*\\*',
  '(?<![\\w])__(?<strong2>[^_\\n]+)__(?![\\w])',
  '(?<![\\w*])\\*(?<em>[^*\\s][^*\\n]*?)\\*(?![\\w*])',
  '(?<![\\w])_(?<em2>[^_\\s][^_\\n]*?)_(?![\\w])',
  '(?<url>https?:\\/\\/[^\\s<>()\\[\\]]*[^\\s<>()\\[\\].,;:!?\'"])',
].join('|'), 'g')

/**
 * One line of Markdown → parts: { type: 'text'|'strong'|'em'|'code', text }
 * or { type: 'link', text, href }. Unsafe links become their plain label.
 */
export function parseInline(text) {
  const src = String(text ?? '')
  const parts = []
  const push = (type, value, extra = {}) => {
    if (!value) return
    const last = parts[parts.length - 1]
    if (type === 'text' && last?.type === 'text') last.text += value
    else parts.push({ type, text: value, ...extra })
  }
  let at = 0
  for (const m of src.matchAll(INLINE_RE)) {
    push('text', src.slice(at, m.index))
    at = m.index + m[0].length
    const g = m.groups
    if (g.code !== undefined) push('code', g.code)
    else if (g.label !== undefined) {
      const href = safeHref(g.href)
      if (href) push('link', g.label, { href })
      else push('text', g.label)
    } else if (g.strong !== undefined || g.strong2 !== undefined) push('strong', g.strong ?? g.strong2)
    else if (g.em !== undefined || g.em2 !== undefined) push('em', g.em ?? g.em2)
    else if (g.url !== undefined) {
      const href = safeHref(g.url)
      if (href) push('link', g.url, { href })
      else push('text', g.url)
    }
  }
  push('text', src.slice(at))
  return parts
}

// ── blocks ───────────────────────────────────────────────────────────────────

/** Neighbouring plain-text parts merged into one. */
function joinParts(parts) {
  const out = []
  for (const p of parts) {
    const last = out[out.length - 1]
    if (p.type === 'text' && last?.type === 'text') last.text += p.text
    else out.push({ ...p })
  }
  return out
}

function stripHtml(line) {
  return line.replace(/<\/?[a-zA-Z][\w-]*(?:\s[^<>]*)?\/?>/g, '')
}

/**
 * Release notes (GitHub Markdown) → blocks:
 *   { type: 'heading', level, parts } · { type: 'paragraph', lines: [parts] }
 *   { type: 'list', ordered, items: [{ depth, parts }] } · { type: 'quote', lines: [parts] }
 *   { type: 'code', text } · { type: 'rule' }
 * HTML comments and tags are dropped; nothing is ever turned into HTML.
 */
export function parseNotes(md, { maxBlocks = NOTES_MAX_BLOCKS } = {}) {
  const text = String(md ?? '').replace(/\r\n?/g, '\n').replace(/<!--[\s\S]*?(?:-->|$)/g, '')
  const lines = text.split('\n')
  const blocks = []
  let para = null
  let list = null
  let quote = null

  const flush = () => {
    if (para) blocks.push(para)
    if (list) blocks.push(list)
    if (quote) blocks.push(quote)
    para = list = quote = null
  }

  for (let i = 0; i < lines.length && blocks.length < maxBlocks; i++) {
    const raw = lines[i]
    const fence = raw.match(/^\s*(```|~~~)/)
    if (fence) {
      flush()
      const body = []
      for (i++; i < lines.length && !lines[i].trim().startsWith(fence[1]); i++) body.push(lines[i])
      blocks.push({ type: 'code', text: body.join('\n').slice(0, CODE_MAX_CHARS) })
      continue
    }
    const line = stripHtml(raw)
    if (!line.trim()) { flush(); continue }

    const heading = line.match(/^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$/)
    if (heading) {
      flush()
      if (heading[2]) blocks.push({ type: 'heading', level: heading[1].length, parts: parseInline(heading[2]) })
      continue
    }
    if (/^\s{0,3}([-*_])(?:\s*\1){2,}\s*$/.test(line)) { flush(); blocks.push({ type: 'rule' }); continue }

    const item = line.match(/^(\s*)(?:([-*+])|(\d{1,9})[.)])\s+(.*)$/)
    if (item) {
      const ordered = !item[2]
      if (!list || list.ordered !== ordered) {
        flush()
        list = { type: 'list', ordered, items: [] }
      }
      const depth = Math.min(3, Math.floor(item[1].replace(/\t/g, '    ').length / 2))
      list.items.push({ depth, parts: parseInline(item[4]) })
      continue
    }
    const q = line.match(/^\s*>\s?(.*)$/)
    if (q) {
      if (!quote) { flush(); quote = { type: 'quote', lines: [] } }
      if (q[1].trim()) quote.lines.push(parseInline(q[1].trim()))
      continue
    }
    if (list && /^\s+\S/.test(line)) {
      // A wrapped list item: glue it to the item above.
      const last = list.items[list.items.length - 1]
      last.parts = joinParts([...last.parts, { type: 'text', text: ' ' }, ...parseInline(line.trim())])
      continue
    }
    if (!para) { flush(); para = { type: 'paragraph', lines: [] } }
    para.lines.push(parseInline(line.trim()))
  }
  flush()
  return blocks.slice(0, maxBlocks)
}

// ── labels and decisions ─────────────────────────────────────────────────────

/** i18n key of an updater state; unknown states read as "working". */
export function stateKey(state) {
  return UPDATE_STATES.includes(state) ? `updates.state.${state}` : 'updates.state.unknown'
}

export function resultKey(result) {
  return UPDATE_RESULTS.includes(result) ? `updates.result.${result}` : 'updates.result.unknown'
}

export function sourceKey(source) {
  return UPDATE_SOURCES.includes(source) ? `updates.source.${source}` : 'updates.source.unknown'
}

/** Tailwind classes of a result badge. */
export function resultTone(result) {
  if (result === 'success') return 'bg-emerald-100 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-200'
  if (result === 'rolled_back') return 'bg-amber-100 text-amber-900 dark:bg-amber-500/15 dark:text-amber-200'
  if (result === 'failed') return 'bg-rose-100 text-rose-800 dark:bg-rose-500/15 dark:text-rose-200'
  return 'bg-slate-100 text-slate-700 dark:bg-slate-700 dark:text-slate-200'
}

export function isUpdateRunning(op) {
  return !!op?.active
}

/** "Install anyway" makes sense only while an install waits for running jobs. */
export function canForce(op) {
  return !!(op?.active && op.kind === 'install' && op.state === 'preparing' && !op.force
    && op.to && Array.isArray(op.busy) && op.busy.length)
}

/** The updater can be asked to install something (it is there and not in developer mode). */
export function canInstall(overview) {
  return !!(overview?.reachable && overview.updater && !overview.updater.dev)
}

/**
 * What the header notice shows:
 *   { kind: 'running', version } while an update goes on,
 *   { kind: 'available', version, release } when a newer version can be installed,
 *   null otherwise (updater missing, developer mode, nothing new, dismissed).
 */
export function noticeFor(overview, { dismissed = null } = {}) {
  if (!canInstall(overview)) return null
  const u = overview.updater
  const op = u.operation
  if (isUpdateRunning(op)) return { kind: 'running', version: op.to || '' }
  const version = overview.newest
  if (!version || version === dismissed) return null
  const release = (u.available || []).find((r) => r.version === version)
  if (!release?.installable) return null
  return { kind: 'available', version, release }
}

/** Only the settings that differ from what the updater has. */
export function settingsDiff(saved, draft) {
  const out = {}
  for (const key of ['auto', 'time', 'tz', 'channel']) {
    if (draft?.[key] === undefined || draft[key] === null || draft[key] === '') continue
    if (draft[key] !== saved?.[key]) out[key] = draft[key]
  }
  return out
}

export function draftFrom(status) {
  return {
    auto: !!status?.auto,
    time: status?.time || '03:00',
    tz: status?.tz || localTimeZone(),
    channel: UPDATE_CHANNELS.includes(status?.channel) ? status.channel : 'stable',
  }
}

export function localTimeZone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  } catch {
    return 'UTC'
  }
}

/** Time zones to pick from; the current and the saved one are always there. */
export function timeZones(saved) {
  let list = []
  try {
    list = typeof Intl.supportedValuesOf === 'function' ? Intl.supportedValuesOf('timeZone') : []
  } catch {
    list = []
  }
  const set = new Set(list)
  for (const tz of [saved, localTimeZone(), 'UTC']) if (tz) set.add(tz)
  return [...set].sort((a, b) => a.localeCompare(b))
}

/** The browser lost the app (it is restarting during an update, or stopped). */
export function isConnectionLost(err) {
  if (err?.code === 'network') return true
  return [502, 503, 504].includes(err?.status) && /^http_/.test(String(err?.code || ''))
}

/** Text of a failed call: this module's own wording first, then the shared one. */
export function updatesErrorText(err, t, te) {
  const code = err?.code || 'unknown'
  const key = `updates.errors.${code}`
  if (te ? te(key) : t(key) !== key) return t(key, { ...(err?.details || {}), message: err?.message || '' })
  return apiErrorText(err, t, te)
}
