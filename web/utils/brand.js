/**
 * Pure helpers of the brand screen (module 08): kinds, colors, ordering,
 * the describe-from-photos price request and error texts.
 */
import { apiErrorText } from './apiErrorText.js'

export const ELEMENT_KINDS = ['logo', 'frame', 'sticker', 'plate', 'badge', 'background', 'other']
export const SUBJECT_KINDS = ['product', 'person', 'prop']
export const FONT_CATEGORIES = ['sans', 'serif', 'mono', 'display', 'handwriting']
export const IMAGE_ACCEPT = 'image/png,image/jpeg,image/webp'
export const FONT_ACCEPT = '.ttf,.otf,font/ttf,font/otf,font/sfnt,application/font-sfnt'
export const MAX_COLORS = 16
export const DESCRIBE_PHOTOS = 3 // photos the describe call looks at (backend: describe.MAX_PHOTOS)

/** "#abc", "aabbcc", " #AaBbCc " -> "#AABBCC"; anything else -> null. */
export function normalizeHex(value) {
  const m = String(value ?? '').trim().match(/^#?([0-9a-f]{6}|[0-9a-f]{3})$/i)
  if (!m) return null
  let hex = m[1]
  if (hex.length === 3) hex = hex.split('').map((c) => c + c).join('')
  return `#${hex.toUpperCase()}`
}

/** Copy of `list` with the item at `from` moved to `to` (out of range -> unchanged copy). */
export function moveItem(list, from, to) {
  const out = [...(list || [])]
  if (from === to || from < 0 || to < 0 || from >= out.length || to >= out.length) return out
  const [item] = out.splice(from, 1)
  out.splice(to, 0, item)
  return out
}

const bySort = (a, b) => (a.sort ?? 0) - (b.sort ?? 0) || a.id - b.id

/** Assets of one kind in their saved order. */
export function assetsOfKind(assets, kind) {
  return (assets || []).filter((a) => a.kind === kind).sort(bySort)
}

/** { logo: 2, font: 1, … } */
export function countByKind(assets) {
  const out = {}
  for (const a of assets || []) out[a.kind] = (out[a.kind] || 0) + 1
  return out
}

/** Ids of a subject's photos after moving the one at `index` one place forward. */
export function photoIdsMovedForward(photos, index) {
  return moveItem(photos, index, index - 1).map((p) => p.id)
}

/** Price request for "Describe from photos", or null when there is nothing to describe. */
export function describeEstimate(photoCount) {
  const n = Math.min(DESCRIBE_PHOTOS, Number(photoCount) || 0)
  if (!n) return null
  return { kind: 'text', role: 'vision_describe', input_images: n, purpose: 'subject_describe' }
}

/** Error text: the screen's own `brand.errors.<code>` first, then the app-wide one. */
export function brandErrorText(err, t, te) {
  const key = `brand.errors.${err?.code || 'unknown'}`
  if (te ? te(key) : t(key) !== key) return t(key, { ...(err?.details || {}), message: err?.message || '' })
  return apiErrorText(err, t, te)
}
