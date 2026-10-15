<template>
  <section class="card p-4">
    <div class="flex items-center gap-2">
      <h2 class="flex-1 text-sm font-semibold">{{ t('jobsPage.upkeep.title') }}</h2>
      <button type="button" class="btn-ghost btn-sm" @click="$emit('settings')">
        <AppIcon name="settings" :size="14" />{{ t('jobsPage.load.change') }}
      </button>
    </div>
    <ul class="mt-2 space-y-1.5 text-sm">
      <li class="flex gap-2">
        <AppIcon name="archive" :size="16" class="mt-0.5 muted" />
        <span v-if="!settings['jobs.backup_daily']">{{ t('jobsPage.upkeep.backupOff') }}</span>
        <span v-else-if="backups.last">
          {{ t('jobsPage.upkeep.backupLast', { time: formatDateTime(backups.last.at, locale), size: formatBytes(backups.last.size) }) }}
          <span class="muted">{{ t('jobsPage.upkeep.backupCount', { n: backups.count, keep: settings['jobs.backup_keep'] }) }}</span>
        </span>
        <span v-else>{{ t('jobsPage.upkeep.backupNone') }}</span>
      </li>
      <li class="flex gap-2">
        <AppIcon name="stop" :size="16" class="mt-0.5 muted" />
        <span>{{ stuckMinutes > 0 ? t('jobsPage.upkeep.stuck', { n: stuckMinutes }, stuckMinutes) : t('jobsPage.upkeep.stuckOff') }}</span>
      </li>
      <li class="flex gap-2">
        <AppIcon name="trash" :size="16" class="mt-0.5 muted" />
        <span>{{ keepDays > 0 ? t('jobsPage.upkeep.keep', { n: keepDays }, keepDays) : t('jobsPage.upkeep.keepForever') }}</span>
      </li>
    </ul>
    <p class="mt-2 text-xs muted">{{ t('jobsPage.upkeep.where') }}</p>
  </section>
</template>

<script setup>
import { formatBytes, formatDateTime } from '~/utils/format.js'

const props = defineProps({
  settings: { type: Object, default: () => ({}) },
  backups: { type: Object, default: () => ({ count: 0, last: null }) },
})
defineEmits(['settings'])

const { t, locale } = useI18n()
const stuckMinutes = computed(() => Number(props.settings['jobs.stuck_minutes']) || 0)
const keepDays = computed(() => Number(props.settings['jobs.keep_days']) || 0)
</script>
