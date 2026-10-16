<template>
  <!--
    A message of a kind the chat itself does not draw (an avatar card, ideas,
    a text-on-picture result…). Other modules give the component: registered
    with chatRegisterKind(), or a file in components/chat/kinds/ named after the
    kind ('avatar.card' -> AvatarCard.vue). Without one, the text and status show.
  -->
  <component :is="custom" v-if="custom" :message="message" :room="room" />
  <div v-else class="flex justify-start">
    <div class="max-w-2xl space-y-1.5 rounded-card border border-slate-200 bg-white px-4 py-3 text-sm dark:border-slate-700 dark:bg-slate-900">
      <p v-if="message.text" class="whitespace-pre-wrap break-words">{{ message.text }}</p>
      <p v-else class="muted">{{ t('chat.kind.unknown', { kind: message.kind || message.type }) }}</p>
      <div v-if="busy" class="flex items-center gap-2 text-xs muted"><Spinner :size="14" />{{ t('common.loading') }}</div>
      <ChatErrorLine v-if="message.status === 'error'" :item="message" :spend-link="message.spend_link" />
      <p class="text-xs muted"><time :datetime="message.created_at">{{ chatTime(message.created_at, locale) }}</time></p>
    </div>
  </div>
</template>

<script>
import { defineAsyncComponent } from 'vue'
import { chatKindFileName } from '~/utils/chatView.js'

// Files of other modules, loaded only when a message of their kind shows up.
const files = import.meta.glob('./kinds/*.vue')
const cache = new Map()

function kindComponent(kind) {
  if (!kind) return null
  if (cache.has(kind)) return cache.get(kind)
  const loader = files[`./kinds/${chatKindFileName(kind)}.vue`]
  const component = loader ? defineAsyncComponent(loader) : null
  cache.set(kind, component)
  return component
}
</script>

<script setup>
import { chatKindComponent, chatMessageBusy, chatTime } from '~/utils/chatView.js'

const props = defineProps({
  message: { type: Object, required: true },
  room: { type: Object, required: true },
})
const { t, locale } = useI18n()

const custom = computed(() => chatKindComponent(props.message.kind) || kindComponent(props.message.kind))
const busy = computed(() => chatMessageBusy(props.message))
</script>
