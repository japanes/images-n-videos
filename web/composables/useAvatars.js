/**
 * Avatars (module 09): one shared copy of each avatar for everything on the
 * screen — the card in the chat, the batch messages, the 36-slot grid.
 *
 *   const { view, loading, error, reload, put } = useAvatar(() => avatarId)
 *   const { est, usd, loading } = useAvatarEstimate(() => avatarId, () => ({ action: 'pack' }), () => view.value?.updated_at)
 *
 * The copy follows the 'avatars.updated' event (and re-reads after a lost
 * connection); answers of the actions that return the avatar are put in with
 * `put(view)` so the screen changes at once.
 */
import { computed, effectScope, getCurrentScope, onScopeDispose, reactive, ref, toValue, watch } from 'vue'
import { request } from './useApi.js'
import { AVATAR_ESTIMATE_MS, avatarsErrorText } from '~/utils/avatarsView.js'

const entries = new Map() // avatar id -> { state, users, timer, seq }
const EMPTY = reactive({ view: null, loading: false, error: null })
let listening = false

function entryFor(id) {
  let e = entries.get(id)
  if (!e) {
    e = { state: reactive({ view: null, loading: false, error: null }), users: 0, timer: null, seq: 0 }
    entries.set(id, e)
  }
  return e
}

async function load(id) {
  const e = entryFor(id)
  clearTimeout(e.timer)
  const mine = ++e.seq
  e.state.loading = true
  try {
    const view = await request(`/api/avatars/${id}`)
    if (mine === e.seq) { e.state.view = view; e.state.error = null }
  } catch (err) {
    if (mine === e.seq) e.state.error = err
  } finally {
    if (mine === e.seq) e.state.loading = false
  }
}

/** Re-read an avatar a moment later (several events in a row make one request). */
export function avatarReload(id, delay = 150) {
  const e = entries.get(Number(id))
  if (!e || e.users <= 0) return
  clearTimeout(e.timer)
  e.timer = setTimeout(() => load(Number(id)), delay)
}

/** An answer that carries the whole avatar replaces the shared copy. */
export function avatarPut(view) {
  if (!view?.id || !Array.isArray(view.slots)) return
  const e = entryFor(Number(view.id))
  e.seq += 1 // an older request still on its way must not overwrite this
  e.state.view = view
  e.state.error = null
  e.state.loading = false
}

function listen() {
  if (listening || typeof window === 'undefined') return
  listening = true
  // a scope of its own: the listener stays when the first screen that asked for it goes away
  effectScope(true).run(() => {
    const events = useEvents()
    events.on('avatars.updated', (data) => {
      if (data?.avatar_id) avatarReload(data.avatar_id)
    })
    events.on('reconnect', () => {
      for (const [id, e] of entries) if (e.users > 0) avatarReload(id, 0)
    })
  })
}

export function useAvatar(getId) {
  listen()
  const id = computed(() => {
    const n = Number(toValue(getId))
    return Number.isInteger(n) && n > 0 ? n : null
  })
  let current = null
  const release = () => {
    if (current && entries.has(current)) entries.get(current).users -= 1
    current = null
  }
  watch(id, (next) => {
    release()
    if (!next) return
    const e = entryFor(next)
    const wasIdle = e.users <= 0
    e.users += 1
    current = next
    // a copy nobody watched may have missed events: read it again
    if (!e.state.view || wasIdle) load(next)
  }, { immediate: true })
  if (getCurrentScope()) onScopeDispose(release)

  const state = computed(() => (id.value ? entryFor(id.value).state : EMPTY))
  return {
    view: computed(() => state.value.view),
    loading: computed(() => state.value.loading),
    error: computed(() => state.value.error),
    reload: () => (id.value ? load(id.value) : Promise.resolve()),
    put: avatarPut,
  }
}

/**
 * The price and the time before a button (POST /api/avatars/:id/estimate).
 * `getBody` returns the request or null (nothing to price); `getDeps` lists what
 * else changes the price (the avatar's updated_at, the chosen model…).
 */
export function useAvatarEstimate(getId, getBody, getDeps = () => null, { debounce = AVATAR_ESTIMATE_MS } = {}) {
  const est = ref(null)
  const loading = ref(false)
  const error = ref(null)
  let timer = null
  let seq = 0

  const run = async (id, body) => {
    const mine = ++seq
    try {
      const res = await request(`/api/avatars/${id}/estimate`, { method: 'POST', body })
      if (mine === seq) { est.value = res; error.value = null }
    } catch (err) {
      if (mine === seq) { est.value = null; error.value = err }
    } finally {
      if (mine === seq) loading.value = false
    }
  }

  watch(() => {
    const id = toValue(getId)
    const body = getBody()
    return id && body ? { id, body, deps: getDeps() } : null
  }, (req) => {
    clearTimeout(timer)
    if (!req) { seq++; est.value = null; error.value = null; loading.value = false; return }
    loading.value = true
    timer = setTimeout(() => run(req.id, req.body), debounce)
  }, { immediate: true, deep: true })
  if (getCurrentScope()) onScopeDispose(() => clearTimeout(timer))

  return { est, usd: computed(() => (est.value && est.value.count > 0 ? est.value.usd : null)), loading, error }
}

/**
 * One action at a time on a part of the screen, with the error shown as a toast:
 *
 *   const { busy, act } = useAvatarAction()
 *   await act('save', () => api.put(...))   // the answer, or null after an error
 */
export function useAvatarAction() {
  const busy = ref('')
  const toast = useToast()
  const { t, te } = useI18n()
  async function act(key, fn) {
    if (busy.value) return null
    busy.value = key
    try {
      const res = await fn()
      if (res && typeof res === 'object') avatarPut(res.avatar || res)
      return res ?? true
    } catch (err) {
      toast.error(avatarsErrorText(err, t, te))
      return null
    } finally {
      busy.value = ''
    }
  }
  return { busy, act }
}
