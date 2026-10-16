/**
 * State of the image studio (module 04) for the chat (module 15) and the
 * studio components. Every export starts with `useStudio` because composables
 * are auto-imported.
 *
 *   const studio = useStudioWork(() => workId)   // one work and its frames
 *   await studio.load()
 *   await studio.generateAll()                    // -> { queued, skipped, work } or null
 *
 *   const list = useStudioWorks()                 // the gallery of works
 *   const price = useStudioEstimate(() => ({ action: 'frame', frame_id: 7 }))
 *
 * Actions toast their own errors and return null on failure, so a component
 * only has to check the result. Live updates come from `studio.updated`.
 */
import { useDebounceFn } from '@vueuse/core'
import { computed, ref, watch } from 'vue'
import { studioErrorText, studioEventMatches } from '~/utils/studioView.js'

const BASE = '/api/studio'

export const useStudioWork = (getId) => {
  const api = useApi()
  const toast = useToast()
  const { t, te } = useI18n()
  const { on } = useEvents()

  const work = ref(null)
  const loading = ref(false)
  const error = ref(null)
  const pending = ref({}) // { [key]: true } while an action runs
  let seq = 0

  const workId = computed(() => {
    const id = typeof getId === 'function' ? getId() : getId
    return id ? Number(id) : null
  })

  async function load() {
    const id = workId.value
    const mine = ++seq
    if (!id) { work.value = null; return null }
    loading.value = true
    try {
      const res = await api.get(`${BASE}/works/${id}`)
      if (mine === seq) { work.value = res; error.value = null }
      return res
    } catch (err) {
      if (mine === seq) error.value = err
      return null
    } finally {
      if (mine === seq) loading.value = false
    }
  }

  const reload = useDebounceFn(load, 200)
  on('studio.updated', (data) => { if (studioEventMatches(data, workId.value)) reload() })
  on('reconnect', () => { if (workId.value) reload() })
  watch(workId, () => load())

  /** Put a frame (as the API returns it) in place without a reload. */
  function setFrame(frame) {
    if (!frame?.id || !work.value) return
    const frames = work.value.frames || []
    if (!frames.some((f) => f.id === frame.id)) return
    work.value = { ...work.value, frames: frames.map((f) => (f.id === frame.id ? frame : f)) }
  }

  const isPending = (key) => Boolean(pending.value[key])

  async function act(key, fn, { quiet = false } = {}) {
    pending.value = { ...pending.value, [key]: true }
    try {
      return await fn()
    } catch (err) {
      if (!quiet) toast.error(studioErrorText(err, t, te))
      return null
    } finally {
      const next = { ...pending.value }
      delete next[key]
      pending.value = next
    }
  }

  const id = () => workId.value
  const takeWork = (res) => { if (res?.id) work.value = res; return res }
  const takeFrame = (res) => { setFrame(res?.frame || res); return res }
  const takeBatch = (res) => { if (res?.work) work.value = res.work; return res }

  return {
    work, loading, error, pending, isPending, load, reload, setFrame,

    // work
    patchWork: (body) => act('work', async () => takeWork(await api.patch(`${BASE}/works/${id()}`, body))),
    patchSettings: (settings) => act('work', async () => takeWork(await api.patch(`${BASE}/works/${id()}`, { settings }))),
    refreshBrand: () => act('brand', async () => takeWork(await api.post(`${BASE}/works/${id()}/refresh-brand`))),
    archive: () => act('archive', async () => takeWork(await api.post(`${BASE}/works/${id()}/archive`))),
    unarchive: () => act('archive', async () => takeWork(await api.post(`${BASE}/works/${id()}/unarchive`))),
    remove: () => act('remove', async () => { await api.del(`${BASE}/works/${id()}`); work.value = null; return true }),
    generateAll: () => act('all', async () => takeBatch(await api.post(`${BASE}/works/${id()}/generate`))),
    acceptPilot: () => act('pilot', async () => takeBatch(await api.post(`${BASE}/works/${id()}/accept-pilot`))),
    reorder: (ids) => act('order', async () => takeWork(await api.post(`${BASE}/works/${id()}/reorder`, { ids }))),
    addFrame: (after = null) => act('add', async () => {
      const frame = await api.post(`${BASE}/works/${id()}/frames`, after ? { after } : {})
      await load()
      return frame
    }),
    exportUrl: computed(() => (workId.value ? `${BASE}/works/${workId.value}/export` : '')),

    // frames
    patchFrame: (frameId, body) => act(`frame:${frameId}`, async () => takeFrame(await api.patch(`${BASE}/frames/${frameId}`, body))),
    deleteFrame: (frameId) => act(`frame:${frameId}`, async () => takeWork(await api.del(`${BASE}/frames/${frameId}`))),
    startFrame: (frameId) => act(`draw:${frameId}`, async () => takeFrame(await api.post(`${BASE}/frames/${frameId}/generate`))),
    editFrame: (frameId, edit, region) => act(`draw:${frameId}`, async () => (
      takeFrame(await api.post(`${BASE}/frames/${frameId}/edit`, { edit, region: region || null }))
    )),
    cancelFrame: (frameId) => act(`cancel:${frameId}`, async () => takeFrame(await api.post(`${BASE}/frames/${frameId}/cancel`))),
    findObjects: (frameId, focus = '') => act(`objects:${frameId}`, async () => (
      takeFrame(await api.post(`${BASE}/frames/${frameId}/find-objects`, { focus }))
    )),
    restoreVersion: (frameId, index) => act(`frame:${frameId}`, async () => (
      takeFrame(await api.post(`${BASE}/frames/${frameId}/versions/${index}/restore`))
    )),
    pickPicture: (frameId, fileId, source = 'library', sourceRef = null) => act(`frame:${frameId}`, async () => (
      takeFrame(await api.post(`${BASE}/frames/${frameId}/pick`, { file_id: fileId, source, source_ref: sourceRef }))
    )),
    uploadPicture: (frameId, file) => act(`frame:${frameId}`, async () => (
      takeFrame(await api.upload(`${BASE}/frames/${frameId}/source`, file))
    )),
  }
}

