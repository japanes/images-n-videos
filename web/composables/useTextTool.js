/**
 * The state of the «Text on a picture» tool (module 06) for one opening.
 *
 *   const tool = useTextTool({ frameId, fileId, chatId, messageId })
 *   await tool.open()
 *
 * Every change of the words or the layers is shown at once (the boxes) and kept
 * on the server as a draft after a short pause (PATCH); then the canvas picture
 * is drawn again by the server — the same drawing «Save» makes. Paid steps
 * first send what is still waiting, so the model sees what is on the screen.
 */
import { useDebounceFn } from '@vueuse/core'
import {
  TEXT_ESTIMATE_MS, TEXT_PREVIEW_SIDE, TEXT_SAVE_MS, textBackgroundsBody, textBindTexts, textDefaultLanguage,
  textEmptyForms, textErrorText, textEstimateQuery, textHumanizeBody, textLayoutTemplate, textParseReport,
  textPlaceBody, textVariantsBody, textWriteBody,
} from '~/utils/textView.js'

const BASE = '/api/text'

export function useTextTool({ frameId, fileId = null, chatId = null, messageId = null }) {
  const api = useApi()
  const { t, te, locale } = useI18n()
  const events = useEvents()

  const state = reactive({
    design: null,
    texts: [],
    layers: [],
    selectedId: '',
    loading: true,
    error: '', // the last failure, in words
    syncing: false, // a draft change is on its way
    preview: { url: '', report: null, loading: false, error: '' },
    layouts: [],
    est: null,
    estError: '',
    forms: textEmptyForms(textDefaultLanguage(locale.value)),
    busy: {},
    undo: null, // { what: 'write' | 'humanize', texts }
    variants: { blockId: '', items: [], errors: [] },
    placement: null,
    original: null, // the picture the tool was opened on, to go back to after a new background
  })

  const id = computed(() => state.design?.id || null)
  const fail = (err) => { state.error = textErrorText(err, t, te) }

  // ── the design as the server last answered ──

  function apply(view, { local = true } = {}) {
    if (!view) return
    state.design = view
    state.placement = view.placement || state.placement
    if (!state.original && view.background?.file_id) state.original = view.background.file_id
    if (local) {
      state.texts = JSON.parse(JSON.stringify(view.texts || []))
      state.layers = JSON.parse(JSON.stringify(view.layers || []))
      if (state.selectedId && !state.layers.some((l) => l.id === state.selectedId)) state.selectedId = ''
    }
    const lang = view.options?.language
    if (lang) state.forms.language = lang
  }

  async function open() {
    state.loading = true
    state.error = ''
    try {
      apply(await api.post(`${BASE}/designs/open`, {
        frame_id: frameId, file_id: fileId || undefined, chat_id: chatId || undefined, message_id: messageId || undefined,
      }))
      refreshPreview()
      loadLayouts()
    } catch (err) {
      fail(err)
    } finally {
      state.loading = false
    }
  }

  async function reload({ local = false } = {}) {
    if (!id.value) return
    try {
      apply(await api.get(`${BASE}/designs/${id.value}`), { local })
    } catch (err) {
      fail(err)
    }
  }

  // ── the canvas picture: drawn by the server, swapped when loaded ──

  let previewSeq = 0
  async function refreshPreview() {
    if (!id.value) return
    const mine = ++previewSeq
    state.preview.loading = true
    try {
      const res = await fetch(`${BASE}/designs/${id.value}/preview.png?max_side=${TEXT_PREVIEW_SIDE}`, { cache: 'no-store' })
      if (!res.ok) {
        let body = null
        try { body = await res.json() } catch { body = null }
        throw Object.assign(new Error(body?.error?.message || ''), { code: body?.error?.code || `http_${res.status}`, details: body?.error?.details || {} })
      }
      const report = textParseReport(res.headers.get('X-Render-Report'))
      const url = URL.createObjectURL(await res.blob())
      if (mine !== previewSeq) {
        URL.revokeObjectURL(url)
        return
      }
      await new Promise((resolve) => {
        const img = new Image()
        img.onload = resolve
        img.onerror = resolve
        img.src = url
      })
      if (mine !== previewSeq) {
        URL.revokeObjectURL(url)
        return
      }
      const old = state.preview.url
      state.preview.url = url
      state.preview.report = report
      state.preview.error = ''
      if (old) URL.revokeObjectURL(old)
    } catch (err) {
      if (mine === previewSeq) state.preview.error = textErrorText(err, t, te)
    } finally {
      if (mine === previewSeq) state.preview.loading = false
    }
  }

  // ── changes: shown now, kept as a draft after a pause ──

  let editSeq = 0
  let sentSeq = 0
  let sending = null
  const pushLater = useDebounceFn(() => push(), TEXT_SAVE_MS)

  function edit({ texts, layers } = {}) {
    if (texts) state.texts = texts
    if (layers) state.layers = layers
    state.layers = textBindTexts(state.layers, state.texts)
    editSeq += 1
    pushLater()
  }

  async function push() {
    if (!id.value) return
    if (sending) await sending.catch(() => null)
    if (sentSeq === editSeq) return
    const mine = editSeq
    sentSeq = mine
    state.syncing = true
    sending = (async () => {
      try {
        const view = await api.patch(`${BASE}/designs/${id.value}`, { texts: state.texts, layers: state.layers })
        apply(view, { local: mine === editSeq })
        refreshPreview()
      } catch (err) {
        sentSeq = -1 // try again with the next change or before a step
        fail(err)
        throw err
      } finally {
        state.syncing = false
      }
    })()
    return sending
  }

  /** Send what is waiting now (before a paid step, a layout, «Save»). */
  async function flush() {
    if (sending) await sending.catch(() => null)
    if (sentSeq !== editSeq) await push()
  }

  async function patchDesign(body) {
    if (!id.value) return
    try {
      await flush()
      apply(await api.patch(`${BASE}/designs/${id.value}`, body))
      refreshPreview()
    } catch (err) {
      fail(err)
    }
  }

  const setLanguage = (language) => {
    state.forms.language = language
    patchDesign({ options: { language } })
  }
  const setKit = (kitId) => patchDesign({ kit_id: kitId || null })
  /** The font new text layers get from «Place the text». */
  const setDefaultFont = (font) => patchDesign({ options: { font: font || null } })

  // ── layouts ──

  async function loadLayouts() {
    try {
      state.layouts = (await api.get(`${BASE}/layouts`))?.items || []
    } catch (err) {
      fail(err)
    }
  }

  async function applyLayout(layoutId) {
    await step('layout', async () => {
      await flush()
      apply(await api.post(`${BASE}/designs/${id.value}/layout`, { layout_id: layoutId }))
      refreshPreview()
    })
  }

  async function saveLayout(title) {
    return step('saveLayout', async () => {
      await api.post(`${BASE}/layouts`, { title, layers: textLayoutTemplate(state.layers) })
      await loadLayouts()
      return true
    })
  }

  async function deleteLayout(layoutId) {
    await step('deleteLayout', async () => {
      await api.del(`${BASE}/layouts/${layoutId}`)
      await loadLayouts()
    })
  }

  // ── paid steps ──

  async function step(name, fn) {
    if (state.busy[name]) return null
    state.busy = { ...state.busy, [name]: true }
    state.error = ''
    try {
      return await fn()
    } catch (err) {
      fail(err)
      return null
    } finally {
      const next = { ...state.busy }
      delete next[name]
      state.busy = next
    }
  }

  const place = () => step('place', async () => {
    await flush()
    const res = await api.post(`${BASE}/designs/${id.value}/place`, textPlaceBody(state.forms))
    apply(res.design)
    state.placement = res.placement
    refreshPreview()
  })

  const write = () => step('write', async () => {
    await flush()
    const res = await api.post(`${BASE}/designs/${id.value}/write`, textWriteBody(state.forms))
    state.undo = { what: 'write', texts: res.previous || [] }
    await reload({ local: true })
    refreshPreview()
  })

  const humanize = () => step('humanize', async () => {
    await flush()
    const res = await api.post(`${BASE}/designs/${id.value}/humanize`, textHumanizeBody(state.forms, state.texts))
    if (res.replaced) {
      state.undo = { what: 'humanize', texts: res.previous || [] }
      await reload({ local: true })
      refreshPreview()
    }
    return res
  })

  function undo() {
    if (!state.undo) return
    edit({ texts: JSON.parse(JSON.stringify(state.undo.texts)) })
    state.undo = null
  }

  const variants = (blockId) => step('variants', async () => {
    await flush()
    const res = await api.post(`${BASE}/designs/${id.value}/variants`, textVariantsBody(state.forms))
    state.variants = { blockId, items: res.variants || [], errors: res.errors || [] }
    reload()
  })

  const startBackgrounds = () => step('backgrounds', async () => {
    await flush()
    const res = await api.post(`${BASE}/designs/${id.value}/backgrounds`, textBackgroundsBody(state.forms))
    if (state.design) state.design = { ...state.design, backgrounds: res.backgrounds || [] }
  })

  const cancelBackgrounds = () => step('cancel', async () => {
    const res = await api.post(`${BASE}/designs/${id.value}/backgrounds/cancel`)
    if (state.design) state.design = { ...state.design, backgrounds: res.backgrounds || [] }
  })

  const useBackground = (backgroundId) => step(`use${backgroundId}`, async () => {
    await flush()
    apply(await api.post(`${BASE}/designs/${id.value}/backgrounds/${backgroundId}/use`))
    refreshPreview()
  })

  /** Back to the picture the tool was opened on. */
  const useOriginal = () => step('original', async () => {
    if (!state.original) return
    await flush()
    apply(await api.patch(`${BASE}/designs/${id.value}`, { background_file_id: state.original }))
    refreshPreview()
  })

  /** What a step would send to the model, without sending it: `{system, text}`. */
  async function promptPreview(name) {
    await flush()
    const bodies = {
      place: () => ['place', textPlaceBody(state.forms)],
      write: () => ['write', textWriteBody(state.forms)],
      variants: () => ['variants', textVariantsBody(state.forms)],
      humanize: () => ['humanize', textHumanizeBody(state.forms, state.texts)],
      backgrounds: () => ['backgrounds', textBackgroundsBody(state.forms)],
    }
    const [path, body] = bodies[name]()
    return api.post(`${BASE}/designs/${id.value}/${path}`, { ...body, preview: true })
  }

  // ── «Save»: the picture goes into the frame as a new version ──

  const save = () => step('save', async () => {
    await flush()
    return api.post(`${BASE}/designs/${id.value}/save`)
  })

  // ── prices ──

  let estSeq = 0
  const estimateKey = computed(() => JSON.stringify(textEstimateQuery(id.value, state.forms)))
  const fetchEstimate = useDebounceFn(async () => {
    const mine = ++estSeq
    try {
      const res = await api.get(`${BASE}/estimate`, textEstimateQuery(id.value, state.forms))
      if (mine === estSeq) {
        state.est = res
        state.estError = ''
      }
    } catch (err) {
      if (mine === estSeq) {
        state.est = null
        state.estError = textErrorText(err, t, te)
      }
    }
  }, TEXT_ESTIMATE_MS)
  watch(estimateKey, () => fetchEstimate(), { immediate: true })

  // ── live updates: backgrounds drawn in the background job ──

  events.on('text.updated', (data) => {
    if (data?.design_id && data.design_id === id.value && data.backgrounds) reload()
  })
  events.on('reconnect', () => reload())

  onScopeDispose(() => {
    previewSeq += 1
    if (state.preview.url) URL.revokeObjectURL(state.preview.url)
    if (sentSeq !== editSeq) push().catch(() => null) // the last change is not lost on close
  })

  return {
    state, id, open, reload, refreshPreview, edit, flush, setLanguage, setKit, setDefaultFont,
    loadLayouts, applyLayout, saveLayout, deleteLayout,
    place, write, humanize, undo, variants, startBackgrounds, cancelBackgrounds, useBackground, useOriginal, promptPreview, save,
  }
}
