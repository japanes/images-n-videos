<template>
  <!-- A short row of pictures (references, attachments) with remove and add. -->
  <div>
    <div class="flex flex-wrap gap-2">
      <div
        v-for="id in ids"
        :key="id"
        class="group relative h-16 w-16 overflow-hidden rounded-button border border-slate-200 dark:border-slate-600"
      >
        <img :src="studioFileThumb(id, 160)" alt="" loading="lazy" class="h-full w-full object-cover">
        <button
          type="button"
          class="absolute right-0.5 top-0.5 inline-flex h-5 w-5 items-center justify-center rounded bg-slate-900/70 text-white opacity-0 transition-opacity hover:bg-rose-600 focus:opacity-100 group-hover:opacity-100"
          :disabled="disabled"
          :title="t('studio.pictures.remove')"
          :aria-label="t('studio.pictures.remove')"
          @click="remove(id)"
        >
          <AppIcon name="close" :size="12" />
        </button>
      </div>
      <button
        v-if="ids.length < max"
        type="button"
        class="inline-flex h-16 w-16 flex-col items-center justify-center gap-0.5 rounded-button border-2 border-dashed border-slate-300 text-xs hover:border-primary dark:border-slate-600"
        :disabled="disabled"
        :title="t('studio.pictures.add')"
        @click="picking = true"
      >
        <AppIcon name="plus" :size="16" />
        <span class="muted">{{ ids.length }}/{{ max }}</span>
      </button>
    </div>
    <StudioSourcePicker
      :open="picking"
      :title="pickerTitle"
      multiple
      :max="Math.max(1, max - ids.length)"
      @pick="add"
      @close="picking = false"
    />
  </div>
</template>

<script setup>
import { studioFileThumb } from '~/utils/studioView.js'

const props = defineProps({
  ids: { type: Array, default: () => [] },
  max: { type: Number, default: 14 },
  disabled: { type: Boolean, default: false },
  pickerTitle: { type: String, default: '' },
})
const emit = defineEmits(['update'])
const { t } = useI18n()
const picking = ref(false)

function remove(id) {
  emit('update', props.ids.filter((x) => x !== id))
}

function add(files) {
  picking.value = false
  const out = [...props.ids]
  for (const f of files || []) {
    if (f?.id && !out.includes(f.id) && out.length < props.max) out.push(f.id)
  }
  emit('update', out)
}
</script>