export const useStudioWorks = ({ pageSize = 24 } = {}) => {
  const api = useApi()
  const toast = useToast()
  const { t, te } = useI18n()
  const { on } = useEvents()

  const items = ref([])
  const total = ref(0)
  const loading = ref(false)
  const error = ref(null)
  const status = ref('active')
  const query = ref('')
  let seq = 0

  async function load({ more = false } = {}) {
    const mine = ++seq
    loading.value = true
    try {
      const res = await api.get(`${BASE}/works`, {
        status: status.value, q: query.value || undefined, limit: pageSize, offset: more ? items.value.length : 0,
      })
      if (mine !== seq) return
      items.value = more ? [...items.value, ...(res.items || [])] : (res.items || [])
      total.value = res.total || 0
      error.value = null
    } catch (err) {
      if (mine === seq) error.value = err
    } finally {
      if (mine === seq) loading.value = false
    }
  }

  const reload = useDebounceFn(() => load(), 300)
  on('studio.updated', reload)
  on('reconnect', reload)
  watch([status, query], () => reload())

  async function guarded(fn) {
    try {
      const res = await fn()
      await load()
      return res
    } catch (err) {
      toast.error(studioErrorText(err, t, te))
      return null
    }
  }

  return {
    items, total, loading, error, status, query, load,
    loadMore: () => load({ more: true }),
    hasMore: computed(() => items.value.length < total.value),
    create: (body = {}) => guarded(() => api.post(`${BASE}/works`, body)),
    rename: (id, title) => guarded(() => api.patch(`${BASE}/works/${id}`, { title })),
    archive: (id) => guarded(() => api.post(`${BASE}/works/${id}/archive`)),
    unarchive: (id) => guarded(() => api.post(`${BASE}/works/${id}/unarchive`)),
    remove: (id) => guarded(() => api.del(`${BASE}/works/${id}`)),
  }
}

/**
 * Price of a studio action (POST /api/studio/estimate). Pass a getter; null
 * means "nothing to price". Debounced; stale answers are dropped.
 * Returns { usd, items, data, loading, error }.
 */
export const useStudioEstimate = (getRequest, { debounce = 250 } = {}) => {
  const api = useApi()
  const usd = ref(null)
  const data = ref(null)
  const loading = ref(false)
  const error = ref(null)
  let timer = null
  let seq = 0

  const run = async (req) => {
    const mine = ++seq
    loading.value = true
    try {
      const res = await api.post(`${BASE}/estimate`, req)
      if (mine === seq) { data.value = res; usd.value = res?.usd ?? null; error.value = null }
    } catch (err) {
      if (mine === seq) { data.value = null; usd.value = null; error.value = err }
    } finally {
      if (mine === seq) loading.value = false
    }
  }

  watch(getRequest, (req) => {
    clearTimeout(timer)
    if (!req) { seq++; usd.value = null; data.value = null; loading.value = false; return }
    timer = setTimeout(() => run(req), debounce)
  }, { immediate: true, deep: true })

  const items = computed(() => data.value?.items || [])
  return { usd, items, data, loading, error }
}
