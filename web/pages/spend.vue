<template>
  <div class="page space-y-4">
    <header class="flex flex-wrap items-start gap-3">
      <div class="min-w-0 flex-1">
        <h1 class="page-title">{{ t('spend.title') }}</h1>
        <p class="mt-1 text-sm muted">
          {{ t('spend.caption') }}
          <a
            v-if="summary?.billing_url"
            :href="summary.billing_url"
            target="_blank"
            rel="noopener noreferrer"
            class="inline-flex items-center gap-0.5 text-primary hover:underline"
          >
            {{ t('spend.billingLink') }}<AppIcon name="external" :size="12" />
          </a>
        </p>
      </div>
      <button type="button" class="btn-secondary" @click="settingsOpen = true">
        <AppIcon name="settings" :size="16" />{{ t('spend.settingsButton') }}
      </button>
      <button type="button" class="btn-secondary" :disabled="loading" :aria-label="t('spend.refresh')" :title="t('spend.refresh')" @click="reloadAll()">
        <AppIcon name="refresh" :size="16" />
      </button>
    </header>

    <p
      v-if="summary?.stub_mode"
      class="flex gap-2 rounded-card bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:bg-amber-500/10 dark:text-amber-200"
    >
      <AppIcon name="info" :size="16" class="mt-0.5 shrink-0" />{{ t('spend.notices.stubMode') }}
    </p>

    <div v-if="loadError" class="flex flex-wrap items-center gap-3 rounded-card bg-rose-50 px-4 py-3 text-sm text-rose-800 dark:bg-rose-500/10 dark:text-rose-200">
      <AppIcon name="alert" :size="16" />
      <span class="min-w-0 flex-1">{{ loadError }}</span>
      <button type="button" class="btn-secondary btn-sm" @click="reloadAll()">{{ t('common.retry') }}</button>
    </div>

    <div v-if="!summary && loading" class="flex justify-center py-16"><Spinner :size="28" /></div>

    <template v-if="summary">
      <SpendSummaryCards :summary="summary" @settings="settingsOpen = true" />

      <EmptyState
        v-if="!everCalled"
        icon="spend"
        :title="t('spend.empty.title')"
        :text="t('spend.empty.text')"
      />

      <template v-else>
        <SpendFilters
          :model-value="filters"
          :choices="choices"
          :show-stub="showStub"
          @update:model-value="setFilters"
        />
        <div class="space-y-4 transition-opacity" :class="refreshing && 'opacity-60'">
          <template v-if="stats">
            <SpendChart :days="stats.days" />
            <SpendBreakdown :stats="stats" @pick="pick" />
          </template>
          <SpendCallsTable
            :items="calls.items"
            :total="calls.total"
            :sum-usd="calls.sum_usd"
            :page="filters.page"
            @open="openCall"
            @page="(p) => setFilters({ ...filters, page: p })"
          />
        </div>
      </template>
    </template>

    <SpendCallModal :call-id="openCallId" @close="closeCall" @filter-ref="filterRef" />
    <SpendSettingsModal
      :open="settingsOpen"
      :cap-resets-at="summary?.cap_resets_at || ''"
      @close="settingsOpen = false"
      @saved="loadSummary"
    />
  </div>
</template>

<script setup>
import { apiErrorText } from '~/utils/apiErrorText.js'
import {
  SPEND_PAGE_SIZE, spendApiQuery, spendDebounce, spendFiltersFromQuery, spendFiltersToQuery, spendTzOffset,
} from '~/composables/useSpend.js'

const { t, te } = useI18n()
const api = useApi()
const route = useRoute()
const router = useRouter()

const summary = ref(null)
const choices = ref({})
const stats = ref(null)
const calls = ref({ items: [], total: 0, sum_usd: 0 })
const loading = ref(false)
const refreshing = ref(false)
const loadError = ref('')
const settingsOpen = ref(false)
const openCallId = ref(null)

// The URL is the one source of truth for filters: links from other screens
// (a clip's cost, a call card) land here already narrowed, and Back works.
const filters = computed(() => spendFiltersFromQuery(route.query))
const setFilters = (f) => {
  const query = spendFiltersToQuery(f)
  if (openCallId.value !== null) query.call = String(openCallId.value)
  router.replace({ query })
}

