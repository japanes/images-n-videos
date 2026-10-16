<template>
  <!--
    The input of a chat: text, attached pictures with their roles, a reply to a
    picture or a video of the feed, and the send button with its price. Under it
    a line of what the request will be made with; a click on a part opens that
    setting in the panel. Enter sends, Shift+Enter starts a new line.
  -->
  <div
    class="border-t border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950"
    :class="dragging && 'bg-primary/5'"
    @dragover="onDragOver"
    @dragleave="dragging = false"
    @drop="onDrop"
  >
    <div class="mx-auto w-full max-w-4xl space-y-2 px-3 py-3 sm:px-6">
      <!-- the reply: what is answered, an area of the picture or the length of the extension -->
      <div v-if="replyKind" class="flex flex-wrap items-center gap-2 rounded-card bg-slate-100 p-2 text-sm dark:bg-slate-800">
        <img v-if="d.reply?.thumb_url" :src="d.reply.thumb_url" alt="" class="h-10 w-10 shrink-0 rounded-button object-cover">
        <AppIcon v-else :name="replyKind === 'video' ? 'video' : 'image'" :size="20" class="shrink-0 opacity-60" />
        <div class="min-w-0 flex-1">
          <p class="text-xs muted">{{ replyKind === 'video' ? t('chat.composer.replyVideo') : t('chat.composer.replyPicture') }}</p>
          <p v-if="d.reply?.text" class="truncate">{{ d.reply.text }}</p>
        </div>
        <button
          v-if="replyKind === 'image'"
          type="button"
          class="btn-ghost btn-sm"
          :disabled="!replyItem?.file"
          :title="t('chat.composer.regionHint')"
          @click="regionOpen = true"
        >
          <AppIcon name="scissors" :size="14" />{{ t('chat.composer.region') }}
        </button>
        <label v-if="replyKind === 'video' && extendLengths.length" class="flex items-center gap-1.5 text-xs">
          <span class="muted">{{ t('chat.composer.extendBy') }}</span>
          <select class="input w-auto py-1 text-sm" :value="extendValue ?? ''" @change="room.editDraft({ extend_seconds: Number($event.target.value) })">
            <option v-for="n in extendLengths" :key="n" :value="n">{{ t('chat.summary.seconds', { n }) }}</option>
          </select>
        </label>
        <button type="button" class="btn-ghost p-1.5" :aria-label="t('chat.composer.replyCancel')" :title="t('chat.composer.replyCancel')" @click="clearReply">
          <AppIcon name="close" :size="16" />
        </button>
      </div>
      <div v-if="replyKind === 'image' && d.region" class="flex">
        <span class="badge inline-flex items-center gap-1">
          <AppIcon name="scissors" :size="12" />{{ d.region.id ? t('chat.composer.regionObject') : t('chat.composer.regionBox') }}
          <button type="button" class="ml-0.5 opacity-70 hover:opacity-100" :aria-label="t('chat.composer.regionClear')" @click="room.editDraft({ region: null })">
            <AppIcon name="close" :size="12" />
          </button>
        </span>
      </div>

      <!-- attached pictures: a click changes the role -->
      <div v-if="d.attachments.length" class="space-y-1">
        <div class="flex flex-wrap gap-2" :class="replyKind && 'opacity-40'">
          <div v-for="(a, i) in d.attachments" :key="a.file_id" class="relative">
            <button
              type="button"
              class="relative block h-16 w-16 overflow-hidden rounded-button border border-slate-200 dark:border-slate-700"
              :disabled="Boolean(replyKind)"
              :title="t('chat.composer.roleHint')"
              @click="cycleRole(i)"
            >
              <img :src="chatFileThumb(a.file)" alt="" class="h-full w-full object-cover">
              <span class="absolute inset-x-0 bottom-0 truncate bg-slate-950/60 px-1 py-0.5 text-center text-[10px] text-white">{{ roleText(a.role) }}</span>
            </button>
            <button
              type="button"
              class="absolute -right-1.5 -top-1.5 grid h-5 w-5 place-items-center rounded-full bg-slate-800 text-white hover:bg-slate-950 dark:bg-slate-600"
              :aria-label="t('chat.composer.remove')"
              @click="removeAttachment(i)"
            >
              <AppIcon name="close" :size="12" />
            </button>
          </div>
        </div>
        <p v-if="replyKind" class="text-xs muted">{{ t('chat.composer.replyNoPictures') }}</p>
      </div>

      <!-- the text and the buttons -->
      <div class="rounded-card border border-slate-300 bg-white focus-within:border-primary dark:border-slate-700 dark:bg-slate-900">
        <textarea
          ref="input"
          rows="1"
          class="block w-full resize-none bg-transparent px-3 pt-3 text-sm outline-none placeholder:text-slate-400"
          :style="{ maxHeight: `${MAX_HEIGHT}px` }"
          :value="d.text"
          :maxlength="maxText"
          :placeholder="placeholder"
          :aria-label="placeholder"
          @input="onInput"
          @keydown.enter="onEnter"
        />
        <div class="flex flex-wrap items-center gap-1 px-2 pb-2 pt-1">
          <ChatMenu
            :items="attachItems"
            icon="paperclip"
            :label="replyKind ? t('chat.composer.replyNoPictures') : t('chat.composer.attach')"
            :disabled="Boolean(replyKind) || !remaining"
          />
          <div class="flex rounded-button bg-slate-100 p-0.5 dark:bg-slate-800">
            <button
              v-for="m in CHAT_MODES"
              :key="m"
              type="button"
              class="rounded-button p-1.5"
              :class="mode === m ? 'bg-white text-primary shadow-sm dark:bg-slate-700' : 'text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-100'"
              :aria-pressed="mode === m"
              :title="t(`chat.modes.${m}`)"
              :aria-label="t(`chat.modes.${m}`)"
              @click="switchMode(m)"
            >
              <AppIcon :name="m === 'video' ? 'video' : 'image'" :size="16" />
            </button>
          </div>
          <button
            v-if="mode === 'image' && !replyKind"
            type="button"
            class="btn-ghost btn-sm px-1.5"
            :disabled="dicing || room.isPending('settings')"
            :title="t('chat.composer.dice')"
            :aria-label="t('chat.composer.dice')"
            @click="dice"
          >
            <Spinner v-if="dicing" :size="14" /><AppIcon v-else name="dice" :size="16" />
          </button>
          <button
            v-if="mode === 'video' && !replyKind"
            type="button"
            class="btn-ghost btn-sm"
            :title="t('chat.composer.briefHint')"
            @click="briefOpen = true"
          >
            <AppIcon name="wand" :size="16" /><span class="hidden sm:inline">{{ t('chat.composer.brief') }}</span>
          </button>
          <button
            v-for="b in extraButtons"
            :key="b.id"
            type="button"
            class="btn-ghost btn-sm px-1.5"
            :title="buttonLabel(b)"
            :aria-label="buttonLabel(b)"
            @click="b.onClick?.(buttonContext())"
          >
            <AppIcon :name="b.icon || 'sparkles'" :size="16" />
          </button>
          <span v-if="canEnhance" class="ml-1 inline-flex items-center gap-1.5" :title="enhanceTitle">
            <ToggleSwitch
              :model-value="Boolean(d.enhance)"
              :label="t('chat.composer.enhance')"
              :disabled="Boolean(enhanceInfo.error)"
              @update:model-value="room.editDraft({ enhance: $event })"
            />
            <span v-if="enhanceUsd !== null && enhanceUsd !== undefined" class="badge tabular-nums">+{{ formatUsd(enhanceUsd, { approx: true }) }}</span>
          </span>

          <span class="ml-auto" />
          <span v-if="showCounter" class="text-xs tabular-nums" :class="textLength >= maxText ? 'text-rose-600 dark:text-rose-400' : 'muted'">
            {{ textLength }}/{{ maxText }}
          </span>
          <PriceButton
            icon="send"
            :label="t('chat.composer.send')"
            :usd="sendUsd"
            :disabled="!sendReady"
            :busy="room.isPending('send')"
            @click="submit"
          />
        </div>
      </div>

      <!-- what the request is made with; a click opens that setting -->
      <div class="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-xs muted">
        <template v-for="(p, i) in summary" :key="`${p.key}-${i}`">
          <span v-if="i" aria-hidden="true">·</span>
          <button v-if="p.key" type="button" class="hover:text-primary hover:underline" @click="$emit('open-field', p.key)">{{ p.text }}</button>
          <span v-else>{{ p.text }}</span>
        </template>
      </div>
      <p v-for="w in warnings" :key="w" class="flex items-start gap-1.5 text-xs text-amber-700 dark:text-amber-400">
        <AppIcon name="alert" :size="14" class="mt-px shrink-0" />{{ chatWarningText(w, t, te) }}
      </p>
      <p v-if="refusal" class="flex items-start gap-1.5 text-xs text-rose-600 dark:text-rose-400">
        <AppIcon name="info" :size="14" class="mt-px shrink-0" />{{ refusal }}
      </p>
    </div>

    <StudioSourcePicker
      :open="sourceOpen"
      :title="t('chat.composer.attach')"
      multiple
      :max="Math.max(1, remaining)"
      @pick="onPick"
      @close="sourceOpen = false"
    />
    <ChatPicturesPicker :open="picturesOpen" :room="room" :max="Math.max(1, remaining)" @pick="onPick" @close="picturesOpen = false" />
    <ChatRegionModal
      :open="regionOpen"
      :item="replyItem"
      :model-value="d.region"
      @update:model-value="room.editDraft({ region: $event })"
      @close="regionOpen = false"
    />
    <ChatBriefModal v-if="briefOpen" :open="briefOpen" :room="room" @use="useBrief" @close="briefOpen = false" />
  </div>
