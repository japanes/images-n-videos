<template>
  <div class="page space-y-4">
    <header class="flex flex-wrap items-start gap-3">
      <div class="min-w-0 flex-1">
        <h1 class="page-title">{{ t('media.title') }}</h1>
        <p class="mt-1 text-sm muted">{{ t('media.subtitle') }}</p>
      </div>
      <button type="button" class="btn-secondary" :disabled="loading" @click="reloadAll">
        <AppIcon name="refresh" :size="16" />{{ t('media.refresh') }}
      </button>
      <button type="button" class="btn-primary" @click="picker?.click()">
        <AppIcon name="upload" :size="16" />{{ t('media.upload.button') }}
      </button>
      <input ref="picker" type="file" multiple class="hidden" :accept="acceptAttr" @change="onPick">
    </header>

    <MediaUploadQueue :entries="uploads" @cancel="cancelUpload" @dismiss="dismissUpload" @clear="clearUploads" />

    <section class="card">
      <div class="flex flex-wrap items-center gap-1 border-b border-slate-200 px-2 pt-2 dark:border-slate-700" role="tablist">
        <button
          v-for="tab in kindTabs"
          :key="tab || 'all'"
          type="button"
          role="tab"
          :aria-selected="filters.kind === tab"
          class="-mb-px flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm"
          :class="filters.kind === tab ? 'border-primary font-medium text-primary' : 'border-transparent muted hover:text-slate-700 dark:hover:text-slate-200'"
          @click="setFilter('kind', tab)"
        >
          {{ tab ? t(`media.kinds.${tab}`) : t('media.filters.allKinds') }}
          <span v-if="kindCount(tab)" class="rounded-badge bg-slate-100 px-1.5 text-xs tabular-nums dark:bg-slate-700">{{ kindCount(tab) }}</span>
        </button>
      </div>

      <div class="flex flex-wrap items-end gap-3 px-4 py-3">
        <label class="block min-w-[10rem] flex-1">
          <span class="label">{{ t('media.filters.search') }}</span>
          <input v-model="search" type="search" class="input" :placeholder="t('media.filters.searchHint')">
        </label>
        <label class="block w-full sm:w-48">
          <span class="label">{{ t('media.filters.source') }}</span>
          <select class="input" :value="filters.source" @change="setFilter('source', $event.target.value)">
            <option value="">{{ t('media.filters.allSources') }}</option>
            <option v-for="s in MEDIA_SOURCES" :key="s" :value="s">{{ t(`media.sources.${s}`) }}</option>
          </select>
        </label>
        <label class="block w-[calc(50%-0.375rem)] sm:w-40">
          <span class="label">{{ t('media.filters.from') }}</span>
          <input type="date" class="input" :value="filters.from" :max="filters.to || undefined" @change="setFilter('from', $event.target.value)">
        </label>
        <label class="block w-[calc(50%-0.375rem)] sm:w-40">
          <span class="label">{{ t('media.filters.to') }}</span>
          <input type="date" class="input" :value="filters.to" :min="filters.from || undefined" @change="setFilter('to', $event.target.value)">
        </label>
        <button v-if="filtered" type="button" class="btn-ghost" @click="resetFilters">
          <AppIcon name="close" :size="14" />{{ t('media.filters.reset') }}
        </button>
      </div>

      <div
        v-if="items.length"
        class="flex flex-wrap items-center gap-2 border-t border-slate-200 px-4 py-2 text-sm dark:border-slate-700"
      >
        <span v-if="selected.size" class="font-medium">{{ t('media.select.count', { n: selected.size }, selected.size) }}</span>
        <span v-else class="muted">{{ t('media.select.total', { n: total }, total) }}</span>
        <span class="flex-1" />
        <button v-if="!allOnPageSelected" type="button" class="btn-ghost btn-sm" @click="selectAllOnPage">
          <AppIcon name="check" :size="14" />{{ t('media.select.page') }}
        </button>
        <template v-if="selected.size">
          <button type="button" class="btn-ghost btn-sm" @click="clearSelection">{{ t('media.select.clear') }}</button>
          <button type="button" class="btn-danger btn-sm" :disabled="deleting" @click="deleteSelected">
            <Spinner v-if="deleting" :size="12" /><AppIcon v-else name="trash" :size="14" />{{ t('media.select.delete') }}
          </button>
        </template>
      </div>

      <p v-if="error" class="mx-4 mb-3 rounded-button bg-rose-50 px-3 py-2 text-sm text-rose-800 dark:bg-rose-500/10 dark:text-rose-200">
        {{ error }}
      </p>

      <div v-if="loading && !items.length" class="flex justify-center py-12"><Spinner :size="24" /></div>
      <EmptyState
        v-else-if="!items.length && !error"
        icon="media"
        :title="filtered ? t('media.empty.filteredTitle') : t('media.empty.title')"
        :text="filtered ? t('media.empty.filteredText') : t('media.empty.text')"
      >
        <button v-if="filtered" type="button" class="btn-secondary" @click="resetFilters">{{ t('media.filters.reset') }}</button>
        <button v-else type="button" class="btn-primary" @click="picker?.click()">
          <AppIcon name="upload" :size="16" />{{ t('media.upload.button') }}
        </button>
      </EmptyState>
      <ul
        v-else
        class="grid grid-cols-2 gap-x-3 gap-y-4 p-4 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-5"
        :class="loading && 'opacity-60'"
      >
        <MediaTile
          v-for="item in items"
          :key="item.id"
          :item="item"
          :selected="selected.has(item.id)"
          :selecting="selected.size > 0"
          @open="openFile"
          @toggle="toggleSelect"
        />
      </ul>

      <div v-if="pages > 1" class="flex items-center justify-center gap-3 border-t border-slate-200 p-3 dark:border-slate-700">
        <button type="button" class="btn-secondary btn-sm" :disabled="filters.page <= 1 || loading" @click="setPage(filters.page - 1)">
          {{ t('media.pager.prev') }}
        </button>
        <span class="text-sm tabular-nums muted">{{ t('media.pager.page', { page: filters.page, pages }) }}</span>
        <button type="button" class="btn-secondary btn-sm" :disabled="filters.page >= pages || loading" @click="setPage(filters.page + 1)">
          {{ t('media.pager.next') }}
        </button>
      </div>
    </section>

    <MediaStorage :stats="stats" :error="statsError" />

    <p class="text-xs muted">{{ t('media.upload.hint', { image: maxMb('image'), video: maxMb('video'), audio: maxMb('audio') }) }}</p>

    <div
      v-if="dragging"
      class="pointer-events-none fixed inset-0 z-[90] flex items-center justify-center bg-slate-950/40 p-6"
    >
      <div class="rounded-modal border-2 border-dashed border-white bg-slate-900/80 px-10 py-8 text-center text-white">
        <AppIcon name="upload" :size="32" class="mx-auto" />
        <p class="mt-3 text-base font-semibold">{{ t('media.upload.drop') }}</p>
      </div>
    </div>

    <MediaViewer
      :open="!!viewerItem"
      :item="viewerItem"
      :has-prev="viewerIndex > 0"
      :has-next="viewerIndex >= 0 && viewerIndex < items.length - 1"
      :position="viewerIndex >= 0 ? `${viewerIndex + 1} / ${items.length}` : ''"
      @close="closeViewer"
      @prev="stepViewer(-1)"
      @next="stepViewer(1)"
      @updated="onItemUpdated"
      @deleted="onItemDeleted"
      @missing="onViewerMissing"
    />
  </div>
