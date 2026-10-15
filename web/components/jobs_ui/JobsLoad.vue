<template>
  <section class="card p-4">
    <div class="flex items-center gap-2">
      <h2 class="flex-1 text-sm font-semibold">{{ t('jobsPage.load.title') }}</h2>
      <button type="button" class="btn-ghost btn-sm" @click="$emit('settings')">
        <AppIcon name="settings" :size="14" />{{ t('jobsPage.load.change') }}
      </button>
    </div>
    <p class="mt-1 text-xs muted">{{ t('jobsPage.load.hint') }}</p>
    <ul class="mt-3 flex flex-wrap gap-2">
      <li
        v-for="g in shown"
        :key="g.group"
        class="rounded-button border px-3 py-1.5 text-xs"
        :class="g.running || g.queued ? 'border-primary/40 bg-primary/5' : 'border-slate-200 dark:border-slate-700'"
      >
        <span class="font-medium">{{ groupLabel(g.group) }}</span>
        <span class="ml-1 tabular-nums">{{ t('jobsPage.load.running', { running: g.running, limit: g.limit }) }}</span>
        <span v-if="g.queued" class="ml-1 muted">· {{ t('jobsPage.load.queued', { n: g.queued }, g.queued) }}</span>
      </li>
    </ul>
  </section>
</template>

<script setup>
import { KNOWN_GROUPS } from '~/utils/jobsView.js'

const props = defineProps({
  groups: { type: Array, default: () => [] },
})
defineEmits(['settings'])

const { t } = useI18n()

// "default" is a catch-all; show it only when something is in it.
const shown = computed(() => props.groups.filter((g) => g.group !== 'default' || g.running || g.queued))
const groupLabel = (name) => (KNOWN_GROUPS.includes(name) ? t(`jobsPage.groups.${name}`) : name)
</script>