const everCalled = computed(() => (summary.value?.real_calls || 0) + (summary.value?.stub_calls || 0) > 0)
const showStub = computed(() => Boolean(summary.value?.stub_calls || summary.value?.stub_mode || filters.value.stub))

const fail = (err) => { loadError.value = apiErrorText(err, t, te) }

async function loadSummary() {
  try {
    summary.value = await api.get('/api/spend/summary', { tz: spendTzOffset() })
  } catch (err) { fail(err) }
}
async function loadChoices() {
  try {
    choices.value = await api.get('/api/spend/filters')
  } catch (err) { fail(err) }
}

// Stats follow the filters; the table also follows the page. Each load drops
// the answer of an older one that comes back late.
let statsSeq = 0
let callsSeq = 0
async function loadStats() {
  const mine = ++statsSeq
  try {
    const res = await api.get('/api/spend/stats', spendApiQuery(filters.value))
    if (mine === statsSeq) stats.value = res
  } catch (err) { if (mine === statsSeq) fail(err) }
}
async function loadCalls() {
  const mine = ++callsSeq
  const f = filters.value
  try {
    const res = await api.get('/api/spend/calls', {
      ...spendApiQuery(f), limit: SPEND_PAGE_SIZE, offset: (f.page - 1) * SPEND_PAGE_SIZE,
    })
    if (mine !== callsSeq) return
    // A page past the end (rows were filtered away) → the last real page.
    if (!res.items.length && res.total && f.page > 1) {
      setFilters({ ...f, page: Math.max(1, Math.ceil(res.total / SPEND_PAGE_SIZE)) })
      return
    }
    calls.value = res
  } catch (err) { if (mine === callsSeq) fail(err) }
}

async function track(work) {
  if (summary.value) refreshing.value = true
  else loading.value = true
  try { await work } finally { loading.value = false; refreshing.value = false }
}

function reloadAll() {
  loadError.value = ''
  return track(Promise.all([loadSummary(), loadChoices(), loadStats(), loadCalls()]))
}

const statsKey = computed(() => JSON.stringify(spendApiQuery(filters.value)))
watch(statsKey, () => { loadError.value = ''; track(Promise.all([loadStats(), loadCalls()])) })
watch(() => filters.value.page, (p, old) => { if (p !== old) track(loadCalls()) })

// Live: a finished call changes the totals, the chart and maybe a row on screen.
const later = spendDebounce(() => {
  loadSummary()
  loadStats()
  loadCalls()
  if (!choices.value?.statuses?.length) loadChoices()
}, 1500)
const { on } = useEvents()
on('ai_call.finished', () => later())
on('reconnect', () => reloadAll())
on('settings.changed', (e) => {
  if (['spend.credit_usd', 'spend.credit_days', 'google.daily_cap_usd', 'connection.trial_started_on'].includes(e?.key)) {
    loadSummary()
  }
})
onBeforeUnmount(() => later.cancel())

function pick({ field, value }) {
  if (!value) return
  setFilters({ ...filters.value, [field]: value })
}

// The open call card is in the URL too (?call=12), so it can be linked to.
function openCall(id) {
  openCallId.value = id
  router.replace({ query: { ...route.query, call: String(id) } })
}
function closeCall() {
  openCallId.value = null
  const { call: _call, ...rest } = route.query
  router.replace({ query: rest })
}
function filterRef({ type, id }) {
  openCallId.value = null
  setFilters({ ...filters.value, refType: type, refId: id, period: 'all', page: 1 })
}

onMounted(() => {
  const id = Number(route.query.call)
  if (Number.isInteger(id) && id > 0) openCallId.value = id
  reloadAll()
})
</script>

<style>
/* Chart colours: fixed slot per kind, picked for both themes and checked for
   colour-blind separation (image, video, text, other). */
.spend-palette {
  --spend-image: #2a78d6;
  --spend-video: #eb6834;
  --spend-text: #1baf7a;
  --spend-other: #eda100;
}
.dark .spend-palette {
  --spend-image: #3987e5;
  --spend-video: #d95926;
  --spend-text: #199e70;
  --spend-other: #c98500;
}
</style>
