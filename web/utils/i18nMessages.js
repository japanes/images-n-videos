/**
 * Merge `{ './locales/<code>/<file>.json': messages }` into
 * `{ <code>: { ...all files } }`. Each file already carries its namespace as
 * the top-level key; two files claiming the same namespace is a mistake and
 * throws, so it surfaces in tests instead of silently dropping strings.
 */
export function buildMessages(files) {
  const out = {}
  for (const [path, content] of Object.entries(files)) {
    const m = path.match(/locales\/([a-z]{2})\/([\w-]+)\.json$/)
    if (!m) continue
    const [, code, file] = m
    out[code] ||= {}
    for (const [ns, value] of Object.entries(content || {})) {
      if (ns in out[code]) throw new Error(`locale ${code}: namespace "${ns}" defined twice (${file}.json)`)
      out[code][ns] = value
    }
  }
  return out
}

/** Flat list of dotted keys of a messages object, for comparing locales. */
export function flatKeys(obj, prefix = '') {
  const keys = []
  for (const [k, v] of Object.entries(obj || {})) {
    const key = prefix ? `${prefix}.${k}` : k
    if (v && typeof v === 'object' && !Array.isArray(v)) keys.push(...flatKeys(v, key))
    else keys.push(key)
  }
  return keys.sort()
}
