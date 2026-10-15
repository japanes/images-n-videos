<template>
  <div class="space-y-2">
    <label
      class="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-card border-2 border-dashed px-4 py-8 text-center transition-colors"
      :class="dragging
        ? 'border-primary bg-primary/5'
        : 'border-slate-300 hover:border-primary dark:border-slate-600'"
      @dragenter.prevent="dragging = true"
      @dragover.prevent="dragging = true"
      @dragleave.prevent="dragging = false"
      @drop.prevent="onDrop"
    >
      <Spinner v-if="busy" :size="24" />
      <AppIcon v-else name="key" :size="28" class="text-slate-400" />
      <span class="text-sm font-medium">{{ busy ? t('connection.upload.busy') : t('connection.upload.drop') }}</span>
      <span v-if="!busy" class="text-xs muted">{{ t('connection.upload.or') }}</span>
      <span v-if="!busy" class="btn-secondary btn-sm pointer-events-none">
        <AppIcon name="upload" :size="14" />{{ t('connection.upload.choose') }}
      </span>
      <input
        ref="input"
        type="file"
        accept=".json,application/json"
        class="sr-only"
        :disabled="busy"
        @change="onPick"
      >
    </label>
    <p v-if="error" role="alert" class="flex gap-2 text-sm text-rose-700 dark:text-rose-300">
      <AppIcon name="alert" :size="16" class="mt-0.5 shrink-0" />
      <ConnectionRichText :text="error" />
    </p>
    <p class="text-xs muted">{{ t('connection.upload.hint') }}</p>
  </div>
</template>

<script setup>
// Drop zone for the service-account JSON key. Emits the File; the parent uploads it.
const props = defineProps({
  busy: { type: Boolean, default: false },
  error: { type: String, default: '' },
})
const emit = defineEmits(['file'])

const { t } = useI18n()
const dragging = ref(false)
const input = ref(null)

function onDrop(e) {
  dragging.value = false
  if (props.busy) return
  const file = e.dataTransfer?.files?.[0]
  if (file) emit('file', file)
}

function onPick(e) {
  const file = e.target.files?.[0]
  if (file) emit('file', file)
  if (input.value) input.value.value = '' // the same file can be picked again after a fix
}
</script>
