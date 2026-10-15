<template>
  <li class="px-4 py-3">
    <div class="flex flex-wrap items-start gap-x-3 gap-y-2">
      <span class="badge mt-0.5 shrink-0" :class="tone">
        <Spinner v-if="job.status === 'running'" :size="11" />
        {{ t(`jobsPage.status.${job.status}`) }}
      </span>
      <div class="min-w-0 flex-1">
        <p class="truncate text-sm font-medium" :title="name">{{ name }}</p>
        <p class="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-xs muted">
          <span>{{ groupLabel }}</span>
          <span>#{{ job.id }}</span>
          <span>{{ t('jobsPage.row.created', { time: formatDateTime(job.created_at, locale) }) }}</span>
          <span v-if="seconds !== null">
            {{ t(active ? 'jobsPage.row.running' : 'jobsPage.row.took', { duration: formatDuration(seconds) }) }}
          </span>
          <span v-if="(job.attempts || 0) > 1">{{ t('jobsPage.row.attempt', { n: job.attempts }) }}</span>
        </p>
      </div>
      <div class="flex shrink-0 flex-wrap items-center gap-1">
        <NuxtLink v-if="link" :to="link" class="btn-ghost btn-sm">
          <AppIcon name="external" :size="14" />{{ t('common.open') }}
        </NuxtLink>
        <button v-if="job.cancellable" type="button" class="btn-ghost btn-sm" :disabled="busy" @click="$emit('cancel', job)">
          <AppIcon name="stop" :size="14" />{{ t('jobs.cancel') }}
        </button>
        <button
          v-if="job.retryable"
          type="button"
          class="btn-secondary btn-sm"
          :disabled="busy || job.known === false"
          :title="job.known === false ? t('jobsPage.row.unknownKind') : ''"
          @click="$emit('retry', job)"
        >
          <AppIcon name="refresh" :size="14" />{{ t('jobsPage.row.retry') }}
        </button>
      </div>
    </div>

    <div v-if="active" class="mt-2 flex items-center gap-2">
      <div class="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
        <div
          class="h-full bg-primary transition-all"
          :class="percent === null && job.status === 'running' && 'w-1/3 animate-pulse'"
          :style="percent !== null ? { width: `${percent}%` } : {}"
        />
      </div>
      <span class="w-24 shrink-0 text-right text-xs tabular-nums muted">
        {{ job.status === 'queued' ? t('jobsPage.row.waiting') : percent !== null ? `${percent}%` : '' }}
      </span>
    </div>
    <p v-if="active && job.progress_note" class="mt-1 truncate text-xs muted">{{ job.progress_note }}</p>

    <div v-if="errorText" class="mt-2 rounded-button px-3 py-2 text-sm" :class="problemTone">
      <p>{{ errorText }}</p>
      <p v-if="job.status === 'interrupted'" class="mt-1 text-xs opacity-80">{{ t('jobsPage.row.interruptedHint') }}</p>
      <details v-if="showDetails" class="mt-1 text-xs">
        <summary class="cursor-pointer select-none opacity-80">{{ t('jobsPage.row.details') }}</summary>
        <pre class="mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-words font-mono">{{ job.error }}</pre>
      </details>
    </div>
    <p v-else-if="job.status === 'interrupted'" class="mt-2 rounded-button px-3 py-2 text-sm" :class="problemTone">
      {{ t('jobsPage.row.interruptedHint') }}
    </p>
  </li>
</template>

<script setup>
import { formatDateTime, formatDuration } from '~/utils/format.js'
import { jobKindLabel, jobRefRoute } from '~/utils/jobRefs.js'
import { KNOWN_GROUPS, STATUS_TONE, hasErrorDetails, isActive, jobErrorText, jobSeconds, progressPercent } from '~/utils/jobsView.js'

const props = defineProps({
  job: { type: Object, required: true },
  now: { type: Number, default: () => Date.now() },
  busy: { type: Boolean, default: false },
})
defineEmits(['cancel', 'retry'])

const { t, te, locale } = useI18n()
const router = useRouter()

const active = computed(() => isActive(props.job))
const name = computed(() => props.job.title || jobKindLabel(props.job.kind, t))
const groupLabel = computed(() => (KNOWN_GROUPS.includes(props.job.group_name)
  ? t(`jobsPage.groups.${props.job.group_name}`)
  : props.job.group_name))
const tone = computed(() => STATUS_TONE[props.job.status] || STATUS_TONE.queued)
const problemTone = computed(() => (props.job.status === 'error'
  ? 'bg-rose-50 text-rose-800 dark:bg-rose-500/10 dark:text-rose-200'
  : 'bg-amber-50 text-amber-800 dark:bg-amber-500/10 dark:text-amber-200'))
const seconds = computed(() => jobSeconds(props.job, props.now))
const percent = computed(() => progressPercent(props.job))
const errorText = computed(() => (['error', 'interrupted'].includes(props.job.status) ? jobErrorText(props.job, t, te) : ''))
const showDetails = computed(() => hasErrorDetails(props.job, errorText.value))

const link = computed(() => {
  const target = jobRefRoute(props.job)
  if (!target) return null
  try {
    const resolved = router.resolve(target)
    return resolved.matched.length && resolved.name !== 'all' ? target : null
  } catch {
    return null
  }
})
</script>
