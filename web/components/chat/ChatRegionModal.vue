<template>
  <!--
    «Mark an area» of the picture being answered: click an object found in the
    viewer, or drag a rectangle. Only that part is changed by the edit.
  -->
  <ModalShell :open="open" :title="t('chat.region.title')" size="lg" @close="$emit('close')">
    <p class="mb-3 text-sm muted">{{ objects.length ? t('chat.region.textObjects') : t('chat.region.text') }}</p>
    <div class="flex justify-center">
      <StudioRegionPicker v-if="src" v-model="value" :src="src" :objects="objects" />
    </div>
    <template #footer>
      <button type="button" class="btn-ghost mr-auto" :disabled="!value" @click="value = null">{{ t('chat.region.clear') }}</button>
      <button type="button" class="btn-secondary" @click="$emit('close')">{{ t('common.cancel') }}</button>
      <button type="button" class="btn-primary" @click="apply">{{ t('chat.region.apply') }}</button>
    </template>
  </ModalShell>
</template>

<script setup>
const props = defineProps({
  open: { type: Boolean, default: false },
  item: { type: Object, default: null }, // the picture answered: { work_id, frame_id, file_id, file }
  modelValue: { type: Object, default: null }, // null | { id } | { label, box }
})
const emit = defineEmits(['update:modelValue', 'close'])
const { t } = useI18n()

const value = ref(null)
const studio = useStudioWork(() => (props.open ? props.item?.work_id : null))
const src = computed(() => props.item?.file?.url || '')

// Objects found earlier in the viewer, when they belong to this very picture.
const objects = computed(() => {
  const frame = (studio.work.value?.frames || []).find((f) => f.id === props.item?.frame_id)
  if (!frame || Number(frame.file_id) !== Number(props.item?.file_id)) return []
  return frame.objects?.items || []
})

watch(() => props.open, (open) => {
  if (!open) return
  value.value = props.modelValue // the work loads by itself: its id appears when the modal opens
}, { immediate: true })

function apply() {
  emit('update:modelValue', value.value)
  emit('close')
}
</script>
