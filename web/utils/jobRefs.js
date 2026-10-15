/**
 * What a background job belongs to, as seen from the jobs page.
 *
 * Jobs carry `ref_type` / `ref_id` (a frame, a video, a file…). Only the module
 * that owns that object knows where it lives in the interface, so each module
 * registers it from a client plugin of its own, e.g. web/plugins/media-jobrefs.js:
 *
 *   import { registerJobRef, registerJobKind } from '~/utils/jobRefs.js'
 *   export default defineNuxtPlugin(() => {
 *     registerJobRef('file', '/media?file=:id')                 // ':id' is replaced
 *     registerJobRef('video', (id, job) => ({ path: `/chat/${job.result_json?.chat_id}` }))
 *     registerJobKind('media.preview', 'media.jobs.preview')    // a key in the module's own locale
 *   })
 *
 * A resolver returns a route (string or route object) or null for "no link".
 * Nothing is guessed: a type nobody registered gets no link. The page also hides
 * links to routes that do not exist (yet).
 */

const refs = new Map()
const kinds = new Map()

/** Register where jobs of `refType` lead. Returns a function that removes it. */
export function registerJobRef(refType, resolver) {
  if (!refType || typeof refType !== 'string') throw new Error('registerJobRef: refType must be a string')
  if (typeof resolver !== 'string' && typeof resolver !== 'function') {
    throw new Error('registerJobRef: resolver must be a path pattern or a function')
  }
  refs.set(refType, resolver)
  return () => { if (refs.get(refType) === resolver) refs.delete(refType) }
}

export function unregisterJobRef(refType) {
  refs.delete(refType)
}

export function jobRefTypes() {
  return [...refs.keys()].sort()
}

/** The route a job's "Open" link points to, or null. */
export function jobRefRoute(job) {
  if (!job || !job.ref_type || job.ref_id === null || job.ref_id === undefined) return null
  const resolver = refs.get(job.ref_type)
  if (!resolver) return null
  if (typeof resolver === 'string') return resolver.replaceAll(':id', encodeURIComponent(String(job.ref_id)))
  try {
    return resolver(job.ref_id, job) || null
  } catch (err) {
    console.error(`job link for ${job.ref_type} failed`, err)
    return null
  }
}

/** A readable name for a job kind: a locale key from the owning module. */
export function registerJobKind(kind, labelKey) {
  if (!kind || !labelKey) throw new Error('registerJobKind: kind and labelKey are required')
  kinds.set(kind, labelKey)
  return () => { if (kinds.get(kind) === labelKey) kinds.delete(kind) }
}

export function unregisterJobKind(kind) {
  kinds.delete(kind)
}

/** Registered label for a kind, else the kind itself. */
export function jobKindLabel(kind, t) {
  const key = kinds.get(kind)
  if (key && t) {
    const text = t(key)
    if (text && text !== key) return text
  }
  return kind || ''
}
