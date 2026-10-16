<template>
  <!-- A video made for a request: the player, or its progress, or why it failed; and what to do with it next. -->
  <div class="flex justify-start">
    <div class="w-full max-w-2xl space-y-2">
      <div v-for="(item, i) in items" :key="`${item.run_id}-${item.version}-${i}`" class="space-y-2">
        <div
          class="relative mx-auto max-h-[70vh] overflow-hidden rounded-card bg-slate-900"
          :style="{ aspectRatio: chatItemRatio(item, aspect) }"
        >
          <video
            v-if="chatItemReady(item) && item.file"
            :ref="(el) => { players[i] = el }"
            :src="item.file.url"
            :poster="item.file.thumb_url || undefined"
            controls
            preload="metadata"
            playsinline
            class="h-full w-full bg-black object-contain"
          />
          <div v-else-if="chatItemBusy(item)" class="absolute inset-0 flex flex-col items-center justify-center gap-2 px-4 text-center text-xs text-slate-300">
            <Spinner :size="22" />
            <span>{{ item.status === 'queued' ? t('chat.video.queued') : t('chat.video.making', { p: Math.round((item.progress || 0) * 100) }) }}</span>
            <span class="text-slate-400">{{ t('chat.video.slow') }}</span>
          </div>
          <div v-else-if="item.status === 'cancelled'" class="absolute inset-0 flex flex-col items-center justify-center gap-1 text-xs text-slate-300">
            <AppIcon name="stop" :size="18" />{{ t('chat.video.cancelled') }}
          </div>
          <div v-else class="absolute inset-0 overflow-y-auto bg-white p-3 dark:bg-slate-900">
            <ChatErrorLine :item="item.error_code || item.error ? item : { error_code: 'not_started' }" :spend-link="item.spend_link" />
          </div>
        </div>

        <div v-if="chatItemReady(item) && item.file" class="flex flex-wrap items-center gap-1">
          <button type="button" class="btn-secondary btn-sm" :title="t('chat.video.extendHint')" @click="$emit('reply', { message, index: i })">
            <AppIcon name="reply" :size="14" />{{ t('chat.video.extend') }}
          </button>
          <button
            type="button"
            class="btn-ghost btn-sm"
            :title="t('chat.video.takeFrameHint')"
            :disabled="room.isPending(`frame:${message.id}`)"
            @click="takeFrame(i)"
          >
            <Spinner v-if="room.isPending(`frame:${message.id}`)" :size="14" />
            <AppIcon v-else name="scissors" :size="14" />{{ t('chat.video.takeFrame') }}
          </button>
          <button type="button" class="btn-ghost btn-sm" @click="navigateTo(clipEditorRoute(item.file_id))">
            <AppIcon name="edit" :size="14" />{{ t('chat.video.openEditor') }}
          </button>
          <a :href="videoDownloadUrl(item.file)" download class="btn-ghost btn-sm">
            <AppIcon name="download" :size="14" />{{ t('common.download') }}
          </a>
          <NuxtLink :to="chatMediaLink(item.file_id)" class="btn-ghost btn-sm">
            <AppIcon name="media" :size="14" />{{ t('chat.image.toLibrary') }}
          </NuxtLink>
        </div>
      </div>

      <ChatRepeatConfirm
        v-if="confirming"
        :room="room"
        :message-id="message.request_id"
        :question="action === 'extend' ? t('chat.repeat.askExtendAgain') : t('chat.repeat.askRetake')"
        @done="confirming = false"
        @cancel="confirming = false"
      />

      <div class="flex flex-wrap items-center gap-x-1 gap-y-1 text-xs muted">
        <span v-if="actionLabel" class="badge bg-slate-100 dark:bg-slate-800">{{ actionLabel }}</span>
        <span v-if="first?.model_id" class="px-1">{{ modelTitle(first.model_id) }}</span>
        <span v-if="first?.seconds" class="px-1">{{ t('chat.summary.seconds', { n: first.seconds }) }}</span>
        <span v-if="first?.resolution" class="px-1">{{ first.resolution }}</span>
        <span v-if="message.cost_usd > 0" class="px-1">{{ formatUsd(message.cost_usd) }}</span>
        <time :datetime="message.created_at" class="px-1">{{ chatTime(message.created_at, locale) }}</time>
        <span class="flex-1" />
        <button v-if="busy" type="button" class="btn-ghost btn-sm px-1.5" :disabled="room.isPending(`cancel:${message.id}`)" @click="cancel">
          <AppIcon name="stop" :size="14" />{{ t('chat.video.cancel') }}
        </button>
        <button v-else-if="message.request_id" type="button" class="btn-ghost btn-sm px-1.5" :title="t('chat.video.retakeHint')" @click="confirming = true">
          <AppIcon name="refresh" :size="14" />{{ hasErrors ? t('common.retry') : t('chat.video.retake') }}
        </button>
      </div>
      <ChatSentDetails v-if="request" :settings="request.settings || {}" :attachments="request.attachments || []" />
    </div>
  </div>
</template>

<script setup>
import { clipEditorRoute } from '~/utils/clipState.js'
import { formatUsd } from '~/utils/format.js'
import { videoDownloadUrl } from '~/utils/videoView.js'
import {
  chatItemBusy, chatItemRatio, chatItemReady, chatItems, chatMediaLink, chatMessageBusy, chatTime,
} from '~/utils/chatView.js'

const props = defineProps({
  message: { type: Object, required: true },
  room: { type: Object, required: true },
  request: { type: Object, default: null },
})
defineEmits(['reply'])
const { t, te, locale } = useI18n()
const { confirm } = useConfirm()
const modelTitle = inject('chatModelTitle', (id) => id)

const players = [] // plain array: the <video> elements are not reactive state
const confirming = ref(false)
const items = computed(() => chatItems(props.message))
const first = computed(() => items.value[0] || null)
const action = computed(() => props.message.data?.action || '')
const busy = computed(() => chatMessageBusy(props.message))
const hasErrors = computed(() => items.value.some((i) => i.status === 'error'))
const aspect = computed(() => {
  const s = props.request?.settings || {}
  return s.video_sent?.aspect || s.video?.aspect || '16:9'
})
const actionLabel = computed(() => {
  const key = `chat.actions.${action.value}`
  return action.value && action.value !== 'new_video' && te(key) ? t(key) : ''
})

/** The paused moment of the player, or the last frame when it is not paused in the middle. */
function frameMoment(index) {
  const v = players[index]
  if (!v || !v.paused || !(v.currentTime > 0)) return 'last'
  if (Number.isFinite(v.duration) && v.currentTime >= v.duration - 0.05) return 'last'
  return Math.round(v.currentTime * 1000) / 1000
}

function takeFrame(index) {
  props.room.takeFrame(props.message.id, index, frameMoment(index))
}

async function cancel() {
  const ok = await confirm({ message: t('chat.video.cancelAsk'), confirmLabel: t('chat.video.cancel'), tone: 'danger' })
  if (ok) props.room.cancel(props.message.id)
}
</script>
