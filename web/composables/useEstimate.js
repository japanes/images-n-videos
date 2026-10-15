/**
 * Price before the button: keeps `usd` in sync with a reactive estimate
 * request (see POST /api/estimate). Pass a getter; null means "nothing to
 * price". Requests are debounced and stale answers are dropped.
 *
 *   const { usd, loading } = useEstimate(() => ({ kind: 'image', model_id, count: 4 }))
 */
import { ref, watch } from 'vue'

export const useEstimate = (getRequest, { debounce = 250 } = {}) => {
  const api = useApi()
  const usd = ref(null)
  const loading = ref(false)
  const error = ref(null)
  let timer = null
  let seq = 0

  const run = async (req) => {
    const mine = ++seq
    loading.value = true
    try {
      const path = Array.isArray(req) ? '/api/estimate/batch' : '/api/estimate'
      const res = await api.post(path, req)
      if (mine === seq) { usd.value = res.usd; error.value = null }
    } catch (err) {
      if (mine === seq) { usd.value = null; error.value = err }
    } finally {
      if (mine === seq) loading.value = false
    }
  }

  watch(getRequest, (req) => {
    clearTimeout(timer)
    if (!req) { seq++; usd.value = null; loading.value = false; return }
    timer = setTimeout(() => run(req), debounce)
  }, { immediate: true, deep: true })

  return { usd, loading, error }
}