</template>

<script setup>
import { useDebounceFn, useEventListener } from '@vueuse/core'
import { apiErrorText } from '~/utils/apiErrorText.js'
import {
  MEDIA_KINDS, MEDIA_PAGE_SIZE, MEDIA_SOURCES, mediaApplyIngestJob, mediaCheckFile, mediaFiltersFromQuery,
  mediaFiltersToQuery, mediaHasFilters, mediaListParams, mediaMergeFile, mediaUploadFile,
} from '~/composables/useMediaLibrary.js'

// Two files at a time: enough to keep the line busy, light on a laptop.
const UPLOAD_PARALLEL = 2

const { t, te } = useI18n()
const api = useApi()
const route = useRoute()
const router = useRouter()
const toast = useToast()
const { confirm } = useConfirm()
const { on } = useEvents()

const kindTabs = ['', ...MEDIA_KINDS]
const win = typeof window !== 'undefined' ? window : null

const filters = ref(mediaFiltersFromQuery(route.query))
const search = ref(filters.value.q)
const items = ref([])
const total = ref(0)
const pages = ref(0)
const loading = ref(false)
const error = ref('')
const stats = ref(null)
const statsError = ref('')
const limits = ref(null)
const selected = ref(new Set())
const deleting = ref(false)
const picker = ref(null)

const filtered = computed(() => mediaHasFilters(filters.value))

