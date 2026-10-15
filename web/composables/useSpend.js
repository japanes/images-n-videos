/**
 * Spend log (module 03): helpers shared by the /spend page and its parts.
 *
 * Nuxt auto-imports every export of composables/, so everything here starts
 * with `spend`/`SPEND_`. The functions are pure (no Nuxt context) and are
 * covered by tests/spend.test.js.
 *
 * Days are the user's local days ("YYYY-MM-DD"); the backend gets the offset
 * from UTC in minutes, east positive (Kyiv in summer = 180).
 */

/** Groups on the chart; fixed order = fixed colour slot (see .spend-palette). */
export const SPEND_KINDS = ['image', 'video', 'text', 'other']
export const SPEND_PERIODS = ['today', '7d', '30d', 'month', '90d', 'all', 'custom']
export const SPEND_STATUSES = ['success', 'error', 'blocked', 'cancelled', 'running']
export const SPEND_DEFAULT_PERIOD = '30d'
export const SPEND_PAGE_SIZE = 50

const DAY_RE = /^\d{4}-\d{2}-\d{2}$/

/** Minutes east of UTC for the given moment. */
export function spendTzOffset(d = new Date()) {
  return -d.getTimezoneOffset() || 0
}

/** Local calendar day of a Date as "YYYY-MM-DD". */
export function spendIsoDay(d) {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

/** "YYYY-MM-DD" → local Date at midnight (no UTC shift), or null. */
export function spendParseDay(s) {
  if (!DAY_RE.test(String(s || ''))) return null
  const [y, m, d] = s.split('-').map(Number)
  const date = new Date(y, m - 1, d)
  return date.getFullYear() === y && date.getMonth() === m - 1 && date.getDate() === d ? date : null
}

function addDays(d, n) {
  const out = new Date(d.getFullYear(), d.getMonth(), d.getDate())
  out.setDate(out.getDate() + n)
  return out
}

/** Period preset → inclusive local days `{ from, to }`; null means "no bound". */
export function spendPeriodRange(period, today = new Date(), custom = {}) {
  const to = spendIsoDay(today)
  switch (period) {
    case 'today': return { from: to, to }
    case '7d': return { from: spendIsoDay(addDays(today, -6)), to }
    case '30d': return { from: spendIsoDay(addDays(today, -29)), to }
    case '90d': return { from: spendIsoDay(addDays(today, -89)), to }
    case 'month': return { from: spendIsoDay(new Date(today.getFullYear(), today.getMonth(), 1)), to }
    case 'custom': {
      let from = spendParseDay(custom.from) ? custom.from : null
      let end = spendParseDay(custom.to) ? custom.to : null
      if (from && end && from > end) [from, end] = [end, from]
      return { from, to: end }
    }
    default: return { from: null, to: null } // 'all'
  }
}

/** Default state of the filter row. */
export function spendDefaultFilters() {
  return {
    period: SPEND_DEFAULT_PERIOD,
    from: '',
    to: '',
    kind: '',
    status: '',
    model: '',
    purpose: '',
    stub: false,
    refType: '',
    refId: null,
    page: 1,
  }
}

const one = (v) => (Array.isArray(v) ? v[0] : v)
const str = (v) => (typeof one(v) === 'string' ? one(v).trim().slice(0, 200) : '')

/** Route query → filters (anything odd falls back to the default). */
export function spendFiltersFromQuery(query = {}) {
  const f = spendDefaultFilters()
  const period = str(query.period)
  if (SPEND_PERIODS.includes(period)) f.period = period
  if (spendParseDay(str(query.from))) f.from = str(query.from)
  if (spendParseDay(str(query.to))) f.to = str(query.to)
  f.kind = str(query.kind)
  f.status = str(query.status)
  f.model = str(query.model)
  f.purpose = str(query.purpose)
  f.stub = str(query.stub) === '1'
  f.refType = str(query.ref_type)
  const refId = Number(str(query.ref_id))
  f.refId = f.refType && Number.isInteger(refId) && str(query.ref_id) !== '' ? refId : null
  if (!f.refType) f.refId = null
  const page = Number(str(query.page))
  f.page = Number.isInteger(page) && page > 1 ? page : 1
  return f
}

/** Filters → route query, leaving out defaults so links stay short. */
export function spendFiltersToQuery(f) {
  const q = {}
  if (f.period && f.period !== SPEND_DEFAULT_PERIOD) q.period = f.period
  if (f.period === 'custom') {
    if (f.from) q.from = f.from
    if (f.to) q.to = f.to
  }
  for (const key of ['kind', 'status', 'model', 'purpose']) if (f[key]) q[key] = f[key]
  if (f.stub) q.stub = '1'
  if (f.refType) {
    q.ref_type = f.refType
    if (f.refId !== null && f.refId !== undefined) q.ref_id = String(f.refId)
  }
  if (f.page > 1) q.page = String(f.page)
  return q
}

/** Filters → query of /api/spend/stats and /api/spend/calls. */
export function spendApiQuery(f, { today = new Date(), tz = spendTzOffset(today) } = {}) {
  const { from, to } = spendPeriodRange(f.period, today, { from: f.from, to: f.to })
  const q = { tz }
  if (from) q.date_from = from
  if (to) q.date_to = to
  if (f.kind) q.kind = f.kind
  if (f.status) q.status = f.status
  if (f.model) q.model_id = f.model
  if (f.purpose) q.purpose = f.purpose
  if (f.stub) q.include_stub = true
  if (f.refType) {
    q.ref_type = f.refType
    if (f.refId !== null && f.refId !== undefined) q.ref_id = f.refId
  }
  return q
}

/** True when anything besides the period is narrowing the list. */
export function spendHasNarrowing(f) {
  return Boolean(f.kind || f.status || f.model || f.purpose || f.refType)
}

/** Round axis: 0…max in `count` equal steps of 1/2/2.5/5 × 10^k. */
export function spendNiceScale(value, count = 4) {
  const v = Number(value) || 0
  if (v <= 0) return { max: 1, step: 0.25, ticks: [0, 0.25, 0.5, 0.75, 1] }
  const raw = v / count
  const pow = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * pow).find((s) => s * count >= v - 1e-12) || 10 * pow
  const ticks = []
  for (let i = 0; i <= count; i++) ticks.push(Number((step * i).toPrecision(12)))
  return { max: ticks[ticks.length - 1], step, ticks }
}

