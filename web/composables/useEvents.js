/**
 * Live updates from the backend over Server-Sent Events (`/api/events`).
 * One EventSource per tab, shared by everyone:
 *
 *   useEvents().on('job.updated', (job) => { … })        // auto-off on unmount
 *   useEvents().on('*', ({ type, data }) => { … })        // every event
 *   useEvents().on('reconnect', () => refetch())          // after a drop
 *
 * Events can be missed while the connection is down, so screens that care
 * re-fetch on 'reconnect'.
 */
import { getCurrentScope, onScopeDispose, ref } from 'vue'

const handlers = new Map()
const connected = ref(false)
let source = null
let everConnected = false

function emit(type, data) {
  for (const fn of handlers.get(type) || []) {
    try { fn(data) } catch (err) { console.error(`event handler for ${type} failed`, err) }
  }
}

export function dispatchEvent(raw) {
  let msg
  try { msg = JSON.parse(raw) } catch { return }
  if (!msg || typeof msg.type !== 'string') return
  emit(msg.type, msg.data || {})
  emit('*', msg)
}

function connect() {
  if (source || typeof EventSource === 'undefined') return
  source = new EventSource('/api/events')
  source.onopen = () => {
    connected.value = true
    if (everConnected) emit('reconnect', {})
    everConnected = true
  }
  source.onerror = () => { connected.value = false } // EventSource retries by itself
  source.onmessage = (e) => dispatchEvent(e.data)
}

export const useEvents = () => {
  connect()
  const on = (type, fn) => {
    if (!handlers.has(type)) handlers.set(type, new Set())
    handlers.get(type).add(fn)
    const off = () => handlers.get(type)?.delete(fn)
    if (getCurrentScope()) onScopeDispose(off)
    return off
  }
  return { on, connected }
}