// Totals per kind; hidden while other filters narrow the list, so the numbers never disagree with it.
function kindCount(kind) {
  const byKind = stats.value?.by_kind
  const f = filters.value
  if (!byKind || f.source || f.q || f.from || f.to) return null
  const n = kind ? byKind[kind]?.count : MEDIA_KINDS.reduce((sum, k) => sum + (byKind[k]?.count || 0), 0)
  return n || null
}

const maxMb = (kind) => limits.value?.max_mb?.[kind] ?? '…'
const acceptAttr = computed(() => {
  const types = limits.value?.types
  if (!types) return 'image/*,video/*,audio/*'
  return MEDIA_KINDS.flatMap((k) => types[k] || []).join(',')
})

// --- list ---------------------------------------------------------------------------------

// Answers can arrive out of order when filters change quickly: keep the last.
let listSeq = 0

async function loadList() {
  const seq = ++listSeq
  loading.value = true
  error.value = ''
  try {
    const res = await api.get('/api/media/files', mediaListParams(filters.value, MEDIA_PAGE_SIZE))
    if (seq !== listSeq) return
    items.value = res.items
    total.value = res.total
    pages.value = res.pages
    // The last page emptied (files deleted): step back to the new last page.
    if (!res.items.length && res.total > 0 && filters.value.page > res.pages) setPage(res.pages)
  } catch (err) {
    if (seq !== listSeq) return
    items.value = []
    total.value = 0
    pages.value = 0
    error.value = apiErrorText(err, t, te)
  } finally {
    if (seq === listSeq) loading.value = false
  }
}

async function loadStats() {
  try {
    stats.value = await api.get('/api/media/stats')
    statsError.value = ''
  } catch (err) {
    statsError.value = apiErrorText(err, t, te)
  }
}

async function loadLimits() {
  try {
    limits.value = await api.get('/api/media/limits')
  } catch {
    // The server checks every file anyway; without limits the browser just skips its quick check.
  }
}

function reloadAll() {
  loadList()
  loadStats()
}

const scheduleReload = useDebounceFn(reloadAll, 700)

// --- filters and the address bar -----------------------------------------------------------

const fileParam = computed(() => {
  const n = Number(route.query.file)
  return Number.isInteger(n) && n > 0 ? n : null
})

function syncQuery(fileId = fileParam.value) {
  const query = mediaFiltersToQuery(filters.value)
  if (fileId) query.file = String(fileId)
  router.replace({ query })
}

function setFilter(key, value) {
  if (filters.value[key] === value) return
  filters.value = { ...filters.value, [key]: value, page: 1 }
  clearSelection()
  syncQuery()
  loadList()
}

function setPage(page) {
  if (page < 1 || page === filters.value.page) return
  filters.value = { ...filters.value, page }
  clearSelection()
  syncQuery()
  loadList()
}

function resetFilters() {
  search.value = ''
  filters.value = mediaFiltersFromQuery({})
  clearSelection()
  syncQuery()
  loadList()
}

const applySearch = useDebounceFn((value) => setFilter('q', value.trim()), 350)
watch(search, (v) => applySearch(v))

// Back/forward through filter states.
watch(() => route.query, (q) => {
  const next = mediaFiltersFromQuery(q)
  if (JSON.stringify(next) === JSON.stringify(filters.value)) return
  filters.value = next
  search.value = next.q
  clearSelection()
  loadList()
})

// --- selection and deleting ----------------------------------------------------------------

const allOnPageSelected = computed(() => items.value.length > 0 && items.value.every((i) => selected.value.has(i.id)))

function toggleSelect(item) {
  const next = new Set(selected.value)
  if (next.has(item.id)) next.delete(item.id)
  else next.add(item.id)
  selected.value = next
}

function selectAllOnPage() {
  selected.value = new Set([...selected.value, ...items.value.map((i) => i.id)])
}

function clearSelection() {
  if (selected.value.size) selected.value = new Set()
}

function dropFromList(ids) {
  const gone = new Set(ids)
  const before = items.value.length
  items.value = items.value.filter((i) => !gone.has(i.id))
  total.value = Math.max(0, total.value - (before - items.value.length))
  if ([...gone].some((id) => selected.value.has(id))) {
    selected.value = new Set([...selected.value].filter((id) => !gone.has(id)))
  }
}

