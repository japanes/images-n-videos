<template>
  <!--
    The right panel of a chat: what the next requests are made with. Changes are
    saved at once; messages already sent keep the settings they were sent with.
  -->
  <div class="flex min-h-full flex-col">
    <div class="sticky top-0 z-10 flex items-center gap-2 border-b border-slate-200 bg-white px-4 py-3 dark:border-slate-800 dark:bg-slate-900">
      <h2 class="min-w-0 flex-1 truncate text-sm font-semibold">{{ t('chat.settings.title') }}</h2>
      <Spinner v-if="room.isPending('settings')" :size="14" />
      <button type="button" class="btn-ghost p-1.5" :aria-label="t('common.close')" @click="$emit('close')">
        <AppIcon name="close" :size="16" />
      </button>
    </div>

    <div class="space-y-6 p-4">
      <div id="chat-set-mode" class="space-y-1">
        <span class="label">{{ t('chat.settings.mode') }}</span>
        <div class="grid grid-cols-2 gap-1 rounded-button bg-slate-100 p-1 dark:bg-slate-800">
          <button
            v-for="m in CHAT_MODES"
            :key="m"
            type="button"
            class="flex items-center justify-center gap-1.5 rounded-button px-2 py-1.5 text-sm"
            :class="room.mode === m ? 'bg-white shadow-sm dark:bg-slate-700' : 'text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-100'"
            :aria-pressed="room.mode === m"
            :disabled="room.isPending('settings')"
            @click="room.setMode(m)"
          >
            <AppIcon :name="m === 'video' ? 'video' : 'image'" :size="16" />{{ t(`chat.modes.${m}`) }}
          </button>
        </div>
      </div>

      <ChatVideoSettings v-if="room.mode === 'video'" :room="room" />
      <ChatImageSettings v-else :room="room" />
    </div>
  </div>
</template>

<script setup>
import { CHAT_MODES } from '~/utils/chatView.js'

defineProps({
  room: { type: Object, required: true }, // reactive(useChatRoom(…))
})
defineEmits(['close'])
const { t } = useI18n()
</script>
