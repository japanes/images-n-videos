<template>
  <div class="flex h-dvh overflow-hidden">
    <!-- Left menu: fixed on wide screens, a drawer on narrow ones. -->
    <div class="hidden lg:block"><AppSidebar /></div>
    <Transition name="vf-fade">
      <div v-if="drawer" class="fixed inset-0 z-40 bg-slate-950/50 lg:hidden" @click="drawer = false" />
    </Transition>
    <Transition name="vf-slide">
      <div v-if="drawer" class="fixed inset-y-0 left-0 z-50 lg:hidden">
        <AppSidebar @navigate="drawer = false" @close="drawer = false" />
      </div>
    </Transition>

    <div class="flex min-w-0 flex-1 flex-col">
      <header class="flex items-center gap-2 border-b border-slate-200 px-3 py-2 dark:border-slate-800 lg:hidden">
        <button type="button" class="btn-ghost p-1.5" :aria-label="t('common.menu')" @click="drawer = true">
          <AppIcon name="menu" />
        </button>
        <span class="truncate text-sm font-semibold">Vertex AI Factory</span>
      </header>
      <ShellNotices />
      <main class="min-h-0 flex-1 overflow-y-auto">
        <slot />
      </main>
    </div>

    <ConfirmDialog />
    <ToastHost />
  </div>
</template>

<script setup>
const { t } = useI18n()
const drawer = ref(false)
</script>
