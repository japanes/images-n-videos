<template>
  <div class="page space-y-4">
    <header class="flex flex-wrap items-start gap-3">
      <div class="min-w-0 flex-1">
        <h1 class="page-title">{{ t('jobsPage.title') }}</h1>
        <p class="mt-1 text-sm muted">{{ t('jobsPage.subtitle') }}</p>
      </div>
      <button type="button" class="btn-secondary" :disabled="loading" @click="reloadAll">
        <AppIcon name="refresh" :size="16" />{{ t('jobsPage.refresh') }}
      </button>
    </header>

    <p
      v-if="overview && !overview.runner_alive"
      class="flex gap-2 rounded-card bg-rose-50 px-4 py-3 text-sm text-rose-800 dark:bg-rose-500/10 dark:text-rose-200"
    >
      <AppIcon name="alert" :size="16" class="mt-0.5" />{{ t('jobsPage.runnerDown') }}
    </p>

    <JobsServices
      :services="health?.services || []"
      :checked-at="health?.checked_at || ''"
      :loading="healthLoading"
      :error="healthError"
      @check="loadHealth"
    />

    <div class="grid gap-4 lg:grid-cols-2">
      <JobsLoad :groups="overview?.groups || []" @settings="settingsOpen = true" />
      <JobsUpkeep
        :settings="overview?.settings || {}"
        :backups="overview?.backups || { count: 0, last: null }"
        @settings="settingsOpen = true"
      />
    </div>

    <section class="card">
      <div class="flex flex-wrap items-center gap-1 border-b border-slate-200 px-2 pt-2 dark:border-slate-700" role="tablist">
        <button
          v-for="tab in tabs"
          :key="tab"
          type="button"
          role="tab"
          :aria-selected="filters.status === tab"
          class="-mb-px flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm"
          :class="filters.status === tab ? 'border-primary font-medium text-primary' : 'border-transparent muted hover:text-slate-700 dark:hover:text-slate-200'"
          @click="setFilter('status', tab)"
        >
          {{ t(`jobsPage.tabs.${tab}`) }}
          <span v-if="countFor(tab) !== null" class="rounded-badge bg-slate-100 px-1.5 text-xs tabular-nums dark:bg-slate-700">{{ countFor(tab) }}</span>
        </button>
      </div>

      <div class="flex flex-wrap items-end gap-3 px-4 py-3">
        <label class="block min-w-[10rem] flex-1">
          <span class="label">{{ t('jobsPage.filters.search') }}</span>
          <input v-model="search" type="search" class="input" :placeholder="t('jobsPage.filters.searchHint')">
        </label>
        <label class="block w-full sm:w-44">
          <span class="label">{{ t('jobsPage.filters.group') }}</span>
          <select class="input" :value="filters.group" @change="setFilter('group', $event.target.value)">
            <option value="">{{ t('jobsPage.filters.allGroups') }}</option>
            <option v-for="g in groupOptions" :key="g" :value="g">{{ groupLabel(g) }}</option>
          </select>
        </label>
        <label v-if="kindOptions.length > 1" class="block w-full sm:w-56">
          <span class="label">{{ t('jobsPage.filters.kind') }}</span>
          <select class="input" :value="filters.kind" @change="setFilter('kind', $event.target.value)">
            <option value="">{{ t('jobsPage.filters.allKinds') }}</option>
            <option v-for="k in kindOptions" :key="k.kind" :value="k.kind">{{ jobKindLabel(k.kind, t) }} ({{ k.count }})</option>
          </select>
        </label>
        <button v-if="filtered" type="button" class="btn-ghost" @click="resetFilters">
          <AppIcon name="close" :size="14" />{{ t('jobsPage.filters.reset') }}
        </button>
      </div>
      <p v-if="filters.refType" class="px-4 pb-2 text-xs muted">
        {{ t('jobsPage.filters.owner', { type: filters.refType, id: filters.refId ?? '' }) }}
      </p>

      <p v-if="error" class="mx-4 mb-3 rounded-button bg-rose-50 px-3 py-2 text-sm text-rose-800 dark:bg-rose-500/10 dark:text-rose-200">
        {{ error }}
      </p>

      <div v-if="loading && !items.length" class="flex justify-center py-12"><Spinner :size="24" /></div>
      <EmptyState
        v-else-if="!items.length && !error"
        icon="jobs"
        :title="filtered ? t('jobsPage.empty.filteredTitle') : t('jobsPage.empty.title')"
        :text="filtered ? t('jobsPage.empty.filteredText') : t('jobsPage.empty.text')"
      >
        <button v-if="filtered" type="button" class="btn-secondary" @click="resetFilters">{{ t('jobsPage.filters.reset') }}</button>
      </EmptyState>
      <ul v-else class="divide-y divide-slate-200 dark:divide-slate-700">
        <JobsRow
          v-for="job in items"
          :key="job.id"
          :job="job"
          :now="now"
          :busy="busy.has(job.id)"
          @cancel="cancel"
          @retry="retry"
        />
      </ul>
      <div v-if="hasMore" class="flex justify-center border-t border-slate-200 p-3 dark:border-slate-700">
        <button type="button" class="btn-secondary" :disabled="loadingMore" @click="loadMore">
          <Spinner v-if="loadingMore" :size="14" />{{ t('jobsPage.loadMore') }}
        </button>
      </div>
    </section>

    <JobsSettingsModal
      :open="settingsOpen"
      :groups="overview?.groups || []"
      :settings="overview?.settings || {}"
      @close="settingsOpen = false"
      @saved="loadOverview"
    />
  </div>
