<template>
  <!--
    /chat opens the newest chat (a new one when there is none).
    /chat?frame= | ?work= | ?video= opens the chat that holds that result; when no
    chat holds it, the result is shown here in its own workspace instead.
  -->
  <div class="h-full">
    <div v-if="state === 'loading'" class="flex h-full items-center justify-center"><Spinner /></div>

    <div v-else-if="state === 'missing'" class="page">
      <EmptyState icon="alert" :title="t('chat.find.missingTitle')" :text="missingText">
        <button type="button" class="btn-secondary" @click="openChat">{{ t('chat.find.toChat') }}</button>
      </EmptyState>
    </div>

    <div v-else class="page space-y-4">
      <div class="flex flex-wrap items-center gap-2 rounded-card bg-slate-100 px-3 py-2 text-sm dark:bg-slate-800">
        <AppIcon name="info" :size="16" class="shrink-0 opacity-70" />
        <span class="min-w-0 flex-1">{{ t('chat.find.notInChat') }}</span>
        <button type="button" class="btn-ghost btn-sm" @click="openChat">
          <AppIcon name="chat" :size="16" />{{ t('chat.find.toChat') }}
        </button>
      </div>
      <StudioWorkspace
        v-if="state === 'work'"
        :work-id="found.work_id"
        :initial-frame-id="found.frame_id || null"
        @removed="openChat"
      />
      <VideoWorkspace
        v-else
        :run-id="found.run_id"
        @removed="openChat"
        @open-editor="({ fileId }) => navigateTo(clipEditorRoute(fileId))"
      />
    </div>
  </div>
</template>

<script setup>
import { chatErrorText, chatFindQuery } from '~/utils/chatView.js'
import { clipEditorRoute } from '~/utils/clipState.js'

const { t, te } = useI18n()
const route = useRoute()
const api = useApi()
const start = useChatStart()

const state = ref('loading')
const found = ref(null)
const failure = ref(null)
const missingText = computed(() => (failure.value && failure.value.status !== 404
  ? chatErrorText(failure.value, t, te)
  : t('chat.find.missingText')))

async function openChat() {
  state.value = 'loading'
  const chat = await start.open()
  if (chat) await navigateTo(`/chat/${chat.id}`, { replace: true })
  else state.value = 'missing'
}

async function resolve() {
  const ask = chatFindQuery(route.query)
  failure.value = null
  if (!ask) return openChat()
  state.value = 'loading'
  try {
    const res = await api.get('/api/chat/find', { [ask.key]: ask.id })
    if (res?.chat_id) {
      const query = res.message_id ? { message: res.message_id } : {}
      return navigateTo({ path: `/chat/${res.chat_id}`, query }, { replace: true })
    }
    found.value = res
    state.value = res?.work_id ? 'work' : res?.run_id ? 'video' : 'missing'
  } catch (err) {
    failure.value = err
    state.value = 'missing'
  }
  return null
}

watch(() => route.fullPath, () => { if (route.path === '/chat') resolve() }, { immediate: true })
</script>
