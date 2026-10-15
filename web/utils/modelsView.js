// Pure helpers for the "Models" and "Settings" screens (module 02).
// Nothing here knows a model id: everything is read from the registry data
// the backend sends.

export const MODEL_KINDS = ['image', 'video', 'text']
export const MODEL_TABS = [...MODEL_KINDS, 'roles']

const PER_MILLION = 1_000_000

const isNum = (v) => typeof v === 'number' && Number.isFinite(v)

/** 'available' | 'unavailable' | 'unchecked' after the last availability check. */
export function modelAvailability(model) {
  if (model?.available === true) return 'available'
  if (model?.available === false) return 'unavailable'
  return 'unchecked'
}

/**
 * Price lines of a model as `{ key, ...params }`; `key` is a message under
 * `models.price.*`, money params are numbers (format them in the view).
 */
export function modelPriceLines(model) {
  const p = model?.price || {}
  const lines = []
  if (isNum(p.input_per_1m) || isNum(p.output_per_1m)) {
    lines.push({ key: 'tokens', input: p.input_per_1m ?? null, output: p.output_per_1m ?? null })
  }
  if (model?.kind === 'image' && p.image_output_tokens && isNum(p.output_per_1m)) {
    const allowed = model.caps?.allowed_resolutions
    for (const [size, tokens] of Object.entries(p.image_output_tokens)) {
      if (Array.isArray(allowed) && !allowed.includes(size)) continue
      if (isNum(tokens)) lines.push({ key: 'perImage', size, usd: (tokens * p.output_per_1m) / PER_MILLION })
    }
  }
  if (p.per_second && typeof p.per_second === 'object') {
    for (const [res, usd] of Object.entries(p.per_second)) {
      if (isNum(usd)) lines.push({ key: 'perSecond', res: videoResolutionName(res), usd })
    }
  }
  if (model?.kind === 'video' && isNum(p.output_tokens_per_second) && isNum(p.output_per_1m)) {
    lines.push({ key: 'perSecondApprox', usd: (p.output_tokens_per_second * p.output_per_1m) / PER_MILLION })
  }
  if (isNum(p.search_per_request)) {
    lines.push({ key: p.search_unit === 'prompt' ? 'searchPrompt' : 'searchQuery', usd: p.search_per_request })
  }
  return lines
}

/** "4k" -> "4K", "1080p" stays. */
export function videoResolutionName(res) {
  const s = String(res || '').trim()
  return /^\d+k$/i.test(s) ? s.toUpperCase() : s
}

/** "720p,1080p@8,4k@8" (or a list) -> [{ res: '720p', only: [] }, { res: '1080p', only: [8] }, ...] */
export function parseVideoResolutions(raw) {
  const items = Array.isArray(raw) ? raw : String(raw || '').split(',')
  const out = []
  for (const item of items) {
    const [name, tail = ''] = String(item).trim().split('@')
    if (!name.trim()) continue
    const only = tail.split('|').map((x) => x.trim()).filter((x) => /^\d+$/.test(x)).map(Number)
    out.push({ res: videoResolutionName(name.trim().toLowerCase()), only })
  }
  return out
}

// Capabilities with a message of their own; anything else is shown as is.
const KNOWN_CAPS = new Set([
  'allowed_resolutions', 'max_output_dimension', 'accepts_references', 'max_references',
  'allowed_durations', 'allowed_aspects', 'max_duration_seconds', 'max_asset_references',
  'max_input_video_seconds', 'supports_negative_prompt', 'generates_audio', 'supports_audio_switch',
  'frame_shadows_references', 'accepts_images', 'json_mode', 'strict_schema', 'search', 'thinking',
])

/**
 * What a model can do, as chips `{ key, params }` (messages under
 * `models.caps.*`) or `{ raw }` for a capability this screen does not know yet.
 * Read only: capabilities change with the registry, not in the interface.
 */
