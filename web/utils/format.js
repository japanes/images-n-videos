/** Money as shown on buttons and in the spend log: "$0.16", "<$0.01", "$12.40". */
export function formatUsd(value, { approx = false, digits } = {}) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—'
  const v = Number(value)
  const prefix = approx ? '≈' : ''
  if (v > 0 && v < 0.01) return `${prefix}<$0.01`
  const d = digits ?? (v >= 100 ? 0 : 2)
  return `${prefix}$${v.toFixed(d)}`
}

export function formatBytes(n) {
  const v = Number(n) || 0
  if (v < 1024) return `${v} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let x = v / 1024
  let i = 0
  while (x >= 1024 && i < units.length - 1) { x /= 1024; i++ }
  return `${x.toFixed(x >= 10 ? 0 : 1)} ${units[i]}`
}

/** 75 → "1:15", 3725 → "1:02:05" */
export function formatDuration(seconds) {
  const s = Math.max(0, Math.round(Number(seconds) || 0))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const r = String(s % 60).padStart(2, '0')
  return h ? `${h}:${String(m).padStart(2, '0')}:${r}` : `${m}:${r}`
}

/** Backend timestamps are UTC ISO strings ("2026-10-15T12:00:00Z" or without the Z). */
export function parseTs(ts) {
  if (!ts) return null
  const iso = /[zZ]|[+-]\d\d:?\d\d$/.test(ts) ? ts : `${ts}Z`
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? null : d
}

export function formatDateTime(ts, locale = 'en') {
  const d = parseTs(ts)
  if (!d) return '—'
  return d.toLocaleString(locale, { dateStyle: 'medium', timeStyle: 'short' })
}

export function formatDate(ts, locale = 'en') {
  const d = parseTs(ts)
  if (!d) return '—'
  return d.toLocaleDateString(locale, { dateStyle: 'medium' })
}
