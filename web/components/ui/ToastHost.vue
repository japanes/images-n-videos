<template>
  <Teleport to="body">
    <div class="pointer-events-none fixed bottom-4 right-4 z-[120] flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2" aria-live="polite">
      <TransitionGroup name="vf-fade">
        <div
          v-for="item in items"
          :key="item.id"
          class="pointer-events-auto flex items-start gap-2 rounded-card border px-3 py-2.5 text-sm shadow-card-hover"
          :class="tone(item.kind)"
          :role="item.kind === 'error' ? 'alert' : 'status'"
        >
          <AppIcon :name="item.kind === 'error' ? 'alert' : item.kind === 'success' ? 'check' : 'info'" :size="16" class="mt-0.5" />
          <p class="min-w-0 flex-1 whitespace-pre-line break-words">{{ item.text }}</p>
          <button type="button" class="opacity-60 hover:opacity-100" :aria-label="t('common.close')" @click="dismiss(item.id)">
            <AppIcon name="close" :size="14" />
          </button>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<script setup>
const { t } = useI18n()
const { items, dismiss } = useToast()

const tone = (kind) => ({
  error: 'border-rose-200 bg-rose-50 text-rose-800 dark:border-rose-500/30 dark:bg-rose-950 dark:text-rose-200',
  success: 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-500/30 dark:bg-emerald-950 dark:text-emerald-200',
}[kind] || 'border-slate-200 bg-white text-slate-800 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100')
</script>
