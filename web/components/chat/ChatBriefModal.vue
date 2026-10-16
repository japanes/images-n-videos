<template>
  <!--
    «Write it for me» in video mode. The composer's text, pictures and the
    chat's video settings go into a draft video (free); here the model writes
    the brief (paid, the price is on the button) and a storyboard can be drawn.
    The brief then goes back into the composer: what is sent is what is seen.
  -->
  <ModalShell :open="open" :title="t('chat.brief.title')" size="lg" @close="close">
    <div v-if="!run" class="flex justify-center py-10"><Spinner /></div>
    <div v-else class="space-y-4">
      <p class="text-sm muted">{{ t('chat.brief.text') }}</p>
      <VideoBriefWriter :video="video" />
      <div class="flex flex-wrap items-center gap-2 rounded-card border border-slate-200 p-3 text-sm dark:border-slate-600">
        <span class="min-w-0 flex-1 muted">{{ hasStoryboard ? t('chat.brief.storyboardReady') : t('chat.brief.storyboardText') }}</span>
        <button type="button" class="btn-secondary btn-sm" @click="storyboard = true">
          <AppIcon name="image" :size="14" />{{ t('chat.brief.storyboard') }}
        </button>
      </div>
    </div>
    <template #footer>
      <button type="button" class="btn-secondary" @click="close">{{ t('common.close') }}</button>
      <button type="button" class="btn-primary" :disabled="!brief" @click="use">
        <AppIcon name="edit" :size="16" />{{ t('chat.brief.use') }}
      </button>
    </template>
  </ModalShell>
  <VideoStoryboardModal v-if="run" :open="storyboard" :video="video" @close="storyboard = false" />
</template>

<script setup>
const props = defineProps({
  open: { type: Boolean, default: false },
  room: { type: Object, required: true },
})
const emit = defineEmits(['use', 'close'])
const { t } = useI18n()

const runId = ref(null)
const storyboard = ref(false)
const video = useVideoRun(() => runId.value)
const run = computed(() => (runId.value && video.run.value?.id === runId.value ? video.run.value : null))
const brief = computed(() => String(run.value?.brief || '').trim())
const hasStoryboard = computed(() => Boolean(run.value?.storyboard?.file_id || run.value?.storyboard?.file))

watch(() => props.open, async (open) => {
  if (!open) return
  const res = await props.room.videoDraft()
  if (!res?.run_id) { emit('close'); return }
  if (res.run_id === runId.value) video.load()
  else runId.value = res.run_id
}, { immediate: true })

async function close() {
  await video.flush()
  emit('close')
}

async function use() {
  await video.flush()
  emit('use', brief.value)
}
</script>
