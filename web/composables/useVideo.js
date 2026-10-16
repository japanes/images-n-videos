/**
 * State of the video module (11) for the chat (module 15) and the video
 * components. Every export starts with `useVideo` because composables are
 * auto-imported.
 *
 *   const video = useVideoRun(() => runId)       // one video, live via `video.updated`
 *   video.edit({ brief: '…' })                    // autosave after 600 ms of quiet
 *   await video.start()                           // the paid take (flushes the form first)
 *
 *   const catalog = useVideoCatalog()             // models and camera moves (loaded once)
 *   const list = useVideoRuns()                   // recent videos
 *   const price = useVideoPrice(() => req, (req) => api.post(…, req))
 *
 * Actions toast their own errors and return null on failure, so a component
 * only has to check the result.
 */
import { useDebounceFn } from '@vueuse/core'
import { computed, ref, watch } from 'vue'
import { VIDEO_AUTOSAVE_MS, videoErrorText, videoEventMatches, videoStepsBody } from '~/utils/videoView.js'

const BASE = '/api/video'

// Scalar fields shown in the form straight away while they wait to be saved.
const LOCAL_FIELDS = ['title', 'niche', 'platform', 'brief', 'model_id', 'duration', 'resolution', 'aspect',
  'camera_move', 'sound']

export const useVideoRun = (getId) => {
  const api = useApi()
  const toast = useToast()
  const { t, te } = useI18n()
  const { on } = useEvents()

  const run = ref(null)
  const loading = ref(false)
  const error = ref(null)
  const deleted = ref(false)
  const pending = ref({}) // { [key]: true } while an action runs
  const draft = ref({}) // fields typed but not saved yet
  const saving = ref(false)
  let seq = 0

  const runId = computed(() => {
    const id = typeof getId === 'function' ? getId() : getId
    return id ? Number(id) : null
  })

  /** Take a fresh view, but keep what the person typed and has not saved yet. */
  function take(view) {
    if (!view?.id) return view
    if (view.id !== runId.value) return view
    const keep = Object.fromEntries(Object.entries(draft.value).filter(([k]) => LOCAL_FIELDS.includes(k)))
    run.value = { ...view, ...keep }
    deleted.value = false
    return view
  }

  async function load() {
    const id = runId.value
    const mine = ++seq
    if (!id) { run.value = null; return null }
    loading.value = true
    try {
      const res = await api.get(`${BASE}/runs/${id}`)
      if (mine === seq) { take(res); error.value = null }
      return res
    } catch (err) {
      if (mine === seq) error.value = err
      return null
    } finally {
      if (mine === seq) loading.value = false
    }
  }

  const reload = useDebounceFn(load, 200)
  on('video.updated', (data) => { if (videoEventMatches(data, runId.value)) take(data) })
  on('video.deleted', (data) => {
    if (videoEventMatches(data, runId.value)) { run.value = null; deleted.value = true }
  })
  on('reconnect', () => { if (runId.value) reload() })
  watch(runId, () => { draft.value = {}; load() })

  const isPending = (key) => Boolean(pending.value[key])

  async function act(key, fn, { quiet = false } = {}) {
    pending.value = { ...pending.value, [key]: true }
    try {
      return await fn()
    } catch (err) {
      if (!quiet) toast.error(videoErrorText(err, t, te))
      return null
    } finally {
      const next = { ...pending.value }
      delete next[key]
      pending.value = next
    }
  }

  // ── autosave ──────────────────────────────────────────────────────────────

  async function flush() {
    const id = runId.value
    const body = draft.value
    if (!id || !Object.keys(body).length) return run.value
    draft.value = {}
    saving.value = true
    try {
      return take(await api.patch(`${BASE}/runs/${id}`, body))
    } catch (err) {
      toast.error(videoErrorText(err, t, te))
      await load()
      return null
    } finally {
      saving.value = false
    }
  }

  const saveSoon = useDebounceFn(flush, VIDEO_AUTOSAVE_MS)

  /** Change form fields: shown at once, saved after a short quiet (or now with `{ now: true }`). */
  function edit(fields, { now = false } = {}) {
    if (!fields || !run.value) return null
    draft.value = { ...draft.value, ...fields }
    const local = Object.fromEntries(Object.entries(fields).filter(([k]) => LOCAL_FIELDS.includes(k)))
    if (Object.keys(local).length) run.value = { ...run.value, ...local }
    return now ? flush() : saveSoon()
  }

  const isDirty = (field) => field in draft.value
  const id = () => runId.value
  const path = (tail = '') => `${BASE}/runs/${id()}${tail}`
  const post = (tail, body) => api.post(path(tail), body)

  /** Save the form, then run a paid action: the price shown was for what is on screen. */
  const afterSave = (key, fn, opts) => act(key, async () => { await flush(); return fn() }, opts)

  return {
    run, loading, error, deleted, pending, saving, draft, isPending, isDirty, load, reload, edit, flush, take,

    // the take
    start: () => afterSave('start', async () => take(await post('/start'))),
    stop: () => act('stop', async () => take(await post('/stop'))),
    chooseVersion: (number) => act('version', async () => take(await post(`/versions/${number}/choose`))),
    undo: () => act('undo', async () => take(await post('/undo'))),
    takeFrame: (at = 'last', version = null) => act('frame', () => post('/frame', version ? { at, version } : { at })),
    remove: () => act('remove', async () => { await api.del(path()); run.value = null; deleted.value = true; return true }),

    // extension piece by piece, and «continue from the last frame»
    extendInfo: (modelId = null) => act('extendInfo', () => api.get(path('/extend'), { model_id: modelId || undefined }), { quiet: true }),
    extendEstimate: (steps, modelId = null) => act('extendEstimate', () => (
      post('/extend/estimate', { steps: videoStepsBody(steps), model_id: modelId || undefined })
    ), { quiet: true }),
    extend: (steps, { modelId = null, pauseEach = true } = {}) => afterSave('extend', async () => take(await post('/extend', {
      steps: videoStepsBody(steps), model_id: modelId || undefined, pause_each: Boolean(pauseEach),
    }))),
    continuePlan: (steps = null) => act('extend', async () => (
      take(await post('/extend/continue', steps ? { steps: videoStepsBody(steps) } : {}))
    )),
    dropPlan: () => act('drop', async () => take(await post('/extend/drop'))),
    continueEstimate: (seconds, modelId = null) => act('continueEstimate', () => (
      post('/continue/estimate', { seconds, model_id: modelId || undefined })
    ), { quiet: true }),
    continueFromLast: (text, seconds, modelId = null) => afterSave('continue', async () => take(await post('/continue', {
      text: String(text || '').trim(), seconds, model_id: modelId || undefined,
    }))),

    // «Write it for me»
    briefEstimate: (research = true) => act('briefEstimate', () => api.get(path('/brief/estimate'), { research }), { quiet: true }),
    writeBrief: ({ research = true, force = false } = {}) => afterSave('brief', async () => {
      const res = await post('/brief/write', { research, force })
      take(res?.run)
      return res?.result || null
    }),
    restoreBrief: () => act('brief', async () => take(await post('/brief/restore'))),
    applyCamera: () => act('camera', async () => take(await post('/brief/camera'))),

    // storyboard sheet
    storyboardPreview: (body = {}) => act('storyboardPreview', () => post('/storyboard/preview', body), { quiet: true }),
    makeStoryboard: (body = {}) => afterSave('storyboard', async () => take(await post('/storyboard', body))),
    pickStoryboard: (fileId) => act('storyboard', async () => take(await post('/storyboard/pick', { file_id: fileId }))),
    attachStoryboard: (attached) => act('storyboard', async () => take(await post('/storyboard/attach', { attached }))),
    clearStoryboard: () => act('storyboard', async () => take(await api.del(path('/storyboard')))),
  }
}

