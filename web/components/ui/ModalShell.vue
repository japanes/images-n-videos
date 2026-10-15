<template>
  <Teleport to="body">
    <Transition name="vf-fade">
      <div
        v-if="open"
        class="fixed inset-0 z-[100] flex items-end justify-center bg-slate-950/60 sm:items-center sm:px-4"
        role="dialog"
        aria-modal="true"
        @click.self="closeOnOverlay && $emit('close')"
        @keydown.escape="$emit('close')"
      >
        <div
          ref="panel"
          tabindex="-1"
          class="flex max-h-[92vh] w-full flex-col overflow-hidden rounded-t-modal border border-slate-200 bg-white shadow-modal outline-none dark:border-slate-700 dark:bg-slate-800 sm:rounded-modal"
          :class="widthClass"
        >
          <header v-if="title || $slots.header" class="flex items-center gap-3 border-b border-slate-200 px-5 py-3 dark:border-slate-700">
            <slot name="header"><h2 class="min-w-0 flex-1 truncate text-base font-semibold">{{ title }}</h2></slot>
            <button type="button" class="btn-ghost -mr-2 p-1.5" :aria-label="t('common.close')" @click="$emit('close')">
              <AppIcon name="close" />
            </button>
          </header>
          <div class="min-h-0 flex-1 overflow-y-auto" :class="bodyClass"><slot /></div>
          <footer v-if="$slots.footer" class="flex flex-wrap items-center justify-end gap-2 border-t border-slate-200 px-5 py-3 dark:border-slate-700">
            <slot name="footer" />
          </footer>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
const props = defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, default: '' },
  size: { type: String, default: 'md' }, // sm | md | lg | xl | full
  bodyClass: { type: String, default: 'p-5' },
  closeOnOverlay: { type: Boolean, default: true },
})
defineEmits(['close'])
const { t } = useI18n()

const widthClass = computed(() => ({
  sm: 'sm:max-w-sm',
  md: 'sm:max-w-lg',
  lg: 'sm:max-w-3xl',
  xl: 'sm:max-w-5xl',
  full: 'sm:max-w-[min(96vw,1600px)] sm:h-[92vh]',
}[props.size] || 'sm:max-w-lg'))

const panel = ref(null)
watch(() => props.open, (v) => { if (v) nextTick(() => panel.value?.focus()) })
</script>
