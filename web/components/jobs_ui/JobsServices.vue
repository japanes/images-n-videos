<template>
  <section class="card p-4">
    <div class="flex items-center gap-2">
      <h2 class="flex-1 text-sm font-semibold">{{ t('jobsPage.services.title') }}</h2>
      <span v-if="checkedAt" class="text-xs muted">{{ t('jobsPage.services.checkedAt', { time: formatDateTime(checkedAt, locale) }) }}</span>
      <button type="button" class="btn-ghost btn-sm" :disabled="loading" @click="$emit('check')">
        <Spinner v-if="loading" :size="12" />
        <AppIcon v-else name="refresh" :size="14" />
        {{ t('jobsPage.services.check') }}
      </button>
    </div>
    <p v-if="error" class="mt-2 text-sm text-rose-700 dark:text-rose-300">{{ error }}</p>
    <ul class="mt-3 grid gap-2 sm:grid-cols-3">
      <li v-for="s in services" :key="s.name" class="rounded-button border border-slate-200 px-3 py-2 dark:border-slate-700">
        <div class="flex items-center gap-2">
          <span class="h-2 w-2 shrink-0 rounded-full" :class="DOT[s.state] || DOT.unreachable" />
          <span class="min-w-0 flex-1 truncate text-sm font-medium">{{ serviceName(s.name) }}</span>
          <span class="text-xs muted">{{ t(`jobsPage.services.state.${s.state}`) }}</span>
        </div>
        <p class="mt-1 flex flex-wrap gap-x-3 text-xs muted">
          <span v-if="s.version">{{ t('jobsPage.services.version', { v: s.version }) }}</span>
          <span v-for="line in detailLines(s)" :key="line">{{ line }}</span>
        </p>
        <p v-if="s.state !== 'ok'" class="mt-1 text-xs text-amber-800 dark:text-amber-200">
          {{ problemText(s) }}
        </p>
      </li>
    </ul>
  </section>
</template>

<script setup>
import { formatDateTime } from '~/utils/format.js'

defineProps({
  services: { type: Array, default: () => [] },
  checkedAt: { type: String, default: '' },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
})
defineEmits(['check'])

const { t, te, locale } = useI18n()

const DOT = {
  ok: 'bg-emerald-500',
  problem: 'bg-amber-500',
  unreachable: 'bg-rose-500',
}
const KNOWN = ['render', 'stt', 'updater']

const serviceName = (name) => (KNOWN.includes(name) ? t(`jobsPage.services.names.${name}`) : name)

function detailLines(s) {
  const d = s.details || {}
  const out = []
  if (typeof d.ffmpeg === 'string' && d.ffmpeg) out.push(t('jobsPage.services.ffmpeg', { v: d.ffmpeg }))
  if (d.queue && typeof d.queue === 'object') {
    out.push(t('jobsPage.services.queue', { running: d.queue.running ?? 0, queued: d.queue.queued ?? 0 }))
  }
  if (d.busy === true) out.push(t('jobsPage.services.busy'))
  return out
}

function problemText(s) {
  if (s.state === 'unreachable') {
    const key = `errors.${s.error_code}`
    return s.error_code && te(key) ? t(key) : t('jobsPage.services.notResponding')
  }
  return s.message || t('jobsPage.services.problem')
}
</script>
