/**
 * Style library (module 07): pure helpers of the library screen and a thin API
 * wrapper the chat's style picker can reuse.
 *
 *   const lib = useLibrary()
 *   const { items, total } = await lib.styles({ tab: 'builtin', kind: 'style', q: 'neon' })
 *   const { item } = await lib.random({ exclude: lastId })      // the dice
 *   const { prompt } = await lib.render({ style_id: 42, values: { brand: 'SALT' } })   // free, no AI
 *
 * The slot grammar below mirrors app/vf/modules/library/variables.py; the
 * server stays the source of truth (it fills the text that goes to Google).
 */
import { apiErrorText } from '~/utils/apiErrorText.js'
import { useApi } from '~/composables/useApi.js'

export const LIBRARY_KINDS = ['style', 'photo_style']
export const LIBRARY_TABS = ['builtin', 'mine']
export const LIBRARY_PAGE_SIZE = 48
export const LIBRARY_PREVIEW_ACCEPT = 'image/png,image/jpeg,image/webp'
export const LIBRARY_LIMITS = { title: 200, description: 1000, prompt: 4000, variables: 20, value: 1000, extra: 1000, zones: 40000 }
// Backend error codes of this module; texts live in library.errors.<code>.
export const LIBRARY_ERROR_CODES = [
  'library_builtin_readonly', 'library_title_required', 'library_prompt_required', 'library_too_long',
  'library_too_many_variables', 'library_bad_kind', 'library_unknown_category', 'library_bad_image', 'empty_file',
  'text_zones_too_large', 'text_zones_invalid_json', 'text_zones_not_an_object',
]

const VARIABLE_RE = /\{\{\s*([^{}|]{1,60}?)\s*(?:\|\s*([^{}]{0,200}?)\s*)?\}\}/g
const VARIABLE_TYPES = {
  subject: 'subject',
  subject_appearance: 'text',
  subject_color: 'color',
  design_on_subject: 'text',
  secondary_subject: 'subject',
  additional_elements: 'subjects',
  action: 'text',
  clothing: 'subject',
  environment: 'subject',
  background_color: 'color',
  effect: 'text',
  brand: 'brand',
  text_on_subject: 'text',
}
// "Colour" words, whole words only (digits and "_" break words): accent_color yes, discolour no.
// The Cyrillic stems (ru "tsvet", uk "kolir"/"kolor", ru/uk "aktsent") are \u escapes: no Cyrillic outside the locales.
const COLOR_NAME = new RegExp(
  '(?:^|[^\\p{L}])(?:colou?rs?|hex|accents?|\\u0446\\u0432\\u0435\\u0442\\p{L}*|\\u043a\\u043e\\u043b\\u0456\\u0440'
  + '|\\u043a\\u043e\\u043b\\u044c\\u043e\\u0440\\p{L}*|\\u0430\\u043a\\u0446\\u0435\\u043d\\u0442\\p{L}*)(?:[^\\p{L}]|$)',
  'iu',
)

/** `{{Brand}}` and `{{brand}}` are one slot. */
export const libraryVariableKey = (name) => String(name ?? '').trim().toLowerCase()

/** subject | subjects | brand | color | text */
export function libraryVariableType(name) {
  const slot = libraryVariableKey(name).replace(/’/g, "'").replace(/[\s-]+/g, '_')
  if (slot in VARIABLE_TYPES) return VARIABLE_TYPES[slot]
  return COLOR_NAME.test(String(name ?? '')) ? 'color' : 'text'
}

/** The slots of a style text, first occurrence wins: [{ key, name, default, type }]. */
export function libraryVariables(prompt) {
  const out = []
  const seen = new Set()
  for (const m of String(prompt ?? '').matchAll(VARIABLE_RE)) {
    const name = (m[1] || '').trim()
    const key = libraryVariableKey(name)
    if (!key || seen.has(key)) continue
    seen.add(key)
    out.push({ key, name, default: (m[2] || '').trim(), type: libraryVariableType(name) })
    if (out.length >= LIBRARY_LIMITS.variables) break
  }
  return out
}

/** How many different slots a text has (the server refuses more than 20). */
export function librarySlotCount(prompt) {
  const keys = new Set()
  for (const m of String(prompt ?? '').matchAll(VARIABLE_RE)) {
    const key = libraryVariableKey(m[1])
    if (key) keys.add(key)
  }
  return keys.size
}

/** A category's name in the interface language; the shipped library has Russian names only. */
export function libraryCategoryTitle(cat, locale) {
  if (!cat) return ''
  return (locale && locale !== 'ru' && cat[`title_${locale}`]) || cat.title || cat.slug || ''
}

/** "a/b/c" -> ["a", "a/b"] : the categories to open so "a/b/c" is visible. */
export function libraryAncestors(slug) {
  const parts = String(slug || '').split('/').filter(Boolean)
  return parts.slice(0, -1).map((_, i) => parts.slice(0, i + 1).join('/'))
}