</template>

<script setup>
import { formatUsd } from '~/utils/format.js'
import { studioStyleSetting } from '~/utils/studioView.js'
import { videoAttachWarnings, videoModelById } from '~/utils/videoView.js'
import {
  CHAT_LIMITS, CHAT_MODES, chatAddPictures, chatCanSend, chatComposerButtons, chatErrorText, chatFileThumb, chatItems,
  chatNextRole, chatRandomPick, chatReasonText, chatSendBody, chatSummaryParts, chatWarningText, chatWarnings,
} from '~/utils/chatView.js'

const props = defineProps({
  room: { type: Object, required: true }, // reactive(useChatRoom(…))
})
const emit = defineEmits(['open-field', 'sent'])
const { t, te } = useI18n()
const api = useApi()
const toast = useToast()
const modelTitle = inject('chatModelTitle', (id) => id)
const catalog = useVideoCatalog()

const DRAG_TYPE = 'application/x-vf-chat-item'
const MAX_HEIGHT = 240
const COUNTER_FROM = 0.8 // the counter shows from 80% of the limit

const input = ref(null)
const dragging = ref(false)
const sourceOpen = ref(false)
const picturesOpen = ref(false)
const regionOpen = ref(false)
const briefOpen = ref(false)
const dicing = ref(false)

