<template>
  <nav class="flex flex-wrap items-center gap-1 border-b border-slate-200 dark:border-slate-700" role="tablist">
    <NuxtLink
      v-for="tab in SETTINGS_TABS"
      :key="tab.key"
      :to="tab.to"
      role="tab"
      :aria-selected="active === tab.key"
      class="-mb-px flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm"
      :class="active === tab.key ? 'border-primary font-medium text-primary' : 'border-transparent muted hover:text-slate-700 dark:hover:text-slate-200'"
    >
      <AppIcon :name="tab.icon" :size="16" />{{ t(`settings.tabs.${tab.key}`) }}
    </NuxtLink>
  </nav>
</template>

<script setup>
import { SETTINGS_TABS, settingsTabKey } from '~/utils/nav.js'

const { t } = useI18n()
const route = useRoute()
const active = computed(() => settingsTabKey(route.path))
</script>