/** Flat categories (parent links) -> nested [{ ...cat, children }], in library order. */
export function libraryBuildTree(items) {
  const nodes = new Map((items || []).map((c) => [c.slug, { ...c, children: [] }]))
  const roots = []
  for (const node of nodes.values()) {
    const parent = node.parent && nodes.get(node.parent)
    if (parent) parent.children.push(node)
    else roots.push(node)
  }
  const order = (a, b) => (a.sort ?? 0) - (b.sort ?? 0) || String(a.slug).localeCompare(String(b.slug))
  const sortAll = (list) => { list.sort(order); list.forEach((n) => sortAll(n.children)); return list }
  return sortAll(roots)
}

/** The tree without categories that hold no style of the current filter. */
export function libraryPruneEmpty(nodes) {
  return (nodes || []).filter((n) => n.count > 0).map((n) => ({ ...n, children: libraryPruneEmpty(n.children) }))
}

/** Nodes in display order with their depth, skipping children of closed nodes. */
export function libraryVisibleRows(nodes, open, depth = 0, out = []) {
  for (const node of nodes || []) {
    out.push({ node, depth })
    if (node.children.length && open.has(node.slug)) libraryVisibleRows(node.children, open, depth + 1, out)
  }
  return out
}

/** Every category as one select option, indented by depth: [{ slug, label, depth }]. */
export function libraryCategoryOptions(nodes, locale, depth = 0, out = []) {
  for (const node of nodes || []) {
    out.push({ slug: node.slug, depth, label: `${'  '.repeat(depth)}${libraryCategoryTitle(node, locale)}` })
    libraryCategoryOptions(node.children, locale, depth + 1, out)
  }
  return out
}

/** Text zones as the editor shows them. */
export function libraryZonesText(zones) {
  return zones && typeof zones === 'object' ? JSON.stringify(zones, null, 2) : ''
}

/** Quick check before saving: null (fine or empty) or the error code the server would give. */
export function libraryCheckZones(text) {
  const raw = String(text ?? '').trim()
  if (!raw) return null
  if (raw.length > LIBRARY_LIMITS.zones) return 'text_zones_too_large'
  let value
  try { value = JSON.parse(raw) } catch { return 'text_zones_invalid_json' }
  if (!value || typeof value !== 'object' || Array.isArray(value)) return 'text_zones_not_an_object'
  if ('zones' in value && !Array.isArray(value.zones)) return 'text_zones_not_an_object'
  return null
}

/** Error text: this module's own wording first, then the shared one. */
export function libraryErrorText(err, t, te) {
  const key = `library.errors.${err?.code || 'unknown'}`
  if (te ? te(key) : t(key) !== key) return t(key, { ...(err?.details || {}), message: err?.message || '' })
  return apiErrorText(err, t, te)
}

const firstOf = (v) => String((Array.isArray(v) ? v[0] : v) ?? '')

/** Page filters from the address bar; unknown values fall back to the defaults. */
export function libraryFiltersFromQuery(query = {}) {
  const tab = firstOf(query.tab)
  const kind = firstOf(query.kind)
  return {
    tab: LIBRARY_TABS.includes(tab) ? tab : 'builtin',
    kind: LIBRARY_KINDS.includes(kind) ? kind : '',
    category: firstOf(query.cat).slice(0, 200),
    q: firstOf(query.q).trim().slice(0, 200),
  }
}

/** Page filters -> address bar, defaults left out. */
export function libraryFiltersToQuery(filters = {}) {
  const query = {}
  if (filters.tab && filters.tab !== 'builtin') query.tab = filters.tab
  if (filters.kind) query.kind = filters.kind
  if (filters.category) query.cat = filters.category
  if (filters.q) query.q = filters.q
  return query
}

/** Query for GET /api/library/styles without empty fields. */
export function libraryStylesQuery({ tab, kind, category, q, limit = LIBRARY_PAGE_SIZE, offset = 0 } = {}) {
  const query = { tab: tab || 'builtin', limit, offset }
  if (kind) query.kind = kind
  if (category) query.category = category
  if (q && String(q).trim()) query.q = String(q).trim()
  return query
}

export function useLibrary() {
  const api = useApi()
  return {
    categories: ({ tab, kind } = {}) => api.get('/api/library/categories', { tab: tab || 'builtin', ...(kind ? { kind } : {}) }),
    styles: (filters = {}) => api.get('/api/library/styles', libraryStylesQuery(filters)),
    style: (id) => api.get(`/api/library/styles/${id}`),
    random: ({ kind = 'style', tab = 'all', category, exclude } = {}) => api.get('/api/library/styles/random', {
      kind, tab, ...(category ? { category } : {}), ...(exclude ? { exclude } : {}),
    }),
    create: (body) => api.post('/api/library/styles', body),
    update: (id, body) => api.patch(`/api/library/styles/${id}`, body),
    remove: (id) => api.del(`/api/library/styles/${id}`),
    copy: (id, title) => api.post(`/api/library/styles/${id}/copy`, title ? { title } : {}),
    uploadPreview: (id, file) => api.upload(`/api/library/styles/${id}/preview`, file),
    previewFromFile: (id, fileId) => api.post(`/api/library/styles/${id}/preview/from-file`, { file_id: fileId }),
    removePreview: (id) => api.del(`/api/library/styles/${id}/preview`),
    render: (body) => api.post('/api/library/render', body),
  }
}