const chat = computed(() => props.room.chat)
const d = computed(() => props.room.draft)
const mode = computed(() => props.room.mode)
const limits = computed(() => chat.value?.limits || {})
const replyKind = computed(() => {
  if (!d.value.reply_to) return null
  return d.value.reply?.kind === 'video' ? 'video' : 'image'
})

// ── text ──

const hasBase = computed(() => mode.value === 'image' && d.value.attachments.some((a) => a.role === 'base'))
const maxText = computed(() => {
  const l = limits.value
  if (replyKind.value === 'video') return Number(l.max_extend || CHAT_LIMITS.text)
  if (replyKind.value === 'image' || hasBase.value) return Number(l.max_edit || CHAT_LIMITS.text)
  return Number(l.max_text || CHAT_LIMITS.text)
})
const textLength = computed(() => String(d.value.text || '').length)
const showCounter = computed(() => textLength.value >= maxText.value * COUNTER_FROM)
const placeholder = computed(() => {
  if (replyKind.value === 'video') return t('chat.composer.placeholderExtend')
  if (replyKind.value === 'image') return t('chat.composer.placeholderEdit')
  return mode.value === 'video' ? t('chat.composer.placeholderVideo') : t('chat.composer.placeholderImage')
})

function autosize() {
  const el = input.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT)}px`
}
watch(() => d.value.text, () => nextTick(autosize))
onMounted(autosize)

function onInput(e) {
  props.room.editDraft({ text: e.target.value })
  autosize()
}

function onEnter(e) {
  if (e.shiftKey || e.isComposing || e.keyCode === 229) return // a new line, or a word being typed in an IME
  e.preventDefault()
  submit()
}

function focus() {
  input.value?.focus()
}

function setText(text) {
  props.room.editDraft({ text: String(text || '') })
  nextTick(() => { autosize(); focus() })
}

// ── attached pictures ──

const maxAttachments = computed(() => Number(limits.value.max_attachments || CHAT_LIMITS.attachments))
const remaining = computed(() => Math.max(0, maxAttachments.value - d.value.attachments.length))

const attachItems = computed(() => [
  { id: 'library', icon: 'upload', label: t('chat.composer.fromLibrary'), onClick: () => { sourceOpen.value = true } },
  { id: 'chat', icon: 'chat', label: t('chat.composer.fromChat'), onClick: () => { picturesOpen.value = true } },
])

function roleText(role) {
  return te(`chat.roles.${role}`) ? t(`chat.roles.${role}`) : role
}

function addFiles(files) {
  const next = chatAddPictures(d.value.attachments, files, mode.value, maxAttachments.value)
  if (next.length < d.value.attachments.length + (files || []).length) toast.info(t('chat.composer.tooMany', { max: maxAttachments.value }))
  props.room.editDraft({ attachments: next })
}

function onPick(files) {
  sourceOpen.value = false
  picturesOpen.value = false
  addFiles(files)
}

function cycleRole(index) {
  const role = chatNextRole(d.value.attachments, index, mode.value, limits.value)
  props.room.editDraft({ attachments: d.value.attachments.map((a, i) => (i === index ? { ...a, role } : a)) })
}

function removeAttachment(index) {
  props.room.editDraft({ attachments: d.value.attachments.filter((_, i) => i !== index) })
}

// ── the reply ──

const fetchedReply = ref(null)
const replyMessage = computed(() => {
  const id = d.value.reply_to
  if (!id) return null
  return props.room.messages.find((m) => m.id === id) || (fetchedReply.value?.id === id ? fetchedReply.value : null)
})
const replyItem = computed(() => chatItems(replyMessage.value)[Number(d.value.reply_index || 0)] || null)

watch(() => d.value.reply_to, async (id) => {
  if (!id || props.room.messages.some((m) => m.id === id) || fetchedReply.value?.id === id) return
  try {
    fetchedReply.value = await api.get(`/api/chat/messages/${id}`)
  } catch { /* the estimate says why the reply cannot go */ }
}, { immediate: true })

/** Answer a picture or a video of the feed (its own buttons, or dragged onto the input). */
function setReply({ message, index = 0 } = {}) {
  if (!message?.id) return
  const kind = message.kind === 'video' ? 'video' : 'image'
  const item = chatItems(message)[index] || null
  props.room.editDraft({
    reply_to: message.id, reply_index: index, region: null, extend_seconds: null,
    reply: {
      id: message.id, type: message.type, kind, mode: message.mode, index,
      text: String(message.text || '').slice(0, 160), thumb_url: chatFileThumb(item?.file) || null,
    },
  })
  if (kind !== mode.value) props.room.setMode(kind)
  nextTick(focus)
}

function clearReply() {
  props.room.editDraft({ reply_to: null, reply_index: 0, reply: null, region: null, extend_seconds: null })
}

function switchMode(next) {
  if (next === mode.value) return
  if (replyKind.value && replyKind.value !== next) clearReply()
  props.room.setMode(next)
}

// The lengths a video can be extended by (asked from the video module, free).
const extendInfo = ref(null)
const replyRunId = computed(() => (replyKind.value === 'video' ? replyItem.value?.run_id || null : null))
watch(replyRunId, async (runId) => {
  extendInfo.value = null
  if (!runId) return
  try {
    const info = await api.get(`/api/video/runs/${runId}/extend`)
    if (replyRunId.value === runId) extendInfo.value = info
  } catch { /* the estimate says why it cannot be extended */ }
}, { immediate: true })
const extendLengths = computed(() => extendInfo.value?.lengths || [])

// Drag a picture or a video from the feed onto the input to answer it.
function onDragOver(e) {
  if (!e.dataTransfer?.types?.includes(DRAG_TYPE)) return
  e.preventDefault()
  dragging.value = true
}

function onDrop(e) {
  dragging.value = false
  const raw = e.dataTransfer?.getData(DRAG_TYPE)
  if (!raw) return
  e.preventDefault()
  try {
    const { message_id: id, index } = JSON.parse(raw)
    const message = props.room.messages.find((m) => m.id === Number(id))
    if (message) setReply({ message, index: Number(index || 0) })
  } catch { /* not ours */ }
}

// ── price and sending ──

const sendBody = computed(() => chatSendBody({
  mode: replyKind.value || mode.value, text: d.value.text, attachments: d.value.attachments,
  replyTo: d.value.reply_to, replyIndex: d.value.reply_index, enhance: d.value.enhance,
  region: d.value.region, extendSeconds: d.value.extend_seconds,
}))
const canSend = computed(() => chatCanSend({ text: d.value.text, replyKind: replyKind.value }))

// Asked again when the request or the chat's settings change. An empty text is
// priced as one letter so the price is there before typing; the button stays
// off until there is text, and nothing is sent by an estimate.
const price = useVideoPrice(() => {
  const c = chat.value
  if (!c || c.archived) return null
  const body = canSend.value ? sendBody.value : { ...sendBody.value, text: '.' }
  const v = [c.updated_at, c.kit_id, JSON.stringify(c.image_settings), JSON.stringify(c.video_settings),
    replyItem.value?.status || ''].join('|')
  return { body, v }
}, (req) => props.room.askEstimate(req.body), { debounce: 400 })

const estimate = computed(() => price.data.value || null)
const refusal = computed(() => {
  if (estimate.value?.refusal) return chatReasonText(estimate.value.refusal, t, te, estimate.value.refusal_details || {})
  if (price.error.value) return chatErrorText(price.error.value, t, te)
  return ''
})
const sendUsd = computed(() => (estimate.value && !estimate.value.refusal ? Number(estimate.value.usd ?? 0) : null))
const extendValue = computed(() => d.value.extend_seconds ?? estimate.value?.extra?.seconds ?? extendLengths.value[0] ?? null)
const sendReady = computed(() => Boolean(
  chat.value && !chat.value.archived && canSend.value && sendUsd.value !== null && !refusal.value
  && !props.room.isPending('send'),
))

async function submit() {
  if (!sendReady.value) return
  const res = await props.room.send(sendBody.value)
  if (res) {
    emit('sent', res)
    nextTick(autosize)
  }
}

// ── «improve the prompt» ──

const enhanceInfo = computed(() => chat.value?.enhance || {})
const canEnhance = computed(() => !replyKind.value && !hasBase.value)
const enhanceUsd = computed(() => {
  const part = estimate.value?.parts?.enhance
  return d.value.enhance && part ? part : enhanceInfo.value.usd
})
const enhanceTitle = computed(() => (enhanceInfo.value.error
  ? chatReasonText(enhanceInfo.value.error, t, te)
  : t('chat.composer.enhanceHint')))

// ── helpers: random style, «Write it for me», buttons of other modules ──

async function dice() {
  dicing.value = true
  try {
    const res = await api.get('/api/library/styles', { kind: 'style', tab: 'all', limit: 200 })
    const style = chatRandomPick(res?.items || [])
    if (!style) {
      toast.info(t('chat.composer.diceEmpty'))
      return
    }
    const view = await props.room.patchImage({ style: studioStyleSetting({ kind: 'library', id: style.id, title: style.title }) })
    if (view) toast.success(t('chat.composer.diceDone', { name: style.title }))
  } catch (err) {
    toast.error(chatErrorText(err, t, te))
  } finally {
    dicing.value = false
  }
}

function useBrief(brief) {
  briefOpen.value = false
  if (brief) setText(brief)
}

const extraButtons = computed(() => chatComposerButtons(mode.value))
const buttonLabel = (b) => (b.labelKey ? t(b.labelKey) : b.label || b.id)
const buttonContext = () => ({ room: props.room, mode: mode.value, text: d.value.text, draft: d.value, setText, addFiles })

// ── the line under the input ──

const summary = computed(() => {
  if (replyKind.value === 'video') {
    const e = estimate.value
    const parts = [{ key: null, text: t('chat.composer.extending') }]
    if (e?.model_id) parts.push({ key: null, text: modelTitle(e.model_id) || e.model_id })
    if (e?.extra?.resolution) parts.push({ key: null, text: e.extra.resolution })
    if (e?.extra?.length_after) parts.push({ key: null, text: t('chat.composer.lengthAfter', { n: e.extra.length_after }) })
    return parts
  }
  return chatSummaryParts(chat.value, replyKind.value || mode.value, t, { modelTitle, estimate: estimate.value })
})

const videoModel = computed(() => videoModelById(catalog.models.value, chat.value?.video_settings?.model_id))
const warnings = computed(() => {
  const atts = d.value.attachments
  const own = mode.value === 'video' && !replyKind.value
    ? videoAttachWarnings(videoModel.value, {
      first_frame_id: atts.find((a) => a.role === 'first')?.file_id || null,
      references: atts.filter((a) => a.role === 'reference').map((a) => a.file_id),
    })
    : []
  return chatWarnings(own, estimate.value?.warnings || [])
})

defineExpose({ setReply, clearReply, addFiles, setText, focus })
</script>
