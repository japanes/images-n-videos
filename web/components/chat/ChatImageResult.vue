<template>
  <!--
    Pictures made for a request. A finished picture opens the big viewer on a
    click, can be dragged into the composer to answer it, and has a menu of
    actions. Busy, waiting and failed pictures keep their place in the grid.
  -->
  <div class="flex justify-start">
    <div class="w-full max-w-3xl space-y-2">
      <div class="grid gap-2" :class="gridClass">
        <div
          v-for="(item, i) in items"
          :key="item.frame_id || i"
          class="group relative overflow-hidden rounded-card bg-slate-100 dark:bg-slate-800"
          :style="{ aspectRatio: chatItemRatio(item, aspect) }"
        >
          <template v-if="chatItemReady(item) && item.file">
            <img
              :src="item.file.thumb_url || item.file.url"
              :alt="t('chat.image.alt', { n: i + 1 })"
              class="h-full w-full cursor-zoom-in object-cover"
              draggable="true"
              @dragstart="drag($event, i)"
              @click="openViewer(item)"
            >
            <div class="absolute right-1.5 top-1.5 flex gap-1 transition-opacity sm:opacity-0 sm:focus-within:opacity-100 sm:group-hover:opacity-100">
              <button type="button" :class="overlayButton" :title="t('chat.image.reply')" :aria-label="t('chat.image.reply')" @click="$emit('reply', { message, index: i })">
                <AppIcon name="reply" :size="16" />
              </button>
              <ChatMenu :items="menuItems(item, i)" :label="t('common.more')" :button-class="overlayButton" />
            </div>
          </template>

          <div v-else-if="chatItemBusy(item)" class="absolute inset-0 flex flex-col items-center justify-center gap-2 text-xs muted">
            <Spinner :size="20" />
            <span>{{ item.status === 'queued' ? t('chat.image.queued') : `${Math.round((item.progress || 0) * 100)}%` }}</span>
          </div>
          <div v-else-if="item.status === 'waiting'" class="absolute inset-0 flex flex-col items-center justify-center gap-1 p-3 text-center text-xs muted">
            <AppIcon name="pause" :size="18" />{{ t('chat.image.waiting') }}
          </div>
          <div v-else-if="item.status === 'cancelled'" class="absolute inset-0 flex flex-col items-center justify-center gap-1 text-xs muted">
            <AppIcon name="stop" :size="18" />{{ t('chat.image.cancelled') }}
          </div>
          <div v-else class="absolute inset-0 overflow-y-auto p-2">
            <ChatErrorLine compact :item="item.error_code || item.error ? item : { error_code: 'not_started' }" :spend-link="item.spend_link" />
          </div>
        </div>
      </div>

      <!-- Series: the first picture is checked before the rest are paid for -->
      <div v-if="pilotWaiting" class="flex flex-wrap items-center gap-2 rounded-card bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:bg-amber-500/10 dark:text-amber-100">
        <span class="min-w-0 flex-1">{{ pilotReady ? t('chat.image.pilotAsk', { n: waiting }, waiting) : t('chat.image.pilotWait') }}</span>
        <PriceButton
          v-if="pilotReady"
          class="btn-sm"
          icon="check"
          :label="t('chat.image.pilotAccept')"
          :usd="pilotUsd"
          :disabled="pilotUsd === null"
          :busy="room.isPending(`pilot:${message.id}`)"
          @click="room.acceptPilot(message.id)"
        />
      </div>

      <ChatRepeatConfirm
        v-if="confirming"
        :room="room"
        :message-id="message.request_id"
        :question="actionAgain ? t('chat.repeat.askAgain') : t('chat.repeat.askVariants')"
        @done="confirming = false"
        @cancel="confirming = false"
      />

      <div class="flex flex-wrap items-center gap-x-1 gap-y-1 text-xs muted">
        <span v-if="actionLabel" class="badge bg-slate-100 dark:bg-slate-800">{{ actionLabel }}</span>
        <span v-if="modelId" class="px-1">{{ modelTitle(modelId) }}</span>
        <span v-if="message.cost_usd > 0" class="px-1">{{ formatUsd(message.cost_usd) }}</span>
        <time :datetime="message.created_at" class="px-1">{{ chatTime(message.created_at, locale) }}</time>
        <span class="flex-1" />
        <button v-if="busy" type="button" class="btn-ghost btn-sm px-1.5" :disabled="room.isPending(`cancel:${message.id}`)" @click="cancel">
          <AppIcon name="stop" :size="14" />{{ t('chat.image.cancel') }}
        </button>
        <button v-if="canRepeat && hasErrors" type="button" class="btn-ghost btn-sm px-1.5" @click="confirming = true">
          <AppIcon name="refresh" :size="14" />{{ t('common.retry') }}
        </button>
        <button v-else-if="canRepeat" type="button" class="btn-ghost btn-sm px-1.5" @click="confirming = true">
          <AppIcon name="refresh" :size="14" />{{ actionAgain ? t('chat.image.again') : t('chat.image.moreVariants') }}
        </button>
      </div>
      <ChatSentDetails v-if="request" :settings="request.settings || {}" :attachments="request.attachments || []" />
    </div>
  </div>