</template>

<script setup>
import { useDebounceFn, useIntervalFn } from '@vueuse/core'
import { apiErrorText } from '~/utils/apiErrorText.js'
import { jobKindLabel } from '~/utils/jobRefs.js'
import { KNOWN_GROUPS, STATUS_TABS, applyProgress, mergeJob } from '~/utils/jobsView.js'

const PAGE_SIZE = 50

const { t, te } = useI18n()
const api = useApi()
const route = useRoute()
const router = useRouter()
const toast = useToast()
const { confirm } = useConfirm()
const { on } = useEvents()

const tabs = Object.keys(STATUS_TABS)

function fromQuery(q) {
  const status = typeof q.status === 'string' && q.status ? q.status : 'all'
  const refId = q.ref_id !== undefined && q.ref_id !== '' && !Number.isNaN(Number(q.ref_id)) ? Number(q.ref_id) : null
  return {
    status,
    group: typeof q.group === 'string' ? q.group : '',
    kind: typeof q.kind === 'string' ? q.kind : '',
    q: typeof q.q === 'string' ? q.q : '',
    refType: typeof q.ref_type === 'string' ? q.ref_type : '',
    refId,
  }
}

const filters = ref(fromQuery(route.query))
const search = ref(filters.value.q)
const items = ref([])
const hasMore = ref(false)
const nextBeforeId = ref(null)
const loading = ref(false)
const loadingMore = ref(false)
const error = ref('')
const overview = ref(null)
const health = ref(null)
const healthLoading = ref(false)
const healthError = ref('')
const settingsOpen = ref(false)
const busy = ref(new Set())
const now = ref(Date.now())

const filtered = computed(() => {
  const f = filters.value
  return f.status !== 'all' || !!f.group || !!f.kind || !!f.q || !!f.refType
})

const groupOptions = computed(() => {
  const names = (overview.value?.groups || []).map((g) => g.group)
  return names.length ? names : KNOWN_GROUPS
})
const kindOptions = computed(() => (overview.value?.kinds || [])
  .filter((k) => k.count > 0 && (!filters.value.group || k.group === filters.value.group)))
const groupLabel = (name) => (KNOWN_GROUPS.includes(name) ? t(`jobsPage.groups.${name}`) : name)

function countFor(tab) {
  const c = overview.value?.counts
  if (!c) return null
  const n = tab === 'all' ? c.all : c[tab]
  return typeof n === 'number' && n > 0 ? n : null
}

function listQuery(beforeId) {
  const f = filters.value
  const q = { status: f.status, limit: PAGE_SIZE }
  if (f.group) q.group = f.group
  if (f.kind) q.kind = f.kind
  if (f.q) q.q = f.q
  if (f.refType) q.ref_type = f.refType
  if (f.refId !== null) q.ref_id = f.refId
  if (beforeId) q.before_id = beforeId
  return q
}

// Answers can arrive out of order when filters change quickly: keep the last.
let listSeq = 0

async function loadList() {
  const seq = ++listSeq
  loading.value = true
  error.value = ''
  try {
    const res = await api.get('/api/jobs_ui/list', listQuery())
    if (seq !== listSeq) return
    items.value = res.items
    hasMore.value = res.has_more
    nextBeforeId.value = res.next_before_id
  } catch (err) {
    if (seq !== listSeq) return
    items.value = []
    hasMore.value = false
    error.value = apiErrorText(err, t, te)
  } finally {
    if (seq === listSeq) loading.value = false
  }
}

