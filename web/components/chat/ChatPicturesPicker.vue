<template>
  <!-- Pictures already made or sent in this chat, newest first; pick one or several to attach. -->
  <ModalShell :open="open" :title="t('chat.picker.title')" size="lg" @close="$emit('close')">
    <div v-if="loading" class="flex justify-center py-10"><Spinner /></div>
    <EmptyState v-else-if="!items.length" icon="image" :title="t('chat.picker.empty')" :text="t('chat.picker.emptyText')" />
    <div v-else class="grid grid-cols-3 gap-2 sm:grid-cols-5">
      <button
        v-for="item in items"
        :key="item.id"
        type="button"
        class="relative aspect-square overflow-hidden rounded-button border"
        :class="chosen.includes(item.id) ? 'border-primary ring-2 ring-primary' : 'border-slate-200 dark:border-slate-600'"
        @click="choose(item)"
      >
        <img :src="chatFileThumb(item)" alt="" loading="lazy" class="h-full w-full object-cover">
        <span
          v-if="chosen.includes(item.id)"
          class="absolute right-1 top-1 inline-flex h-5 w-5 items-center justify-center rounded-full bg-primary text-white"
        ><AppIcon name="check" :size="12" /></span>
      </button>
    </div>
    <template #footer>
      <span class="mr-auto text-sm muted">{{ t('chat.picker.chosen', { n: chosen.length, max }) }}</span>
      <button type="button" class="btn-secondary" @click="$emit('close')">{{ t('common.cancel') }}</button>
      <button type="button" class="btn-primary" :disabled="!chosen.length" @click="done">{{ t('chat.picker.take') }}</button>
    </template>
  </ModalShell>
</template>

<script setup>
import { chatFileThumb } from '~/utils/chatView.js'

const props = defineProps({
  open: { type: Boolean, default: false },
  room: { type: Object, required: true },
  max: { type: Number, default: 10 }, // how many more pictures the composer takes
})
const emit = defineEmits(['pick', 'close'])
const { t } = useI18n()

const items = ref([])
const chosen = ref([])
const loading = ref(false)

watch(() => props.open, async (open) => {
  if (!open) return
  chosen.value = []
  loading.value = true
  items.value = (await props.room.pictures()) || []
  loading.value = false
}, { immediate: true })

function choose(item) {
  if (chosen.value.includes(item.id)) chosen.value = chosen.value.filter((id) => id !== item.id)
  else if (chosen.value.length < props.max) chosen.value = [...chosen.value, item.id]
}

function done() {
  emit('pick', items.value.filter((i) => chosen.value.includes(i.id)))
}
</script>
