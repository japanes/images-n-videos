<template>
  <!--
    The feed of one chat. It keeps to the bottom while the person is there
    (new messages and growing pictures pull it down), loads older messages when
    scrolled to the top without jumping, and can bring one message into view.
  -->
  <div ref="scroller" class="h-full overflow-y-auto overscroll-contain" @scroll.passive="onScroll">
    <div ref="content" class="mx-auto flex w-full max-w-4xl flex-col gap-5 px-3 py-4 sm:px-6">
      <div v-if="room.more" class="flex justify-center">
        <button type="button" class="btn-ghost btn-sm" :disabled="room.isPending('older')" @click="older">
          <Spinner v-if="room.isPending('older')" :size="14" />{{ t('chat.feed.older') }}
        </button>
      </div>

      <div v-if="room.loading && !room.messages.length" class="flex justify-center py-16"><Spinner :size="24" /></div>
      <ChatEmpty v-else-if="!room.messages.length" :mode="room.mode" @example="$emit('example', $event)" />

      <div
        v-for="m in room.messages"
        :id="`chat-msg-${m.id}`"
        :key="m.id"
        class="scroll-mt-16 rounded-card transition-shadow duration-500"
        :class="highlighted === m.id && 'ring-2 ring-primary/60 ring-offset-4 ring-offset-white dark:ring-offset-slate-950'"
      >
        <ChatRequestMessage
          v-if="m.type === 'request'"
          :message="m"
          :room="room"
          @restore="$emit('restore', $event)"
          @jump="focus"
        />
        <ChatImageResult
          v-else-if="m.type === 'result' && m.kind === 'image'"
          :message="m"
          :room="room"
          :request="byId.get(m.request_id) || null"
          @reply="$emit('reply', $event)"
          @viewer="$emit('viewer', $event)"
          @animate="$emit('animate', $event)"
          @reference="$emit('reference', $event)"
        />
        <ChatVideoResult
          v-else-if="m.type === 'result' && m.kind === 'video'"
          :message="m"
          :room="room"
          :request="byId.get(m.request_id) || null"
          @reply="$emit('reply', $event)"
        />
        <ChatKindMessage v-else :message="m" :room="room" />
      </div>
    </div>
  </div>
</template>

<script setup>
const props = defineProps({
  room: { type: Object, required: true }, // reactive(useChatRoom(…))
  focusMessage: { type: Number, default: null }, // `?message=` of the address
})
defineEmits(['reply', 'viewer', 'animate', 'reference', 'restore', 'example'])
const { t } = useI18n()

const STICK_PX = 160 // closer than this to the bottom counts as «at the bottom»
const TOP_PX = 200 // closer than this to the top loads older messages
const HIGHLIGHT_MS = 2500

const scroller = ref(null)
const content = ref(null)
const highlighted = ref(null)
let stick = !props.focusMessage
let highlightTimer = null

const byId = computed(() => new Map(props.room.messages.map((m) => [m.id, m])))

function atBottom() {
  const el = scroller.value
  return !el || el.scrollHeight - el.scrollTop - el.clientHeight < STICK_PX
}

function scrollToBottom(smooth = false) {
  stick = true
  const el = scroller.value
  if (el) el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' })
}

async function older() {
  const el = scroller.value
  if (!el) return
  const fromBottom = el.scrollHeight - el.scrollTop
  const loaded = await props.room.loadOlder()
  if (!loaded) return
  await nextTick()
  el.scrollTop = el.scrollHeight - fromBottom
}

function onScroll() {
  stick = atBottom()
  const el = scroller.value
  if (el && el.scrollTop < TOP_PX && props.room.more && !props.room.isPending('older') && !props.room.loading) older()
}

/** Bring a message into view and light it up for a moment (loads older pages when needed). */
async function focus(id) {
  if (!id) return
  stick = false
  const found = await props.room.loadUntil(Number(id))
  if (!found) return
  await nextTick()
  document.getElementById(`chat-msg-${id}`)?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  highlighted.value = Number(id)
  clearTimeout(highlightTimer)
  highlightTimer = setTimeout(() => { highlighted.value = null }, HIGHLIGHT_MS)
}

// Content grows (a new message, a picture that loaded): follow it while at the bottom.
let observer = null
onMounted(() => {
  if (typeof ResizeObserver === 'undefined' || !content.value) return
  observer = new ResizeObserver(() => { if (stick) scrollToBottom() })
  observer.observe(content.value)
})
onBeforeUnmount(() => {
  observer?.disconnect()
  clearTimeout(highlightTimer)
})

// Another chat: start at the bottom again (or at the asked message once loaded).
watch(() => props.room.chatId, () => { stick = !props.focusMessage; highlighted.value = null })
watch(
  () => [props.focusMessage, props.room.loading, props.room.chatId],
  ([id, loading]) => { if (id && !loading) focus(id) },
  { immediate: true },
)

defineExpose({ scrollToBottom, focus })
</script>
