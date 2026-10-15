/**
 * The one way the browser talks to the backend.
 *
 *   const api = useApi()
 *   const { items } = await api.get('/api/models', { kind: 'image' })
 *   await api.post('/api/jobs/3/cancel')
 *
 * Every failure becomes an ApiError with the backend's `{ code, message,
 * details }` and the HTTP status. Show it with `apiErrorText(err, t)`.
 */
export class ApiError extends Error {
  constructor({ code = 'network', message = '', details = {}, status = 0 } = {}) {
    super(message || code)
    this.name = 'ApiError'
    this.code = code
    this.details = details || {}
    this.status = status
  }
}

export function toApiError(err) {
  if (err instanceof ApiError) return err
  const status = err?.response?.status || err?.statusCode || 0
  const body = err?.data ?? err?.response?._data
  const e = body?.error
  if (e && typeof e === 'object') {
    return new ApiError({ code: e.code, message: e.message, details: e.details, status })
  }
  if (err?.name === 'AbortError') return new ApiError({ code: 'aborted', status })
  return new ApiError({ code: status ? `http_${status}` : 'network', message: err?.message || '', status })
}

export async function request(path, { method = 'GET', query, body, signal, headers } = {}) {
  try {
    return await $fetch(path, { method, query, body, signal, headers })
  } catch (err) {
    throw toApiError(err)
  }
}

export const useApi = () => ({
  request,
  get: (path, query, opts = {}) => request(path, { ...opts, query }),
  post: (path, body, opts = {}) => request(path, { ...opts, method: 'POST', body }),
  put: (path, body, opts = {}) => request(path, { ...opts, method: 'PUT', body }),
  patch: (path, body, opts = {}) => request(path, { ...opts, method: 'PATCH', body }),
  del: (path, query, opts = {}) => request(path, { ...opts, method: 'DELETE', query }),
  /** multipart upload; `fields` are extra form fields */
  upload: (path, file, fields = {}, opts = {}) => {
    const form = new FormData()
    form.append('file', file)
    for (const [k, v] of Object.entries(fields)) {
      if (v !== undefined && v !== null) form.append(k, typeof v === 'object' ? JSON.stringify(v) : String(v))
    }
    return request(path, { ...opts, method: 'POST', body: form })
  },
})
