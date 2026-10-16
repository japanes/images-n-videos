/**
 * State of the chat (module 15). Every export starts with `useChat` because
 * composables are auto-imported.
 *
 *   const list = useChatList()                 // the chats in the left menu
 *   const room = useChatRoom(() => chatId)     // one chat: messages, draft, sending
 *
 * The backend does not push the progress of pictures and videos into the chat:
 * the room listens to the job, studio and video events itself and re-reads the
 * messages they concern (GET /messages/{id} brings a message up to date).
 * Actions toast their own errors and return null on failure.
 */
import { useDebounceFn } from '@vueuse/core'
import { computed, onScopeDispose, ref, watch } from 'vue'
import {
  CHAT_DRAFT_SAVE_MS, CHAT_LIST_SIZE, CHAT_PAGE_SIZE, chatApplyProgress, chatAttachmentsBody, chatErrorText,
  chatEventTouches, chatMergeMessages, chatRolesForMode,
} from '~/utils/chatView.js'

const BASE = '/api/chat'
const LIVE_EVENTS = ['job.updated', 'studio.updated', 'video.updated', 'video.deleted']

/** The chats of the left menu: recent first, search, archive. */
export const useChatList = ({ limit = CHAT_LIST_SIZE } = {}) => {
  const api = useApi()
  const toast = useToast()
  const { t, te } = useI18n()
  const { on } = useEvents()

  const items = ref([])
  const total = ref(0)
  const loading = ref(false)
  const error = ref(null)
  const q = ref('')
  const archived = ref(false)
  let seq = 0

  async function load({ append = false } = {}) {
    const mine = ++seq
    loading.value = true
    try {
      const res = await api.get(`${BASE}/chats`, {
        q: q.value.trim() || undefined, archived: archived.value || undefined, limit,
        offset: append ? items.value.length : 0,
      })
      if (mine !== seq) return
      items.value = append ? [...items.value, ...(res?.items || [])] : res?.items || []
      total.value = res?.total || 0
      error.value = null
    } catch (err) {
      if (mine === seq) error.value = err
    } finally {
      if (mine === seq) loading.value = false
    }
  }

  const reload = useDebounceFn(() => load(), 400)
  on('chat.updated', reload)
  on('reconnect', reload)
  watch([q, archived], reload)

  const more = computed(() => items.value.length < total.value)

  async function create(body = {}) {
    try {
      const chat = await api.post(`${BASE}/chats`, body)
      reload()
      return chat
    } catch (err) {
      toast.error(chatErrorText(err, t, te))
      return null
    }
  }

  async function rename(id, title) {
    try {
      const chat = await api.patch(`${BASE}/chats/${id}`, { title })
      items.value = items.value.map((c) => (c.id === id ? { ...c, title: chat.title } : c))
      return chat
    } catch (err) {
      toast.error(chatErrorText(err, t, te))
      return null
    }
  }

  async function archive(id, value = true) {
    try {
      const chat = await api.post(`${BASE}/chats/${id}/archive`, { archived: value })
      items.value = items.value.filter((c) => c.id !== id)
      total.value = Math.max(0, total.value - 1)
      return chat
    } catch (err) {
      toast.error(chatErrorText(err, t, te))
      return null
    }
  }

  return { items, total, loading, error, q, archived, more, load, reload, create, rename, archive }
}

/** The newest chat, or a new one when there is none: where `/chat` and «New chat» lead. */
export const useChatStart = () => {
  const api = useApi()
  const toast = useToast()
  const { t, te } = useI18n()

  /** `onlyEmpty`: take the newest chat only when nothing was sent in it yet («New chat»). */
  async function open({ onlyEmpty = false } = {}) {
    try {
      const res = await api.get(`${BASE}/chats`, { limit: 1 })
      const last = res?.items?.[0]
      if (last && (!onlyEmpty || !last.last_message_at)) return last
      return await api.post(`${BASE}/chats`, {})
    } catch (err) {
      toast.error(chatErrorText(err, t, te))
      return null
    }
  }

  return { open }
}

const emptyDraft = () => ({
  text: '', attachments: [], reply_to: null, reply_index: 0, reply: null, enhance: false,
  region: null, extend_seconds: null,
})

/** What PATCH /chats/{id} takes as `draft` (the region and the length stay in the tab). */
function draftBody(d) {
  return {
    text: d.text || '', attachments: chatAttachmentsBody(d.attachments), reply_to: d.reply_to || null,
    reply_index: Number(d.reply_index || 0), enhance: Boolean(d.enhance),
  }
}

