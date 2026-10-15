<template>
  <ModalShell :open="callId !== null" size="lg" :title="t('spend.call.title', { id: callId ?? '' })" @close="$emit('close')">
    <div v-if="loading && !call" class="flex justify-center py-12"><Spinner :size="24" /></div>

    <div v-else-if="error" class="rounded-button bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:bg-rose-500/10 dark:text-rose-300">
      <p>{{ error }}</p>
      <button type="button" class="btn-secondary btn-sm mt-2" @click="load">{{ t('common.retry') }}</button>
    </div>

    <div v-else-if="call" class="space-y-5 text-sm">
      <!-- Status and what it cost. -->
      <div class="flex flex-wrap items-center gap-2">
        <span class="badge" :class="statusTone">
          <Spinner v-if="call.status === 'running'" :size="11" />
          {{ spendLabel(t, te, 'statuses', call.status) }}
        </span>
        <span v-if="call.stub" class="badge bg-amber-100 text-amber-800 dark:bg-amber-500/20 dark:text-amber-300">{{ t('spend.table.stub') }}</span>
        <span class="ml-auto text-right">
          <span class="block text-2xl font-semibold tabular-nums">{{ formatUsd(call.cost_usd) }}</span>
          <span class="block text-xs muted">{{ call.stub ? t('spend.table.stubHint') : t('spend.call.costHint') }}</span>
        </span>
      </div>

      <!-- Google's own words, never reworded. -->
      <section v-if="call.error_text || call.error_code" class="rounded-card border border-rose-200 bg-rose-50 p-3 dark:border-rose-500/30 dark:bg-rose-500/10">
        <h3 class="flex flex-wrap items-center gap-x-2 text-sm font-semibold text-rose-700 dark:text-rose-300">
          <AppIcon name="alert" :size="16" />
          {{ t('spend.call.errorTitle') }}
          <span v-if="call.error_code" class="font-mono text-xs font-normal">{{ call.error_code }}</span>
          <span v-if="call.http_status" class="font-mono text-xs font-normal">HTTP {{ call.http_status }}</span>
        </h3>
        <pre v-if="call.error_text" class="mt-2 max-h-60 overflow-auto whitespace-pre-wrap break-words font-mono text-xs text-rose-900 dark:text-rose-100">{{ call.error_text }}</pre>
        <p class="mt-2 text-xs text-rose-700/80 dark:text-rose-300/80">{{ t('spend.call.errorVerbatim') }}</p>
      </section>

      <dl class="grid gap-x-4 gap-y-2 sm:grid-cols-[10rem_1fr]">
        <template v-for="row in facts" :key="row.label">
          <dt class="muted">{{ row.label }}</dt>
          <dd class="min-w-0 break-words" :class="row.mono && 'font-mono text-xs leading-5'">{{ row.value }}</dd>
        </template>
      </dl>

      <!-- The prompt that went to Google: file code + version, and the final text. -->
      <section v-if="call.prompt_code || call.prompt_text">
        <h3 class="mb-1.5 flex items-center gap-2 font-semibold">
          {{ t('spend.call.prompt') }}
          <span v-if="call.prompt_code" class="badge bg-slate-100 font-mono text-slate-700 dark:bg-slate-700 dark:text-slate-200">
            {{ call.prompt_code }}<template v-if="call.prompt_version"> · v{{ call.prompt_version }}</template>
          </span>
          <button v-if="call.prompt_text" type="button" class="btn-ghost btn-sm ml-auto" @click="copy(call.prompt_text)">
            <AppIcon name="copy" :size="14" />{{ t('common.copy') }}
          </button>
        </h3>
        <pre v-if="call.prompt_text" class="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-button bg-slate-50 p-3 font-mono text-xs dark:bg-slate-900">{{ call.prompt_text }}</pre>
        <p v-else class="text-xs muted">{{ t('spend.call.noPromptText') }}</p>
      </section>

      <!-- Pictures and videos sent along with the prompt. -->
      <section v-if="call.attachments?.length">
        <h3 class="mb-1.5 font-semibold">{{ t('spend.call.attachments', { n: call.attachments.length }, call.attachments.length) }}</h3>
        <ul class="flex flex-wrap gap-2">
          <li v-for="(a, i) in call.attachments" :key="i" class="w-24">
            <a
              v-if="a.exists && a.url"
              :href="a.url"
              target="_blank"
              rel="noopener"
              class="block h-24 w-24 overflow-hidden rounded-button border border-slate-200 bg-slate-100 dark:border-slate-700 dark:bg-slate-900"
              :title="a.title || a.mime || ''"
            >
              <img v-if="a.thumb_url" :src="a.thumb_url" alt="" class="h-full w-full object-cover" loading="lazy">
              <span v-else class="flex h-full w-full items-center justify-center"><AppIcon :name="a.kind === 'video' ? 'video' : 'paperclip'" :size="24" class="muted" /></span>
            </a>
            <span v-else class="flex h-24 w-24 items-center justify-center rounded-button border border-dashed border-slate-300 p-2 text-center text-[11px] muted dark:border-slate-600">
              {{ a.file_id ? t('spend.call.fileGone') : t('spend.call.fileNotKept') }}
            </span>
            <span class="mt-1 block truncate text-[11px] muted">{{ [a.mime, a.size ? formatBytes(a.size) : ''].filter(Boolean).join(' · ') }}</span>
          </li>
        </ul>
      </section>

      <!-- What this call was for: a work, a clip, an avatar… -->
      <section v-if="call.refs?.length">
        <h3 class="mb-1.5 font-semibold">{{ t('spend.call.refs') }}</h3>
        <ul class="space-y-1.5">
          <li v-for="r in call.refs" :key="`${r.type}:${r.id}`" class="flex flex-wrap items-center gap-x-3 gap-y-1">
            <img v-if="r.thumb_url && r.exists !== false" :src="r.thumb_url" alt="" class="h-8 w-8 rounded object-cover">
            <span class="min-w-0">
              <span class="muted">{{ spendLabel(t, te, 'refTypes', r.type) }}</span>
              <span class="ml-1">{{ r.title || `#${r.id}` }}</span>
              <span v-if="r.exists === false" class="ml-1 text-xs muted">({{ t('spend.call.refGone') }})</span>
            </span>
            <NuxtLink v-if="refRoute(r)" :to="refRoute(r)" class="text-primary hover:underline" @click="$emit('close')">
              {{ t('common.open') }}
            </NuxtLink>
            <a v-else-if="r.url && r.exists !== false" :href="r.url" target="_blank" rel="noopener" class="text-primary hover:underline">
              {{ t('common.open') }}
            </a>
            <button type="button" class="text-primary hover:underline" @click="$emit('filter-ref', { type: r.type, id: r.id })">
              {{ t('spend.call.refCalls') }}
            </button>
          </li>
        </ul>
      </section>

      <!-- Raw data, for when something needs checking against Google. -->
      <section class="space-y-1.5">
        <details v-for="block in rawBlocks" :key="block.key" class="rounded-button border border-slate-200 dark:border-slate-700">
          <summary class="cursor-pointer select-none px-3 py-2 text-xs font-medium">{{ block.label }}</summary>
          <pre class="max-h-72 overflow-auto whitespace-pre-wrap break-words border-t border-slate-200 p-3 font-mono text-xs dark:border-slate-700">{{ block.text }}</pre>
        </details>
      </section>
    </div>

    <template #footer>
      <button type="button" class="btn-secondary" @click="$emit('close')">{{ t('common.close') }}</button>
    </template>
  </ModalShell>