</template>

<script setup>
import { formatUsd } from '~/utils/format.js'
import {
  chatImageActions, chatItemBusy, chatItemRatio, chatItemReady, chatItems, chatMediaLink, chatMessageBusy, chatTime,
  chatWaitingCount,
} from '~/utils/chatView.js'

const props = defineProps({
  message: { type: Object, required: true },
  room: { type: Object, required: true },
  request: { type: Object, default: null }, // the request message this answers, when loaded
})
const emit = defineEmits(['reply', 'viewer', 'animate', 'reference'])
const { t, te, locale } = useI18n()
const { confirm } = useConfirm()
const modelTitle = inject('chatModelTitle', (id) => id)

const overlayButton = 'grid h-8 w-8 place-items-center rounded-full bg-slate-950/60 text-white hover:bg-slate-950/80'
const confirming = ref(false)

const items = computed(() => chatItems(props.message))
const action = computed(() => props.message.data?.action || '')
const aspect = computed(() => props.request?.settings?.image?.aspect || null)
const busy = computed(() => chatMessageBusy(props.message))
const hasErrors = computed(() => !busy.value && items.value.some((i) => i.status === 'error'))
const modelId = computed(() => items.value.find((i) => i.model_id)?.model_id || props.request?.settings?.model_id || '')
const canRepeat = computed(() => Boolean(props.message.request_id) && !busy.value && !pilotWaiting.value)
const actionAgain = computed(() => action.value !== 'new_image')
const actionLabel = computed(() => {
  const key = `chat.actions.${action.value}`
  return action.value && action.value !== 'new_image' && te(key) ? t(key) : ''
})

const gridClass = computed(() => {
  const n = items.value.length
  if (n <= 1) return 'max-w-md grid-cols-1'
  if (n === 2 || n === 4) return 'grid-cols-2'
  return 'grid-cols-2 sm:grid-cols-3'
})

// ── series ──
const waiting = computed(() => chatWaitingCount(props.message))
const pilotWaiting = computed(() => waiting.value > 0 && !props.message.data?.pilot_accepted)
const pilotReady = computed(() => pilotWaiting.value && items.value.some((i) => chatItemReady(i)))
const pilotUsd = ref(null)
watch(pilotReady, async (ready) => {
  if (!ready) return
  const est = await props.room.pilotEstimate(props.message.id)
  pilotUsd.value = est && est.usd !== null && est.usd !== undefined ? Number(est.usd) : null
}, { immediate: true })

// ── actions on one picture ──
function openViewer(item) {
  emit('viewer', { workId: item.work_id, frameId: item.frame_id, replyTo: props.message.id })
}

function drag(e, index) {
  e.dataTransfer.effectAllowed = 'copy'
  e.dataTransfer.setData('application/x-vf-chat-item', JSON.stringify({ message_id: props.message.id, index }))
}

function menuItems(item, index) {
  const file = item.file
  const extra = chatImageActions().map((a) => ({
    id: `x-${a.id}`, icon: a.icon, label: t(a.labelKey),
    onClick: () => a.onClick?.({ message: props.message, item, index, room: props.room }),
  }))
  return [
    { id: 'reply', icon: 'edit', label: t('chat.image.reply'), onClick: () => emit('reply', { message: props.message, index }) },
    { id: 'viewer', icon: 'search', label: t('chat.image.findObjects'), onClick: () => openViewer(item) },
    { id: 'animate', icon: 'video', label: t('chat.image.animate'), title: t('chat.image.animateHint'), onClick: () => emit('animate', { file }) },
    { id: 'reference', icon: 'paperclip', label: t('chat.image.useAsReference'), onClick: () => emit('reference', { file }) },
    ...extra,
    { id: 'download', icon: 'download', label: t('common.download'), href: `${file.url}?download=1`, download: true },
    { id: 'media', icon: 'media', label: t('chat.image.toLibrary'), to: chatMediaLink(item.file_id) },
  ]
}

async function cancel() {
  const ok = await confirm({ message: t('chat.image.cancelAsk'), confirmLabel: t('chat.image.cancel'), tone: 'danger' })
  if (ok) props.room.cancel(props.message.id)
}
</script>