/** One chat: its settings, the feed, the composer draft and every action of the feed. */
export const useChatRoom = (getId) => {
  const api = useApi()
  const toast = useToast()
  const { t, te } = useI18n()
  const { on } = useEvents()

  const chat = ref(null)
  const messages = ref([])
  const more = ref(false)
  const loading = ref(false)
  const error = ref(null)
  const pending = ref({})
  const draft = ref(emptyDraft())
  let seq = 0

  const chatId = computed(() => {
    const id = typeof getId === 'function' ? getId() : getId
    return id ? Number(id) : null
  })
  const mode = computed(() => (chat.value?.mode === 'video' ? 'video' : 'image'))
  const isPending = (key) => Boolean(pending.value[key])

  async function act(key, fn, { quiet = false } = {}) {
    pending.value = { ...pending.value, [key]: true }
    try {
      return await fn()
    } catch (err) {
      if (!quiet) toast.error(chatErrorText(err, t, te))
      return null
    } finally {
      const next = { ...pending.value }
      delete next[key]
      pending.value = next
    }
  }

  // ── the draft: shown at once, saved after a short pause, never lost on a switch ──

  let draftSave = null // { id, body } waiting to be sent
  let draftTimer = null

  async function flushDraft() {
    clearTimeout(draftTimer)
    const job = draftSave
    draftSave = null
    if (!job) return
    try {
      await api.patch(`${BASE}/chats/${job.id}`, { draft: job.body })
    } catch (err) {
      toast.error(chatErrorText(err, t, te))
    }
  }

  function editDraft(fields) {
    draft.value = { ...draft.value, ...fields }
    if (!chatId.value) return
    draftSave = { id: chatId.value, body: draftBody(draft.value) }
    clearTimeout(draftTimer)
    draftTimer = setTimeout(flushDraft, CHAT_DRAFT_SAVE_MS)
  }

  function dropDraftSave() {
    clearTimeout(draftTimer)
    draftSave = null
  }

  function takeDraft(view) {
    const d = view?.draft || {}
    draft.value = {
      ...emptyDraft(),
      text: d.text || '',
      attachments: (d.attachments || []).map((a) => ({ file_id: a.file_id, role: a.role, file: a.file })),
      reply_to: d.reply_to || null, reply_index: d.reply_index || 0, reply: d.reply || null,
      enhance: Boolean(d.enhance),
    }
  }

  // ── loading ──

  async function loadChat() {
    const id = chatId.value
    if (!id) return null
    try {
      const view = await api.get(`${BASE}/chats/${id}`)
      if (id === chatId.value) chat.value = view
      return view
    } catch (err) {
      if (id === chatId.value) error.value = err
      return null
    }
  }

  async function load() {
    const id = chatId.value
    const mine = ++seq
    chat.value = null
    messages.value = []
    more.value = false
    error.value = null
    draft.value = emptyDraft()
    if (!id) return
    loading.value = true
    try {
      const [view, page] = await Promise.all([
        api.get(`${BASE}/chats/${id}`),
        api.get(`${BASE}/chats/${id}/messages`, { limit: CHAT_PAGE_SIZE }),
      ])
      if (mine !== seq) return
      chat.value = view
      takeDraft(view)
      messages.value = page?.items || []
      more.value = Boolean(page?.more)
    } catch (err) {
      if (mine === seq) error.value = err
    } finally {
      if (mine === seq) loading.value = false
    }
  }

  async function loadOlder() {
    const id = chatId.value
    const first = messages.value[0]
    if (!id || !first || !more.value || pending.value.older) return false
    return act('older', async () => {
      const page = await api.get(`${BASE}/chats/${id}/messages`, { before: first.position, limit: CHAT_PAGE_SIZE })
      if (id !== chatId.value) return false
      messages.value = chatMergeMessages(messages.value, page?.items || [])
      more.value = Boolean(page?.more)
      return true
    }, { quiet: true })
  }

  /** Load older pages until a message is in the feed (a `?message=` link). */
  async function loadUntil(messageId, maxPages = 20) {
    for (let i = 0; i < maxPages; i++) {
      if (messages.value.some((m) => m.id === messageId)) return true
      if (!more.value || !(await loadOlder())) return false
    }
    return messages.value.some((m) => m.id === messageId)
  }

  /** Re-read the newest page after a drop of the live connection. */
  async function refreshLatest() {
    const id = chatId.value
    if (!id) return
    try {
      const page = await api.get(`${BASE}/chats/${id}/messages`, { limit: CHAT_PAGE_SIZE })
      if (id === chatId.value) messages.value = chatMergeMessages(messages.value, page?.items || [])
    } catch { /* the next event or reload brings it */ }
  }

  function put(message) {
    if (message?.id && message.chat_id === chatId.value) messages.value = chatMergeMessages(messages.value, [message])
    return message
  }

  async function refreshMessage(messageId) {
    try {
      return put(await api.get(`${BASE}/messages/${messageId}`))
    } catch (err) {
      if (err?.status === 404) messages.value = messages.value.filter((m) => m.id !== messageId)
      return null
    }
  }

  // ── live updates ──

  const timers = new Map()
  function refreshSoon(messageId, wait = 300) {
    clearTimeout(timers.get(messageId))
    timers.set(messageId, setTimeout(() => { timers.delete(messageId); refreshMessage(messageId) }, wait))
  }

  const reloadChat = useDebounceFn(loadChat, 300)

  on('chat.updated', (data) => {
    if (!chatId.value || Number(data?.chat_id) !== chatId.value) return
    if (data.what === 'message' && data.message_id) refreshSoon(Number(data.message_id), 100)
    else reloadChat()
  })
  on('job.progress', (data) => {
    messages.value = messages.value.map((m) => (chatEventTouches(m, 'job.progress', data) ? chatApplyProgress(m, data) : m))
  })
  for (const type of LIVE_EVENTS) {
    on(type, (data) => {
      for (const m of messages.value) if (chatEventTouches(m, type, data)) refreshSoon(m.id)
    })
  }
  on('reconnect', () => { if (chatId.value) { reloadChat(); refreshLatest() } })

  watch(chatId, async () => {
    await flushDraft()
    for (const timer of timers.values()) clearTimeout(timer)
    timers.clear()
    load()
  }, { immediate: true })

  onScopeDispose(() => {
    for (const timer of timers.values()) clearTimeout(timer)
    timers.clear()
    flushDraft()
  })

  // ── settings of the chat ──

  async function patch(body) {
    const id = chatId.value
    if (!id) return null
    return act('settings', async () => {
      const view = await api.patch(`${BASE}/chats/${id}`, body)
      if (id === chatId.value) chat.value = { ...view, draft: chat.value?.draft || view.draft }
      return view
    })
  }

  const patchImage = (fields) => patch({ image_settings: fields })
  const patchVideo = (fields) => patch({ video_settings: fields })

  /** Switch image ↔ video; attached pictures get roles the new mode knows. */
  function setMode(next) {
    if (!chat.value || next === mode.value) return null
    chat.value = { ...chat.value, mode: next }
    const limits = chat.value.limits
    editDraft({ attachments: chatRolesForMode(draft.value.attachments, next, limits), extend_seconds: null })
    return patch({ mode: next })
  }

  // ── sending and the actions of the feed ──

  const estimateUrl = (id) => `${BASE}/chats/${id}/estimate`
  const askEstimate = (body) => api.post(estimateUrl(chatId.value), body)

  async function send(body) {
    const id = chatId.value
    if (!id) return null
    return act('send', async () => {
      const res = await api.post(`${BASE}/chats/${id}/send`, body)
      dropDraftSave()
      if (id === chatId.value) {
        draft.value = { ...emptyDraft(), enhance: draft.value.enhance }
        put(res?.request)
        put(res?.result)
      }
      return res
    })
  }

  const repeatEstimate = (messageId, original = false) => (
    act(`repeatEstimate:${messageId}`, () => api.get(`${BASE}/messages/${messageId}/repeat-estimate`, { original }),
      { quiet: true })
  )

  const repeat = (messageId, original = false) => act(`repeat:${messageId}`, async () => {
    const res = await api.post(`${BASE}/messages/${messageId}/repeat`, { original })
    put(res?.request)
    put(res?.result)
    return res
  })

  const pilotEstimate = (messageId) => (
    act(`pilotEstimate:${messageId}`, () => api.get(`${BASE}/messages/${messageId}/accept-pilot/estimate`), { quiet: true })
  )
  const acceptPilot = (messageId) => act(`pilot:${messageId}`, async () => put(await api.post(`${BASE}/messages/${messageId}/accept-pilot`)))
  const cancel = (messageId) => act(`cancel:${messageId}`, async () => put(await api.post(`${BASE}/messages/${messageId}/cancel`)))
  const takeFrame = (messageId, index = 0, at = 'last') => act(`frame:${messageId}`, async () => (
    put(await api.post(`${BASE}/messages/${messageId}/take-frame`, { index, at }))
  ))

  /** After the frame viewer closes: what changed there is posted as a new picture. */
  const fromViewer = (frameId, replyTo = null) => act(`viewer:${frameId}`, async () => {
    const res = await api.post(`${BASE}/chats/${chatId.value}/from-viewer`, { frame_id: frameId, reply_to: replyTo })
    return put(res?.message)
  })

  /** The draft video behind «Write it for me» (free): { run_id, run }. */
  const videoDraft = () => act('videoDraft', async () => {
    await flushDraft()
    return api.post(`${BASE}/chats/${chatId.value}/video-draft`, {
      text: draft.value.text || '', attachments: chatAttachmentsBody(draft.value.attachments),
    })
  })

  const pictures = (limit = 60) => act('pictures', async () => (await api.get(`${BASE}/chats/${chatId.value}/pictures`, { limit }))?.items || [], { quiet: true })

  return {
    chat, chatId, mode, messages, more, loading, error, pending, draft, isPending,
    load, loadChat, loadOlder, loadUntil, refreshMessage, put,
    editDraft, flushDraft, patch, patchImage, patchVideo, setMode,
    askEstimate, send, repeatEstimate, repeat, pilotEstimate, acceptPilot, cancel, takeFrame, fromViewer, videoDraft,
    pictures,
  }
}
