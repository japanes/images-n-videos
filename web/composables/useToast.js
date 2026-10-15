/**
 * Short notices in the corner: `toast.success(t('…'))`, `toast.error(text)`.
 * Errors stay until closed; the rest fade after a few seconds.
 */
import { ref } from 'vue'

const items = ref([])
let seq = 0

function push(kind, text, { timeout } = {}) {
  const id = ++seq
  items.value = [...items.value, { id, kind, text }]
  const ms = timeout ?? (kind === 'error' ? 0 : 4000)
  if (ms > 0) setTimeout(() => dismiss(id), ms)
  return id
}

function dismiss(id) {
  items.value = items.value.filter((i) => i.id !== id)
}

export const useToast = () => ({
  items,
  dismiss,
  info: (text, opts) => push('info', text, opts),
  success: (text, opts) => push('success', text, opts),
  error: (text, opts) => push('error', text, opts),
})
