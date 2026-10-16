<template>
  <!-- What the person sent: the quote it answers, the pictures with their roles, the text and what became of it. -->
  <div class="flex justify-end">
    <div class="flex min-w-0 max-w-[min(42rem,92%)] flex-col items-end gap-1.5">
      <button
        v-if="message.reply"
        type="button"
        class="flex max-w-full items-center gap-2 rounded-button border-l-2 border-primary bg-slate-100 px-2 py-1 text-left text-xs text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
        :title="t('chat.request.jump')"
        @click="$emit('jump', message.reply.id)"
      >
        <img v-if="message.reply.thumb_url" :src="message.reply.thumb_url" alt="" class="h-8 w-8 shrink-0 rounded object-cover">
        <AppIcon v-else name="reply" :size="14" class="shrink-0" />
        <span class="min-w-0 truncate">{{ replyText }}</span>
      </button>

      <div v-if="pictures.length" class="flex flex-wrap justify-end gap-1.5">
        <figure v-for="(a, i) in pictures" :key="`${a.file_id}-${i}`" class="relative">
          <img v-if="chatFileThumb(a.file)" :src="chatFileThumb(a.file)" alt="" class="h-16 w-16 rounded-button object-cover sm:h-20 sm:w-20">
          <div v-else class="grid h-16 w-16 place-items-center rounded-button bg-slate-100 text-slate-400 dark:bg-slate-800 sm:h-20 sm:w-20">
            <AppIcon name="alert" :size="16" />
          </div>
          <figcaption class="absolute inset-x-1 bottom-1 truncate rounded bg-slate-950/60 px-1 text-center text-[10px] text-white">
            {{ roleText(a.role) }}
          </figcaption>
        </figure>
      </div>

      <div
        v-if="text"
        class="max-w-full whitespace-pre-wrap break-words rounded-2xl rounded-tr-md bg-primary/10 px-4 py-2.5 text-sm text-slate-900 dark:text-slate-100"
      >{{ text }}</div>

      <div v-if="message.status === 'enhancing'" class="flex items-center gap-2 text-xs muted">
        <Spinner :size="14" />{{ t('chat.request.enhancing') }}
      </div>
      <div v-else-if="s.enhanced" class="max-w-full rounded-card border border-dashed border-primary/40 px-3 py-2 text-sm">
        <p class="mb-1 flex items-center gap-1 text-xs font-medium text-primary">
          <AppIcon name="sparkles" :size="14" />{{ t('chat.request.enhanced') }}
        </p>
        <p class="whitespace-pre-wrap break-words">{{ s.sent_text }}</p>
      </div>

      <ChatErrorLine v-if="message.status === 'error'" class="w-full" :item="message" :spend-link="message.spend_link">
        <template v-if="enhanceFailed">
          <button type="button" class="btn-secondary btn-sm" @click="$emit('restore', message)">
            <AppIcon name="edit" :size="14" />{{ t('chat.request.restore') }}
          </button>
          <button type="button" class="btn-secondary btn-sm" @click="confirming = 'original'">
            <AppIcon name="send" :size="14" />{{ t('chat.request.sendOriginal') }}
          </button>
        </template>
        <button v-else type="button" class="btn-secondary btn-sm" @click="confirming = 'repeat'">
          <AppIcon name="refresh" :size="14" />{{ t('common.retry') }}
        </button>
      </ChatErrorLine>

      <ChatRepeatConfirm
        v-if="confirming"
        class="w-full"
        :room="room"
        :message-id="message.id"
        :original="confirming === 'original'"
        :question="confirming === 'original' ? t('chat.repeat.askOriginal') : t('chat.repeat.askRepeat')"
        @done="confirming = null"
        @cancel="confirming = null"
      />

      <div class="flex flex-wrap items-center justify-end gap-x-1 gap-y-1 text-xs muted">
        <time :datetime="message.created_at" class="px-1">{{ chatTime(message.created_at, locale) }}</time>
        <span v-if="message.cost_usd > 0" class="px-1" :title="t('chat.request.enhanceCost')">{{ formatUsd(message.cost_usd) }}</span>
        <button v-if="!busy" type="button" class="btn-ghost btn-sm px-1.5" :title="t('chat.request.repeatHint')" @click="confirming = 'repeat'">
          <AppIcon name="refresh" :size="14" />{{ t('chat.request.repeat') }}
        </button>
        <button v-if="s.enhanced && !busy" type="button" class="btn-ghost btn-sm px-1.5" :title="t('chat.request.sendOriginalHint')" @click="confirming = 'original'">
          <AppIcon name="send" :size="14" />{{ t('chat.request.sendOriginal') }}
        </button>
        <button v-if="text" type="button" class="btn-ghost btn-sm px-1.5" :title="t('common.copy')" @click="copy">
          <AppIcon name="copy" :size="14" />
        </button>
      </div>
      <ChatSentDetails :settings="s" :attachments="message.attachments || []" />
    </div>
  </div>
</template>

<script setup>
import { formatUsd } from '~/utils/format.js'
import { chatFileThumb, chatMessageBusy, chatTime } from '~/utils/chatView.js'

const props = defineProps({
  message: { type: Object, required: true },
  room: { type: Object, required: true },
})
defineEmits(['restore', 'jump'])
const { t, te, locale } = useI18n()
const toast = useToast()

const confirming = ref(null) // null | 'repeat' | 'original'
const s = computed(() => props.message.settings || {})
const text = computed(() => props.message.text || s.value.original_text || '')
const pictures = computed(() => props.message.attachments || [])
const busy = computed(() => chatMessageBusy(props.message))
const enhanceFailed = computed(() => Boolean(s.value.enhance && !s.value.enhanced))

const replyText = computed(() => {
  const r = props.message.reply
  if (!r) return ''
  const what = r.kind === 'video' ? t('chat.request.replyVideo') : t('chat.request.replyPicture', { n: (r.index || 0) + 1 })
  return r.text ? `${what}: ${r.text}` : what
})

function roleText(role) {
  return te(`chat.roles.${role}`) ? t(`chat.roles.${role}`) : role
}

async function copy() {
  try {
    await navigator.clipboard.writeText(text.value)
    toast.success(t('common.copied'))
  } catch {
    toast.error(t('chat.request.copyFailed'))
  }
}
</script>
