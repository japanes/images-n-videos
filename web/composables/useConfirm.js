/**
 * The app's single confirmation dialog, instead of `window.confirm()`:
 *
 *   const { confirm } = useConfirm()
 *   if (!await confirm({ message: t('jobs.cancelAsk', { title }), tone: 'danger' })) return
 *
 * Resolves true on confirm, false on cancel (button, overlay, Escape).
 * <ConfirmDialog /> in the default layout renders it.
 *
 * Module-level state (not useState): it is read after `await`s where the Nuxt
 * context is gone; the app is a SPA, so there is one module scope per tab.
 * Opening a second dialog cancels the first.
 *
 * opts: { title?, message, confirmLabel?, cancelLabel?, tone?: 'danger'|'default', hideCancel? }
 */
import { ref } from 'vue'

const state = ref({ open: false, opts: {}, resolve: null })

export const useConfirm = () => {
  const confirm = (opts = {}) => {
    if (state.value.open && state.value.resolve) state.value.resolve(false)
    const options = typeof opts === 'string' ? { message: opts } : (opts || {})
    return new Promise((resolve) => {
      state.value = { open: true, opts: options, resolve }
    })
  }
  const settle = (result) => {
    const r = state.value.resolve
    state.value = { open: false, opts: {}, resolve: null }
    if (r) r(result)
  }
  return { state, confirm, accept: () => settle(true), cancel: () => settle(false) }
}