</template>

<script setup>
import { formatBytes, formatDateTime, formatUsd } from '~/utils/format.js'
import { apiErrorText } from '~/utils/apiErrorText.js'
import { jobRefRoute } from '~/utils/jobRefs.js'
import { spendLabel, spendPrettyJson, spendUnitParts } from '~/composables/useSpend.js'

const props = defineProps({
  /** id of the call to show; null = closed */
  callId: { type: Number, default: null },
})
defineEmits(['close', 'filter-ref'])

const { t, te, locale } = useI18n()
const api = useApi()
const toast = useToast()
const router = useRouter()

const call = ref(null)
const loading = ref(false)
const error = ref('')
let seq = 0

async function load() {
  const id = props.callId
  const mine = ++seq
  if (id === null) return
  loading.value = true
  error.value = ''
  try {
    const res = await api.get(`/api/spend/calls/${id}`)
    if (mine === seq) call.value = res
  } catch (err) {
    if (mine === seq) error.value = apiErrorText(err, t, te)
  } finally {
    if (mine === seq) loading.value = false
  }
}
watch(() => props.callId, (id) => {
  call.value = null
  if (id !== null) load()
}, { immediate: true })

// A running call finishes while the card is open → show the final numbers.
const { on } = useEvents()
on('ai_call.finished', (e) => { if (props.callId !== null && Number(e?.id) === props.callId) load() })

