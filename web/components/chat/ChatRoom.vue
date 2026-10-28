<template>
  <!--
    One chat: the feed with the input under it, and the settings panel on the
    right (a drawer over the feed on narrow screens). The list of chats lives in
    the app's left menu.
  -->
  <div class="flex h-full min-h-0">
    <div class="flex min-w-0 flex-1 flex-col">
      <div v-if="room.loading && !room.chat" class="flex flex-1 items-center justify-center"><Spinner :size="24" /></div>

      <div v-else-if="room.error && !room.chat" class="page">
        <EmptyState icon="alert" :title="gone ? t('chat.room.gone') : t('chat.room.failed')" :text="gone ? t('chat.room.goneText') : chatErrorText(room.error, t, te)">
          <div class="flex flex-wrap justify-center gap-2">
            <button v-if="!gone" type="button" class="btn-secondary" @click="room.load()">
              <AppIcon name="refresh" :size="16" />{{ t('chat.room.retry') }}
            </button>
            <NuxtLink to="/chat" class="btn-primary">{{ t('chat.room.toList') }}</NuxtLink>
          </div>
        </EmptyState>
      </div>

      <template v-else-if="room.chat">
        <header class="flex items-center gap-2 border-b border-slate-200 px-3 py-2 dark:border-slate-800 sm:px-4">
          <h1 class="min-w-0 flex-1 truncate text-sm font-semibold">{{ room.chat.title || t('chat.room.untitled') }}</h1>
          <span class="badge inline-flex items-center gap-1">
            <AppIcon :name="room.mode === 'video' ? 'video' : 'image'" :size="12" />{{ t(`chat.modes.${room.mode}`) }}
          </span>
          <button
            type="button"
            class="btn-ghost p-1.5"
            :class="panelOpen && 'text-primary'"
            :aria-pressed="panelOpen"
            :aria-label="t('chat.room.settings')"
            :title="t('chat.room.settings')"
            @click="panelOpen = !panelOpen"
          >
            <AppIcon name="panel" :size="18" />
          </button>
        </header>

        <div v-if="room.chat.archived" class="flex flex-wrap items-center gap-2 border-b border-amber-200 bg-amber-50 px-4 py-2 text-sm dark:border-amber-900 dark:bg-amber-950/40">
          <AppIcon name="archive" :size="16" class="shrink-0 opacity-70" />
          <span class="min-w-0 flex-1">{{ t('chat.room.archived') }}</span>
          <button type="button" class="btn-secondary btn-sm" :disabled="restoring" @click="unarchive">
            <Spinner v-if="restoring" :size="14" />{{ t('chat.room.restore') }}
          </button>
        </div>

        <div class="min-h-0 flex-1">
          <ChatFeed
            ref="feed"
            :room="room"
            :focus-message="focusMessage"
            @reply="onReply"
            @viewer="openViewer"
            @animate="onAnimate"
            @reference="onReference"
            @restore="onRestore"
            @example="(text) => composer?.setText(text)"
          />
        </div>
        <ChatComposer v-if="!room.chat.archived" ref="composer" :room="room" @sent="feed?.scrollToBottom(true)" />
      </template>
    </div>

    <template v-if="room.chat">
      <Transition name="vf-fade">
        <div v-if="panelOpen && !wide" class="fixed inset-0 z-40 bg-slate-950/50" @click="panelOpen = false" />
      </Transition>
      <aside
        v-show="panelOpen"
        class="fixed inset-y-0 right-0 z-50 w-[min(22rem,92vw)] overflow-y-auto border-l border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900 xl:static xl:z-auto xl:w-80 xl:shrink-0"
        :aria-label="t('chat.settings.title')"
      >
        <ChatSettingsPanel :room="room" @close="panelOpen = false" />
      </aside>
    </template>

    <StudioFrameViewer :studio="studio" :frame-id="viewer.frameId" @open="viewerGo" @close="closeViewer" />
  </div>
</template>

<script setup>
import { useMediaQuery } from '@vueuse/core'
import { chatErrorText } from '~/utils/chatView.js'

const props = defineProps({
  chatId: { type: Number, default: null },
  focusMessage: { type: Number, default: null },
})
const { t, te } = useI18n()
const api = useApi()
const toast = useToast()

const room = reactive(useChatRoom(() => props.chatId))
const models = useModels()
provide('chatModels', models)
provide('chatModelTitle', (id) => models.find(id)?.title || id)
onMounted(() => { if (!models.loaded.value && !models.loading.value) models.load() })

const feed = ref(null)
const composer = ref(null)

const gone = computed(() => Number(room.error?.status) === 404)

// ── the settings panel: open by default on wide screens ──

const wide = useMediaQuery('(min-width: 1280px)')
const panelOpen = ref(false)
watch(wide, (v) => { panelOpen.value = v }, { immediate: true })

// ── archived chat ──

const restoring = ref(false)
async function unarchive() {
  restoring.value = true
  try {
    await api.post(`/api/chat/chats/${props.chatId}/archive`, { archived: false })
    await room.loadChat()
  } catch (err) {
    toast.error(chatErrorText(err, t, te))
  } finally {
    restoring.value = false
  }
}

// ── actions from the feed ──

function onReply(payload) {
  composer.value?.setReply(payload)
}

/** «Animate»: the picture becomes the first frame of a video request. Nothing is sent yet. */
function onAnimate({ file } = {}) {
  if (!file) return
  composer.value?.clearReply()
  room.setMode('video')
  composer.value?.addFiles([file])
  composer.value?.focus()
}

function onReference({ file } = {}) {
  if (!file) return
  composer.value?.clearReply()
  composer.value?.addFiles([file])
  composer.value?.focus()
}

/** Put a sent request back into the input (its own words, before any improvement). */
function onRestore(message) {
  if (!message) return
  if (message.mode && message.mode !== room.mode) room.setMode(message.mode)
  room.editDraft({
    text: message.settings?.original_text ?? message.text ?? '',
    attachments: (message.attachments || []).map((a) => ({ file_id: a.file_id, role: a.role, file: a.file })),
    reply_to: null, reply_index: 0, reply: null, region: null, extend_seconds: null,
  })
  nextTick(() => composer.value?.focus())
}

// ── the frame viewer of the studio ──
// Edits made there (new versions, a picked picture) come back to the chat as a
// new picture message when the viewer closes, one per frame that was looked at.

const viewer = reactive({ workId: null, frameId: null, replyTo: null, seen: [] })
const studio = useStudioWork(() => viewer.workId)

function openViewer({ workId, frameId, replyTo = null } = {}) {
  if (!workId || !frameId) return
  viewer.workId = workId
  viewer.frameId = frameId
  viewer.replyTo = replyTo
  viewer.seen = [frameId]
}

function viewerGo(frameId) {
  viewer.frameId = frameId
  if (frameId && !viewer.seen.includes(frameId)) viewer.seen.push(frameId)
}

async function closeViewer() {
  const seen = [...viewer.seen]
  const replyTo = viewer.replyTo
  viewer.frameId = null
  viewer.seen = []
  for (const id of seen) await room.fromViewer(id, replyTo)
}

watch(() => props.chatId, () => {
  viewer.frameId = null
  viewer.seen = []
})
</script>
