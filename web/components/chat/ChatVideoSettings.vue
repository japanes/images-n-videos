<template>
  <!--
    Video settings of the chat, for the side panel: the same form as the video
    workspace. Only the fields that changed are sent; the server brings the rest
    inside what the chosen model allows.
  -->
  <div v-if="room.chat" id="chat-set-video" class="space-y-3">
    <div v-if="!catalog.models.value.length" class="flex justify-center py-6"><Spinner /></div>
    <VideoSettingsForm
      v-else
      :model-value="value"
      :models="catalog.models.value"
      :moves="catalog.moves.value"
      :categories="catalog.categories.value"
      :disabled="room.isPending('settings')"
      @update:model-value="save"
    />
    <p class="muted text-xs">{{ t('chat.settings.videoHint') }}</p>
  </div>
</template>

<script setup>
const props = defineProps({
  room: { type: Object, required: true }, // reactive(useChatRoom(…))
})
const { t } = useI18n()
const catalog = useVideoCatalog()

const KEYS = ['model_id', 'resolution', 'duration', 'aspect', 'camera_move', 'sound']
const value = computed(() => ({ ...(props.room.chat?.video_settings || {}) }))

function save(next) {
  const changed = {}
  for (const key of KEYS) if (next?.[key] !== value.value[key]) changed[key] = next[key]
  if (Object.keys(changed).length) props.room.patchVideo(changed)
}
</script>