async function deleteSelected() {
  const ids = [...selected.value]
  if (!ids.length || deleting.value) return
  const inUse = items.value.filter((i) => selected.value.has(i.id) && i.usage_count !== 0).length
  let message = t('media.delete.manyAsk', { n: ids.length }, ids.length)
  if (inUse) message += ` ${t('media.delete.manyInUse', { n: inUse }, inUse)}`
  const ok = await confirm({ title: t('media.delete.manyTitle'), message, tone: 'danger', confirmLabel: t('common.delete') })
  if (!ok) return
  deleting.value = true
  try {
    const res = await api.post('/api/media/files/delete', { ids })
    const done = res.deleted.length + res.missing.length
    dropFromList([...res.deleted, ...res.missing])
    if (done) toast.success(t('media.delete.doneMany', { n: done }, done))
    if (res.blocked.length) {
      const names = res.blocked.map((b) => b.title || `#${b.id}`).join(', ')
      toast.error(t('media.delete.blocked', { n: res.blocked.length, names }, res.blocked.length))
    }
    selected.value = new Set(res.blocked.map((b) => b.id))
    scheduleReload()
  } catch (err) {
    toast.error(apiErrorText(err, t, te))
  } finally {
    deleting.value = false
  }
}

// --- viewer --------------------------------------------------------------------------------

// A file opened by link (`/media?file=12`) that is not on the current page.
const outsideItem = ref(null)

const viewerIndex = computed(() => (fileParam.value ? items.value.findIndex((i) => i.id === fileParam.value) : -1))
const viewerItem = computed(() => {
  if (!fileParam.value) return null
  if (viewerIndex.value >= 0) return items.value[viewerIndex.value]
  return outsideItem.value?.id === fileParam.value ? outsideItem.value : null
})

async function loadOutside(id) {
  try {
    const res = await api.get(`/api/media/files/${id}`)
    if (fileParam.value === id) outsideItem.value = res
  } catch (err) {
    if (fileParam.value !== id) return
    if (err.status === 404) onViewerMissing()
    else toast.error(apiErrorText(err, t, te))
  }
}

watch(fileParam, (id) => {
  if (id && outsideItem.value?.id !== id && !items.value.some((i) => i.id === id)) loadOutside(id)
}, { immediate: true })

function openFile(item) {
  syncQuery(item.id)
}

function closeViewer() {
  outsideItem.value = null
  syncQuery(null)
}

function stepViewer(delta) {
  const next = items.value[viewerIndex.value + delta]
  if (viewerIndex.value >= 0 && next) syncQuery(next.id)
}

function onViewerMissing() {
  toast.error(t('media.viewer.missing'))
  closeViewer()
}

function patchItem(file) {
  mediaMergeFile(items.value, file)
  if (outsideItem.value?.id === file.id) outsideItem.value = { ...outsideItem.value, ...file }
}

function onItemUpdated(file) {
  const rest = { ...file }
  delete rest.usages
  if (Array.isArray(file.usages)) rest.usage_count = file.usages.length
  patchItem(rest)
}

// A file is gone: from the viewer's "Delete" or from the server event, whichever
// comes first (the second call finds nothing to do). The open viewer moves to
// the neighbour, as photo apps do. True when the file was on the screen.
function removeFile(id) {
  const index = items.value.findIndex((i) => i.id === id)
  const outside = outsideItem.value?.id === id
  if (index < 0 && !outside) return false
  dropFromList([id])
  if (outside) outsideItem.value = null
  if (fileParam.value !== id) return true
  const next = index >= 0 ? (items.value[index] || items.value[index - 1]) : null
  if (next) syncQuery(next.id)
  else closeViewer()
  return true
}

function onItemDeleted(id) {
  removeFile(id)
  scheduleReload()
}

// --- uploads -------------------------------------------------------------------------------

const uploads = ref([])
const controllers = new Map()
let uploadSeq = 0

const activeUploads = computed(() => uploads.value.filter((e) => e.status === 'waiting' || e.status === 'uploading').length)

function addFiles(fileList) {
  const list = [...(fileList || [])]
  if (!list.length) return
  for (const file of list) {
    const problem = limits.value ? mediaCheckFile(file, limits.value) : null
    uploads.value.push({
      key: ++uploadSeq,
      name: file.name,
      size: file.size,
      progress: 0,
      status: problem ? 'error' : 'waiting',
      error: problem ? apiErrorText(problem, t, te) : '',
      file: problem ? null : file,
    })
  }
  pump()
}

function pump() {
  let running = uploads.value.filter((e) => e.status === 'uploading').length
  for (const entry of uploads.value) {
    if (running >= UPLOAD_PARALLEL) break
    if (entry.status !== 'waiting') continue
    running++
    send(entry)
  }
}