const statusTone = computed(() => ({
  success: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-500/20 dark:text-emerald-300',
  error: 'bg-rose-100 text-rose-700 dark:bg-rose-500/20 dark:text-rose-300',
  blocked: 'bg-amber-100 text-amber-800 dark:bg-amber-500/20 dark:text-amber-300',
  running: 'bg-primary/10 text-primary-dark dark:bg-primary/20 dark:text-primary-light',
}[call.value?.status] || 'bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300'))

const facts = computed(() => {
  const c = call.value
  if (!c) return []
  const rows = [
    { label: t('spend.call.started'), value: formatDateTime(c.created_at, locale.value) },
    { label: t('spend.call.duration'), value: c.duration_ms ? t('spend.call.seconds', { n: (c.duration_ms / 1000).toFixed(1) }) : '—' },
    { label: t('spend.call.purpose'), value: spendLabel(t, te, 'purposes', c.purpose) },
    { label: t('spend.call.kind'), value: spendLabel(t, te, 'kinds', c.kind) },
  ]
  if (c.role) rows.push({ label: t('spend.call.role'), value: c.role, mono: true })
  rows.push({ label: t('spend.call.model'), value: c.model_title ? `${c.model_title} (${c.model_id})` : (c.model_id || '—') })
  if (c.region) rows.push({ label: t('spend.call.region'), value: c.region, mono: true })
  if (c.attempt > 1) rows.push({ label: t('spend.call.attempt'), value: String(c.attempt) })
  const units = spendUnitParts(c).map(([key, params]) => t(key, params))
  if (c.video_resolution) units.push(c.video_resolution)
  rows.push({ label: t('spend.call.units'), value: units.length ? units.join(', ') : '—' })
  if (c.operation_name) rows.push({ label: t('spend.call.operation'), value: c.operation_name, mono: true })
  return rows
})

const rawBlocks = computed(() => {
  const c = call.value
  if (!c) return []
  return [
    { key: 'price', label: t('spend.call.priceSnapshot'), text: spendPrettyJson(c.price_snapshot_json) },
    { key: 'request', label: t('spend.call.request'), text: spendPrettyJson(c.request_json) },
    { key: 'response', label: t('spend.call.response'), text: spendPrettyJson(c.response_json) },
  ].filter((b) => b.text)
})

// A screen inside the app: from the backend resolver, else from the registry the
// owning modules fill for the jobs page. A route that does not exist yet gets no link.
function refRoute(r) {
  if (r.exists === false) return null
  const route = r.link || jobRefRoute({ ref_type: r.type, ref_id: r.id })
  if (!route) return null
  try {
    const resolved = router.resolve(route)
    return resolved.matched.length && resolved.name !== 'all' ? route : null
  } catch {
    return null
  }
}

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text)
    toast.success(t('common.copied'))
  } catch (err) {
    toast.error(String(err?.message || err))
  }
}
</script>