async function loadMore() {
  if (!nextBeforeId.value || loadingMore.value) return
  const seq = listSeq
  loadingMore.value = true
  try {
    const res = await api.get('/api/jobs_ui/list', listQuery(nextBeforeId.value))
    if (seq !== listSeq) return
    const seen = new Set(items.value.map((j) => j.id))
    items.value.push(...res.items.filter((j) => !seen.has(j.id)))
    hasMore.value = res.has_more
    nextBeforeId.value = res.next_before_id
  } catch (err) {
    toast.error(apiErrorText(err, t, te))
  } finally {
    loadingMore.value = false
  }
}

async function loadOverview() {
  try {
    overview.value = await api.get('/api/jobs_ui/overview')
  } catch (err) {
    error.value ||= apiErrorText(err, t, te)
  }
}
const refreshOverview = useDebounceFn(loadOverview, 800)

async function loadHealth() {
  healthLoading.value = true
  healthError.value = ''
  try {
    health.value = await api.get('/api/jobs_ui/health')
  } catch (err) {
    healthError.value = apiErrorText(err, t, te)
  } finally {
    healthLoading.value = false
  }
}

function reloadAll() {
  loadList()
  loadOverview()
  loadHealth()
}

function syncQuery() {
  const f = filters.value
  const query = {}
  if (f.status !== 'all') query.status = f.status
  if (f.group) query.group = f.group
  if (f.kind) query.kind = f.kind
  if (f.q) query.q = f.q
  if (f.refType) query.ref_type = f.refType
  if (f.refId !== null) query.ref_id = String(f.refId)
  router.replace({ query })
}

function setFilter(key, value) {
  if (filters.value[key] === value) return
  filters.value = { ...filters.value, [key]: value }
  if (key === 'group' && filters.value.kind) {
    const kind = (overview.value?.kinds || []).find((k) => k.kind === filters.value.kind)
    if (kind && value && kind.group !== value) filters.value.kind = ''
  }
  syncQuery()
  loadList()
}

function resetFilters() {
  search.value = ''
  filters.value = fromQuery({})
  syncQuery()
  loadList()
}

const applySearch = useDebounceFn((value) => setFilter('q', value.trim()), 350)
watch(search, (v) => applySearch(v))

// Back/forward through filter states.
watch(() => route.query, (q) => {
  const next = fromQuery(q)
  if (JSON.stringify(next) === JSON.stringify(filters.value)) return
  filters.value = next
  search.value = next.q
  loadList()
})

function setBusy(id, value) {
  const next = new Set(busy.value)
  if (value) next.add(id)
  else next.delete(id)
  busy.value = next
}

const jobName = (job) => job.title || jobKindLabel(job.kind, t)

async function cancel(job) {
  if (!await confirm({ message: t('jobs.cancelAsk', { title: jobName(job) }), tone: 'danger', confirmLabel: t('jobs.cancel') })) return
  setBusy(job.id, true)
  try {
    mergeJob(items.value, await api.post(`/api/jobs/${job.id}/cancel`), filters.value)
    refreshOverview()
  } catch (err) {
    toast.error(apiErrorText(err, t, te))
  } finally {
    setBusy(job.id, false)
  }
}

async function retry(job) {
  if (!await confirm({ message: t('jobsPage.row.retryAsk', { title: jobName(job) }), confirmLabel: t('jobsPage.row.retry') })) return
  setBusy(job.id, true)
  try {
    mergeJob(items.value, await api.post(`/api/jobs/${job.id}/retry`), filters.value)
    refreshOverview()
  } catch (err) {
    toast.error(apiErrorText(err, t, te))
  } finally {
    setBusy(job.id, false)
  }
}

on('job.updated', (job) => {
  mergeJob(items.value, job, filters.value)
  refreshOverview()
})
on('job.progress', (p) => applyProgress(items.value, p))
on('reconnect', () => {
  loadList()
  loadOverview()
})

// Durations of running jobs tick; the services are re-checked now and then.
useIntervalFn(() => { now.value = Date.now() }, 1000)
useIntervalFn(() => { if (!healthLoading.value) loadHealth() }, 60000)

onMounted(reloadAll)
</script>
