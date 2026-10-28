<template>
  <aside class="flex h-full w-72 flex-col border-r border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950 lg:w-64">
    <div class="flex items-center gap-2 px-4 py-3">
      <NuxtLink to="/" class="flex min-w-0 items-center gap-2" @click="$emit('navigate')">
        <img src="/favicon.svg" alt="" class="h-7 w-7" />
        <span class="truncate text-sm font-semibold">Vertex AI Factory</span>
      </NuxtLink>
      <button type="button" class="btn-ghost ml-auto p-1.5 lg:hidden" :aria-label="t('common.close')" @click="$emit('close')">
        <AppIcon name="close" />
      </button>
    </div>

    <!-- Chats: module 15 fills this (new chat button, search, list). -->
    <SidebarChats class="min-h-0 flex-1" @navigate="$emit('navigate')" />

    <nav class="border-t border-slate-200 px-2 py-2 dark:border-slate-800">
      <template v-for="section in sections" :key="section.key">
        <NuxtLink
          v-for="item in section.items"
          :key="item.to"
          :to="item.to"
          class="flex items-center gap-2.5 rounded-button px-2.5 py-1.5 text-sm text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
          active-class="!bg-primary/10 !text-primary"
          @click="$emit('navigate')"
        >
          <AppIcon :name="item.icon" :size="16" />
          <span class="truncate">{{ t(item.labelKey) }}</span>
        </NuxtLink>
        <div class="my-1.5 border-t border-slate-100 last:hidden dark:border-slate-800/70" />
      </template>
    </nav>

    <div class="flex items-center gap-1 border-t border-slate-200 px-3 py-2 dark:border-slate-800">
      <JobsIndicator />
      <div class="ml-auto flex items-center gap-1">
        <LanguageSwitcher />
        <ThemeToggle />
      </div>
    </div>
  </aside>
</template>

<script setup>
import { NAV_SECTIONS } from '~/utils/nav.js'

defineEmits(['navigate', 'close'])
const { t } = useI18n()
const router = useRouter()

const exists = (path) => router.resolve(path).matched.length > 0 && router.resolve(path).name !== 'all'
const sections = computed(() => NAV_SECTIONS
  .map((s) => ({ ...s, items: s.items.filter((i) => exists(i.to)) }))
  .filter((s) => s.items.length))
</script>