async function send(entry) {
  entry.status = 'uploading'
  const ctrl = new AbortController()
  controllers.set(entry.key, ctrl)
  try {
    await mediaUploadFile(entry.file, { onProgress: (p) => { entry.progress = p }, signal: ctrl.signal })
    entry.status = 'done'
    entry.progress = 1
    scheduleReload()
  } catch (err) {
    if (err.code === 'aborted') entry.status = 'cancelled'
    else {
      entry.status = 'error'
      entry.error = apiErrorText(err, t, te)
    }
  } finally {
    entry.file = null
    controllers.delete(entry.key)
    pump()
    if (!activeUploads.value && uploads.value.every((e) => e.status === 'done')) {
      setTimeout(() => {
        if (!activeUploads.value) uploads.value = uploads.value.filter((e) => e.status !== 'done')
      }, 4000)
    }
  }
}

function cancelUpload(key) {
  const entry = uploads.value.find((e) => e.key === key)
  if (!entry) return
  if (entry.status === 'waiting') {
    entry.status = 'cancelled'
    entry.file = null
  } else {
    controllers.get(key)?.abort()
  }
}

function dismissUpload(key) {
  uploads.value = uploads.value.filter((e) => e.key !== key)
}

function clearUploads() {
  uploads.value = uploads.value.filter((e) => e.status === 'waiting' || e.status === 'uploading')
}

function cancelAllUploads() {
  for (const entry of uploads.value) {
    if (entry.status === 'waiting' || entry.status === 'uploading') cancelUpload(entry.key)
  }
}

function onPick(e) {
  addFiles(e.target.files)
  e.target.value = ''
}

// Leaving the screen stops the uploads, so ask first.
onBeforeRouteLeave(async () => {
  if (!activeUploads.value) return true
  const ok = await confirm({
    message: t('media.upload.leaveAsk', { n: activeUploads.value }, activeUploads.value),
    tone: 'danger',
    confirmLabel: t('media.upload.leave'),
  })
  if (ok) cancelAllUploads()
  return ok
})

// Closing the tab: only the browser's own question is possible here.
useEventListener(win, 'beforeunload', (e) => {
  if (!activeUploads.value) return
  e.preventDefault()
  e.returnValue = ''
})

// --- drag and drop -------------------------------------------------------------------------

// The whole window takes the drop, so a file dropped off target never opens in the tab.
const dragging = ref(false)
let dragDepth = 0
const hasFiles = (e) => [...(e.dataTransfer?.types || [])].includes('Files')

function onDragEnter(e) {
  if (!hasFiles(e)) return
  e.preventDefault()
  dragDepth++
  dragging.value = true
}

function onDragOver(e) {
  if (!hasFiles(e)) return
  e.preventDefault()
  e.dataTransfer.dropEffect = 'copy'
}

function onDragLeave(e) {
  if (!hasFiles(e)) return
  dragDepth = Math.max(0, dragDepth - 1)
  if (!dragDepth) dragging.value = false
}

function onDrop(e) {
  if (!hasFiles(e)) return
  e.preventDefault()
  dragDepth = 0
  dragging.value = false
  addFiles(e.dataTransfer.files)
}

useEventListener(win, 'dragenter', onDragEnter)
useEventListener(win, 'dragover', onDragOver)
useEventListener(win, 'dragleave', onDragLeave)
useEventListener(win, 'drop', onDrop)

// --- live updates --------------------------------------------------------------------------

const isLibraryFile = (f) => f && !f.is_service && MEDIA_KINDS.includes(f.kind)

on('file.created', (f) => { if (isLibraryFile(f)) scheduleReload() })
on('file.updated', (f) => {
  if (!f?.id) return
  if (f.is_service) {
    // Turned into a service file: it leaves the library.
    if (items.value.some((i) => i.id === f.id)) scheduleReload()
    return
  }
  patchItem(f)
})
// Background cleanup deletes service files too; only what was on the screen refills the page.
on('file.deleted', ({ id }) => {
  if (id && removeFile(id)) scheduleReload()
})
on('job.updated', (job) => {
  if (mediaApplyIngestJob(items.value, job)) return
  if (outsideItem.value && job?.kind === 'media.ingest' && job.ref_id === outsideItem.value.id) {
    const box = [outsideItem.value]
    mediaApplyIngestJob(box, job)
    outsideItem.value = box[0]
  }
})
on('reconnect', reloadAll)

onMounted(() => {
  loadLimits()
  reloadAll()
})

</script>
