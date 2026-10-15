<template>
  <section v-if="entries.length" class="card">
    <header class="flex items-center gap-3 border-b border-slate-200 px-4 py-2.5 dark:border-slate-700">
      <h2 class="min-w-0 flex-1 text-sm font-semibold">
        {{ active ? t('media.upload.queueBusy', { n: active }, active) : t('media.upload.queueDone') }}
      </h2>
      <button v-if="finished" type="button" class="btn-ghost btn-sm" @click="$emit('clear')">
        <AppIcon name="close" :size="14" />{{ t('media.upload.clear') }}
      </button>
    </header>
    <ul class="max-h-64 divide-y divide-slate-200 overflow-y-auto dark:divide-slate-700">
      <li v-for="e in entries" :key="e.key" class="flex items-center gap-3 px-4 py-2">
        <span class="shrink-0" :class="iconTone(e)">
          <Spinner v-if="e.status === 'uploading'" :size="16" />
          <AppIcon v-else :name="iconName(e)" :size="16" />
        </span>
        <div class="min-w-0 flex-1">
          <p class="flex gap-2 text-sm">
            <span class="min-w-0 truncate" :title="e.name">{{ e.name }}</span>
            <span class="shrink-0 tabular-nums muted">{{ formatBytes(e.size) }}</span>
          </p>
          <div v-if="e.status === 'uploading'" class="mt-1 flex items-center gap-2">
            <div class="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
              <div class="h-full bg-primary transition-all" :style="{ width: `${Math.round((e.progress || 0) * 100)}%` }" />
            </div>
            <span class="w-10 text-right text-xs tabular-nums muted">{{ Math.round((e.progress || 0) * 100) }}%</span>
          </div>
          <p v-else-if="e.status === 'error'" class="text-xs text-rose-700 dark:text-rose-300">{{ e.error }}</p>
          <p v-else class="text-xs muted">{{ t(`media.upload.status.${e.status}`) }}</p>
        </div>
        <button
          v-if="e.status === 'waiting' || e.status === 'uploading'"
          type="button"
          class="btn-ghost btn-sm shrink-0"
          @click="$emit('cancel', e.key)"
        >
          {{ t('common.cancel') }}
        </button>
        <button
          v-else
          type="button"
          class="btn-ghost shrink-0 p-1"
          :aria-label="t('common.close')"
          @click="$emit('dismiss', e.key)"
        >
          <AppIcon name="close" :size="14" />
        </button>
      </li>
    </ul>
  </section>
</template>

<script setup>
import { formatBytes } from '~/utils/format.js'

const props = defineProps({
  // [{ key, name, size, progress: 0..1, status: waiting|uploading|done|error|cancelled, error }]
  entries: { type: Array, default: () => [] },
})
defineEmits(['cancel', 'dismiss', 'clear'])
const { t } = useI18n()

const active = computed(() => props.entries.filter((e) => e.status === 'waiting' || e.status === 'uploading').length)
const finished = computed(() => props.entries.some((e) => e.status !== 'waiting' && e.status !== 'uploading'))

const iconName = (e) => ({ done: 'check', error: 'alert', cancelled: 'close' }[e.status] || 'upload')
const iconTone = (e) => ({
  done: 'text-emerald-600 dark:text-emerald-400',
  error: 'text-rose-600 dark:text-rose-400',
}[e.status] || 'text-slate-400')
</script>
