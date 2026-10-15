<template>
  <Teleport to="body">
    <Transition name="vf-fade">
      <!-- Escape stops here so a modal underneath does not close on the same key. -->
      <div
        v-if="state.open"
        class="fixed inset-0 z-[110] grid place-items-center bg-slate-950/60 px-4"
        role="dialog"
        aria-modal="true"
        @click.self="cancel"
        @keydown.escape.stop="cancel"
      >
        <div class="w-full max-w-md rounded-modal border border-slate-200 bg-white p-5 shadow-modal dark:border-slate-700 dark:bg-slate-800">
          <div class="flex items-start gap-3">
            <span
              class="grid h-10 w-10 shrink-0 place-items-center rounded-xl"
              :class="isDanger ? 'bg-rose-100 text-rose-600 dark:bg-rose-500/15 dark:text-rose-400' : 'bg-primary/10 text-primary'"
            >
              <AppIcon :name="isDanger ? 'alert' : 'info'" :size="20" />
            </span>
            <div class="min-w-0">
              <h3 class="text-base font-semibold text-slate-900 dark:text-white">{{ o.title || t('common.confirmTitle') }}</h3>
              <p v-if="o.message" class="mt-1 whitespace-pre-line text-sm muted">{{ o.message }}</p>
            </div>
          </div>
          <div class="mt-5 flex justify-end gap-2">
            <button v-if="!o.hideCancel" ref="cancelBtn" type="button" class="btn-ghost" @click="cancel">
              {{ o.cancelLabel || t('common.cancel') }}
            </button>
            <button ref="confirmBtn" type="button" :class="isDanger ? 'btn-danger' : 'btn-primary'" @click="accept">
              {{ o.confirmLabel || (o.hideCancel ? t('common.ok') : t('common.confirm')) }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
const { t } = useI18n()
const { state, accept, cancel } = useConfirm()

const o = computed(() => state.value.opts || {})
const isDanger = computed(() => o.value.tone === 'danger')

const cancelBtn = ref(null)
const confirmBtn = ref(null)
watch(() => state.value.open, (open) => {
  if (open) nextTick(() => (cancelBtn.value || confirmBtn.value)?.focus())
})
</script>
