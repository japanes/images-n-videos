/**
 * What one object (a work, a clip, an avatar…) has cost in Google calls so far,
 * from the spend journal. Live: re-reads when a call linked to it finishes.
 *
 *   const { cost } = useSpendCost(() => ['clip', clipId.value])
 *   // cost.value = { usd, calls, stub_usd, stub_calls, failed, running } | null
 *
 * Or just drop <SpendCost ref-type="clip" :ref-id="id" /> on the page.
 */
import { getCurrentScope, onScopeDispose, ref, watch } from 'vue'
import { spendDebounce, spendRefMatches } from '~/composables/useSpend.js'

export const useSpendCost = (getRef) => {
  const api = useApi()
  const cost = ref(null)
  const loading = ref(false)
  const error = ref(null)
  let seq = 0

  const current = () => {
    const pair = getRef() || []
    const [type, id] = pair
    return type && id !== null && id !== undefined && id !== '' ? [String(type), Number(id)] : null
  }

  const refresh = async () => {
    const pair = current()
    const mine = ++seq
    if (!pair) { cost.value = null; return }
    loading.value = true
    try {
      const res = await api.get('/api/spend/cost', { ref_type: pair[0], ref_id: pair[1] })
      if (mine === seq) { cost.value = res; error.value = null }
    } catch (err) {
      if (mine === seq) error.value = err
    } finally {
      if (mine === seq) loading.value = false
    }
  }

  const later = spendDebounce(refresh, 600)
  const { on } = useEvents()
  on('ai_call.finished', (e) => {
    const pair = current()
    if (pair && spendRefMatches(e?.refs, pair[0], pair[1])) later()
  })
  on('reconnect', () => later())
  if (getCurrentScope()) onScopeDispose(() => later.cancel())

  watch(() => current()?.join(':'), () => refresh(), { immediate: true })
  return { cost, loading, error, refresh }
}