/**
 * One stacked column: segments bottom→top in SPEND_KINDS order, as pixel
 * offsets from the baseline. `gap` px of surface colour separates segments
 * (taken from the lower segment, so the total height stays true).
 */
export function spendStack(byKind = {}, max, height, { gap = 2, minSegment = 1 } = {}) {
  const out = []
  if (!(max > 0) || !(height > 0)) return out
  let y = 0
  const parts = SPEND_KINDS.map((kind) => ({ kind, usd: Number(byKind?.[kind]) || 0 })).filter((p) => p.usd > 0)
  parts.forEach((p, i) => {
    const h = Math.max((p.usd / max) * height, minSegment)
    const last = i === parts.length - 1
    const drawn = last ? h : Math.max(h - gap, minSegment / 2)
    out.push({ kind: p.kind, usd: p.usd, y0: y, y1: y + drawn, top: last })
    y += h
  })
  return out
}

/** Every k-th day gets a label so ~`labelPx` wide labels never collide. */
export function spendLabelEvery(count, width, labelPx = 52) {
  if (!count || !width) return 1
  const slot = width / count
  return Math.max(1, Math.ceil(labelPx / slot))
}

/** Meter tone for "spent of the credit". */
export function spendMeterTone(pct) {
  const p = Number(pct)
  if (!Number.isFinite(p)) return 'ok'
  if (p >= 100) return 'over'
  if (p >= 80) return 'warn'
  return 'ok'
}

/** Localised name of a kind/purpose/status/ref type, the raw key when unknown. */
export function spendLabel(t, te, group, key) {
  if (key === null || key === undefined || key === '') return '—'
  const path = `spend.${group}.${key}`
  if (te(path)) return t(path)
  return String(key).replace(/_/g, ' ')
}

/** Does an `ai_call.finished` event (refs: [[type, id], …]) touch this object? */
export function spendRefMatches(refs, refType, refId) {
  return Array.isArray(refs) && refs.some((r) => Array.isArray(r) && r[0] === refType && Number(r[1]) === Number(refId))
}

/** What a call consumed, as [localeKey, params] pairs (the table shows them joined). */
export function spendUnitParts(call = {}) {
  const parts = []
  if (call.tokens_in || call.tokens_out) {
    parts.push(['spend.units.tokens', { in: num(call.tokens_in), out: num(call.tokens_out) }])
  }
  if (call.tokens_thinking) parts.push(['spend.units.thinking', { n: num(call.tokens_thinking) }])
  if (call.video_seconds) parts.push(['spend.units.seconds', { n: num(call.video_seconds) }])
  if (call.output_video_seconds && !call.video_seconds) {
    parts.push(['spend.units.seconds', { n: num(call.output_video_seconds) }])
  }
  if (call.input_video_seconds) parts.push(['spend.units.inputSeconds', { n: num(call.input_video_seconds) }])
  if (call.search_queries) parts.push(['spend.units.searches', { n: num(call.search_queries) }])
  return parts
}

function num(v) {
  const n = Number(v) || 0
  return Number.isInteger(n) ? n.toLocaleString('en-US').replace(/,/g, ' ') : String(Math.round(n * 10) / 10)
}

/** Pretty JSON for the call card; strings that are JSON get parsed first. */
export function spendPrettyJson(value) {
  if (value === null || value === undefined || value === '') return ''
  let v = value
  if (typeof v === 'string') {
    try { v = JSON.parse(v) } catch { return value }
  }
  try { return JSON.stringify(v, null, 2) } catch { return String(value) }
}

/** Trailing-edge debounce with `.cancel()`. */
export function spendDebounce(fn, ms = 800) {
  let timer = null
  const run = (...args) => {
    clearTimeout(timer)
    timer = setTimeout(() => { timer = null; fn(...args) }, ms)
  }
  run.cancel = () => { clearTimeout(timer); timer = null }
  return run
}