export function modelCapChips(model) {
  const caps = model?.caps || {}
  const chips = []
  const add = (key, params = {}) => chips.push({ key, params })
  if (model?.kind === 'image') {
    if (Array.isArray(caps.allowed_resolutions) && caps.allowed_resolutions.length) {
      add('sizes', { list: caps.allowed_resolutions.join(', ') })
    }
    if (isNum(caps.max_output_dimension)) add('maxSide', { px: caps.max_output_dimension })
    if (caps.accepts_references === false) add('noReferences')
    else if (isNum(caps.max_references)) add('references', { count: caps.max_references })
    else if (caps.accepts_references) add('referencesAny')
  } else if (model?.kind === 'video') {
    if (Array.isArray(caps.allowed_durations) && caps.allowed_durations.length) {
      add('durations', { list: caps.allowed_durations.join(', ') })
    }
    for (const r of parseVideoResolutions(caps.allowed_resolutions)) {
      if (r.only.length) add('resolutionOnly', { res: r.res, seconds: r.only.join(', ') })
      else add('resolution', { res: r.res })
    }
    if (Array.isArray(caps.allowed_aspects) && caps.allowed_aspects.length) {
      add('aspects', { list: caps.allowed_aspects.join(', ') })
    }
    if (isNum(caps.max_asset_references)) {
      add(caps.max_asset_references > 0 ? 'references' : 'noReferences', { count: caps.max_asset_references })
    }
    if (isNum(caps.max_input_video_seconds) && caps.max_input_video_seconds > 0) {
      add('extends', { seconds: caps.max_input_video_seconds })
    }
    if (caps.supports_negative_prompt) add('negativePrompt')
    if (caps.generates_audio) add(caps.supports_audio_switch ? 'audioSwitch' : 'audioAlways')
    if (caps.frame_shadows_references) add('frameShadowsReferences')
  } else {
    if (caps.accepts_images) add('readsImages')
    if (caps.json_mode) add('json')
    if (caps.strict_schema) add('strictSchema')
    if (caps.search) add('search')
    if (caps.thinking) add('thinking')
  }
  for (const [key, value] of Object.entries(caps)) {
    if (KNOWN_CAPS.has(key) || value === null || value === false || value === undefined) continue
    chips.push({ raw: value === true ? key : `${key}: ${Array.isArray(value) ? value.join(', ') : JSON.stringify(value)}` })
  }
  return chips
}

/**
 * Money fields of a model the user may override, in the registry order:
 * `[{ path: 'input_per_1m', seed, value }, { path: 'per_second.720p', res: '720p', seed, value }]`.
 */
export function modelPriceFields(model) {
  const seed = model?.seed_price || {}
  const price = model?.price || {}
  const out = []
  for (const key of ['input_per_1m', 'output_per_1m', 'search_per_request']) {
    if (isNum(seed[key])) out.push({ path: key, seed: seed[key], value: isNum(price[key]) ? price[key] : seed[key] })
  }
  if (seed.per_second && typeof seed.per_second === 'object') {
    for (const [res, usd] of Object.entries(seed.per_second)) {
      if (!isNum(usd)) continue
      const now = price.per_second?.[res]
      out.push({ path: `per_second.${res}`, res: videoResolutionName(res), seed: usd, value: isNum(now) ? now : usd })
    }
  }
  return out
}

/**
 * Build the body of PUT /api/models/{id}/price from edited fields
 * (`{ path: '12.5' }`). Returns `{ price }` or `{ error: path }` for the first
 * value that is not a number of 0 or more. Only changes against the registry
 * price are sent; nothing changed means `{ price: null }` (use the registry).
 */
export function modelPriceBody(fields, values) {
  const price = {}
  for (const f of fields) {
    const raw = values?.[f.path]
    const text = String(raw ?? '').trim().replace(',', '.')
    const n = Number(text)
    if (!text || !Number.isFinite(n) || n < 0) return { error: f.path }
    if (n === f.seed) continue
    const [head, sub] = f.path.split('.')
    if (sub) price[head] = { ...(price[head] || {}), [sub]: n }
    else price[head] = n
  }
  return { price: Object.keys(price).length ? price : null }
}

/** Plain-number text for an input: 0.25 -> "0.25", 30 -> "30". */
export function priceInputText(value) {
  return isNum(value) ? String(Number(value.toPrecision(12))) : ''
}

