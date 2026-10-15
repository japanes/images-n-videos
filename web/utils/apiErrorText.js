/**
 * Human text for an ApiError. A localized `errors.<code>` wins; otherwise the
 * backend message (Google's own wording stays verbatim — that is the rule for
 * errors coming from Google); otherwise a generic line with the code.
 */
export function apiErrorText(err, t, te) {
  const code = err?.code || 'unknown'
  const key = `errors.${code}`
  const params = { ...(err?.details || {}), message: err?.message || '' }
  if (te ? te(key) : t(key) !== key) return t(key, params)
  if (err?.message && err.message !== code) return err.message
  return t('errors.generic', { code })
}