// Models and camera moves change rarely: one copy for the whole tab.
const catalog = {
  models: ref([]), extensionModels: ref([]), moves: ref([]), categories: ref([]),
  loading: ref(false), error: ref(null), loaded: false, promise: null,
}

export const useVideoCatalog = () => {
  const api = useApi()
  const { on } = useEvents()

  async function load({ force = false } = {}) {
    if (catalog.promise && !force) return catalog.promise
    catalog.loading.value = true
    catalog.promise = (async () => {
      try {
        const [models, moves] = await Promise.all([api.get(`${BASE}/models`), api.get(`${BASE}/camera-moves`)])
        catalog.models.value = models?.models || []
        catalog.extensionModels.value = models?.extension_models || []
        catalog.moves.value = moves?.moves || []
        catalog.categories.value = moves?.categories || []
        catalog.error.value = null
        catalog.loaded = true
      } catch (err) {
        catalog.error.value = err
        catalog.promise = null
      } finally {
        catalog.loading.value = false
      }
    })()
    return catalog.promise
  }

  on('models.changed', () => load({ force: true }))
  if (!catalog.loaded) load()

  return {
    models: catalog.models, extensionModels: catalog.extensionModels, moves: catalog.moves,
    categories: catalog.categories, loading: catalog.loading, error: catalog.error, load,
  }
}

/** Recent videos (GET /api/video/runs), kept fresh by events. */
export const useVideoRuns = ({ limit = 50 } = {}) => {
  const api = useApi()
  const toast = useToast()
  const { t, te } = useI18n()
  const { on } = useEvents()

  const items = ref([])
  const loading = ref(false)
  const error = ref(null)
  let seq = 0

  async function load() {
    const mine = ++seq
    loading.value = true
    try {
      const res = await api.get(`${BASE}/runs`, { limit })
      if (mine === seq) { items.value = res?.items || []; error.value = null }
    } catch (err) {
      if (mine === seq) error.value = err
    } finally {
      if (mine === seq) loading.value = false
    }
  }

  const reload = useDebounceFn(load, 300)
  on('video.updated', reload)
  on('video.deleted', reload)
  on('reconnect', reload)

  async function create(body = {}) {
    try {
      const run = await api.post(`${BASE}/runs`, body)
      reload()
      return run
    } catch (err) {
      toast.error(videoErrorText(err, t, te))
      return null
    }
  }

  return { items, loading, error, load, create }
}

/**
 * A price (or any "what would happen") answer kept in sync with a request.
 * `getRequest` returns the request or null ("nothing to ask"); `ask(req)` calls
 * the API. Debounced; stale answers are dropped. Returns { data, loading, error }.
 */
export const useVideoPrice = (getRequest, ask, { debounce = 300 } = {}) => {
  const data = ref(null)
  const loading = ref(false)
  const error = ref(null)
  let timer = null
  let seq = 0

  const run = async (req) => {
    const mine = ++seq
    loading.value = true
    try {
      const res = await ask(req)
      if (mine === seq) { data.value = res ?? null; error.value = res ? null : error.value }
    } catch (err) {
      if (mine === seq) { data.value = null; error.value = err }
    } finally {
      if (mine === seq) loading.value = false
    }
  }

  watch(getRequest, (req) => {
    clearTimeout(timer)
    if (!req) { seq++; data.value = null; loading.value = false; return }
    timer = setTimeout(() => run(req), debounce)
  }, { immediate: true, deep: true })

  return { data, loading, error, refresh: () => { const req = getRequest(); if (req) run(req) } }
}