/** Money with enough digits for small per-token or per-second prices. */
export function priceText(value) {
  if (!isNum(value)) return '—'
  if (value === 0) return '$0'
  if (value >= 1) return `$${Number.isInteger(value) ? value : value.toFixed(2)}`
  const digits = Math.min(6, Math.max(2, 1 - Math.floor(Math.log10(value))))
  // Two significant digits, but never fewer than two decimals: 0.014, 0.10, 0.25.
  return `$${value.toFixed(digits).replace(/(\.\d\d\d*?)0+$/, '$1')}`
}

// ── settings screen ─────────────────────────────────────────────────────────

/** Groups shown first; any other group follows in alphabetical order. */
export const SETTINGS_GROUP_ORDER = ['general', 'google', 'jobs']

export function settingsGroups(items) {
  const byGroup = new Map()
  for (const item of items || []) {
    const g = item.group || 'general'
    if (!byGroup.has(g)) byGroup.set(g, [])
    byGroup.get(g).push(item)
  }
  const rank = (g) => {
    const i = SETTINGS_GROUP_ORDER.indexOf(g)
    return i === -1 ? SETTINGS_GROUP_ORDER.length : i
  }
  return [...byGroup.keys()]
    .sort((a, b) => rank(a) - rank(b) || a.localeCompare(b))
    .map((group) => ({ group, items: byGroup.get(group) }))
}

/** Message keys of a setting: `settings.keys.<key>.label|help`, or the module's own ones from `meta`. */
export function settingMessageKeys(item) {
  const base = `settings.keys.${item.key}`
  return {
    label: [`${base}.label`, item.meta?.label_key].filter(Boolean),
    help: [`${base}.help`, item.meta?.help_key].filter(Boolean),
    choice: (value) => `${base}.choices.${value}`,
  }
}

export function sameSettingValue(a, b) {
  return JSON.stringify(a ?? null) === JSON.stringify(b ?? null)
}

/**
 * Check and convert what the user typed for a setting. Returns
 * `{ value }` or `{ error: 'number' | 'whole' | 'range' | 'json' }`.
 */
export function parseSettingInput(item, raw) {
  if (item.kind === 'int' || item.kind === 'float') {
    const text = String(raw ?? '').trim().replace(',', '.')
    const n = Number(text)
    if (!text || !Number.isFinite(n)) return { error: 'number' }
    if (item.kind === 'int' && !Number.isInteger(n)) return { error: 'whole' }
    if ((item.min !== null && item.min !== undefined && n < item.min)
      || (item.max !== null && item.max !== undefined && n > item.max)) return { error: 'range' }
    return { value: n }
  }
  if (item.kind === 'json' && typeof raw === 'string') {
    try {
      return { value: JSON.parse(raw) }
    } catch {
      return { error: 'json' }
    }
  }
  return { value: raw }
}

export const ASPECT_SIDE_MIN = 64
export const ASPECT_SIDE_MAX = 8192

/** `{"4:5": [1080, 1350]}` -> [{ aspect: '4:5', w: 1080, h: 1350 }] in the order of `defaults`. */
export function aspectSizeRows(value, defaults) {
  const v = value && typeof value === 'object' ? value : {}
  const d = defaults && typeof defaults === 'object' ? defaults : {}
  const keys = [...new Set([...Object.keys(d), ...Object.keys(v)])]
  return keys.map((aspect) => {
    const pair = Array.isArray(v[aspect]) ? v[aspect] : (Array.isArray(d[aspect]) ? d[aspect] : [null, null])
    return { aspect, w: pair[0], h: pair[1] }
  })
}

/** Rows back to the stored value; `null` when a side is not a whole number in range. */
export function aspectSizesValue(rows) {
  const out = {}
  for (const r of rows) {
    const w = Number(r.w)
    const h = Number(r.h)
    const ok = (n) => Number.isInteger(n) && n >= ASPECT_SIDE_MIN && n <= ASPECT_SIDE_MAX
    if (!ok(w) || !ok(h)) return null
    out[r.aspect] = [w, h]
  }
  return out
}
