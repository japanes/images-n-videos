<template>
  <section class="card px-4 py-3 text-sm">
    <div v-if="!stats" class="flex items-center gap-2 muted">
      <Spinner v-if="!error" :size="14" />{{ error || t('common.loading') }}
    </div>
    <template v-else>
      <div class="flex flex-wrap items-center gap-x-5 gap-y-1">
        <span class="font-medium">{{ t('media.storage.title') }}</span>
        <span v-for="kind in kinds" :key="kind" class="muted">
          {{ t(`media.kinds.${kind}`) }}: <span class="tabular-nums text-slate-700 dark:text-slate-200">{{ count(kind) }}</span>
          · <span class="tabular-nums">{{ formatBytes(bytes(kind)) }}</span>
        </span>
      </div>
      <div class="mt-1 flex flex-wrap gap-x-5 gap-y-1 text-xs muted">
        <span>{{ t('media.storage.total', { size: formatBytes(stats.total_bytes) }) }}</span>
        <span :title="t('media.storage.serviceHint')">{{ t('media.storage.service', { size: formatBytes(stats.service_bytes + stats.cache_bytes) }) }}</span>
        <span v-if="stats.disk?.total" :class="lowDisk && 'font-medium text-amber-700 dark:text-amber-300'">
          {{ t('media.storage.free', { free: formatBytes(stats.disk.free), total: formatBytes(stats.disk.total) }) }}
        </span>
      </div>
      <p v-if="lowDisk" class="mt-2 flex gap-2 text-xs text-amber-800 dark:text-amber-200">
        <AppIcon name="alert" :size="14" />{{ t('media.storage.lowDisk') }}
      </p>
    </template>
  </section>
</template>

<script setup>
import { formatBytes } from '~/utils/format.js'

// Below this much free space a long video may not fit any more.
const LOW_DISK_BYTES = 5 * 1024 ** 3

const props = defineProps({
  stats: { type: Object, default: null },
  error: { type: String, default: '' },
})
const { t } = useI18n()

const kinds = ['image', 'video', 'audio']
const count = (kind) => props.stats?.by_kind?.[kind]?.count || 0
const bytes = (kind) => props.stats?.by_kind?.[kind]?.bytes || 0
const lowDisk = computed(() => {
  const free = props.stats?.disk?.free
  return typeof free === 'number' && props.stats.disk.total > 0 && free < LOW_DISK_BYTES
})
</script>
