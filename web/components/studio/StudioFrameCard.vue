<template>
  <article class="card flex flex-col overflow-hidden">
    <header class="flex items-center gap-2 px-3 py-2">
      <span class="text-sm font-medium">{{ t('studio.frame.title', { n: index + 1 }) }}</span>
      <span v-if="frame.is_pilot" class="badge bg-primary/10 text-primary" :title="t('studio.frame.pilotHint')">
        {{ t('studio.frame.pilot') }}
      </span>
      <span class="badge ml-auto" :class="stateClass">{{ t(`studio.statuses.${state}`) }}</span>
    </header>

    <!-- Picture or what is going on -->
    <button
      type="button"
      class="relative mx-3 overflow-hidden rounded-button bg-slate-100 dark:bg-slate-900"
      :style="{ aspectRatio: studioAspectRatio(aspect) }"
      :title="t('studio.frame.open')"
      @click="$emit('open', frame.id)"
    >
      <img v-if="frame.file" :src="frame.file.thumb_url || frame.file.url" alt="" loading="lazy" class="h-full w-full object-cover">
      <span v-else class="absolute inset-0 flex items-center justify-center text-slate-400">
        <AppIcon name="image" :size="32" />
      </span>
      <span v-if="busy" class="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-slate-900/50 px-3 text-center text-sm text-white">
        <Spinner :size="22" />
        <span>{{ state === 'waiting' ? t('studio.frame.waiting') : t(`studio.statuses.${state}`) }}</span>
      </span>
    </button>

    <div class="flex flex-1 flex-col gap-2 p-3">
      <p v-if="frame.status === 'error'" class="flex items-start gap-1.5 text-xs text-rose-600 dark:text-rose-400">
        <AppIcon name="alert" :size="14" class="mt-0.5 shrink-0" />
        <span :title="frameError.detail || undefined">{{ frameError.text }}</span>
      </p>
      <textarea
        v-model="brief"
        rows="3"
        class="input text-sm"
        :maxlength="STUDIO_LIMITS.brief"
        :placeholder="t('studio.frame.briefPlaceholder')"
        :aria-label="t('studio.frame.brief')"
        :disabled="busy"
        @blur="saveBrief"
      />
      <p v-if="blocker" class="muted text-xs">{{ blocker }}</p>

      <div class="mt-auto flex flex-wrap items-center gap-1.5">
        <button v-if="busy" type="button" class="btn-secondary btn-sm" :disabled="studio.isPending(`cancel:${frame.id}`)" @click="studio.cancelFrame(frame.id)">
          <AppIcon name="stop" :size="14" />{{ t('studio.frame.cancel') }}
        </button>
        <PriceButton
          v-else
          class="btn-sm"
          icon="sparkles"
          :label="frame.file ? t('studio.frame.redraw') : t('studio.frame.draw')"
          :usd="shownUsd"
          :busy="studio.isPending(`draw:${frame.id}`)"
          :disabled="!canDraw"
          @click="draw"
        />
        <span class="ml-auto flex items-center">
          <button
            type="button"
            class="btn-ghost p-1.5"
            :disabled="index === 0 || moving"
            :title="t('studio.frame.moveLeft')"
            :aria-label="t('studio.frame.moveLeft')"
            @click="move(-1)"
          ><AppIcon name="chevron-left" :size="16" /></button>
          <button
            type="button"
            class="btn-ghost p-1.5"
            :disabled="index >= count - 1 || moving"
            :title="t('studio.frame.moveRight')"
            :aria-label="t('studio.frame.moveRight')"
            @click="move(1)"
          ><AppIcon name="chevron-right" :size="16" /></button>
          <button
            type="button"
            class="btn-ghost p-1.5 text-rose-600 dark:text-rose-400"
            :disabled="count <= 1 || busy"
            :title="count <= 1 ? t('studio.errors.last_frame') : t('studio.frame.remove')"
            :aria-label="t('studio.frame.remove')"
            @click="remove"
          ><AppIcon name="trash" :size="16" /></button>
        </span>
      </div>
    </div>
  </article>
</template>

<script setup>
import { useDebounceFn } from '@vueuse/core'
import {
  STUDIO_LIMITS, studioAspectRatio, studioEstimateRequest, studioFrameBusy, studioFrameError, studioFrameState,
  studioMoveIds, studioReasonText,
} from '~/utils/studioView.js'

const props = defineProps({
  studio: { type: Object, required: true },
  frame: { type: Object, required: true },
  index: { type: Number, default: 0 },
  count: { type: Number, default: 1 },
  aspect: { type: String, default: '1:1' },
})
defineEmits(['open'])
const { t, te } = useI18n()
const { confirm } = useConfirm()

const brief = ref(props.frame.brief || '')
let sentBrief = null // what we saved last, so our own echo does not reset the field mid-typing
watch(() => props.frame.brief, (v) => {
  if ((v || '') !== sentBrief) brief.value = v || ''
  sentBrief = null
})
const autosave = useDebounceFn(() => saveBrief(), 900)
watch(brief, () => autosave())

const state = computed(() => studioFrameState(props.frame))
const busy = computed(() => studioFrameBusy(props.frame))
const moving = computed(() => props.studio.isPending('order'))
const frameError = computed(() => studioFrameError(props.frame, t, te))

const stateClass = computed(() => ({
  done: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-200',
  error: 'bg-rose-100 text-rose-800 dark:bg-rose-500/15 dark:text-rose-200',
  waiting: 'bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-200',
  drawing: 'bg-sky-100 text-sky-800 dark:bg-sky-500/15 dark:text-sky-200',
  queued: 'bg-sky-100 text-sky-800 dark:bg-sky-500/15 dark:text-sky-200',
}[state.value] || 'bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300'))

const price = useStudioEstimate(() => (busy.value ? null : studioEstimateRequest('frame', { frame: props.frame })))
const priceError = computed(() => price.items.value[0]?.error || null)
const briefTyped = computed(() => brief.value.trim() !== (props.frame.brief || '').trim() && brief.value.trim())
const blocker = computed(() => {
  const code = priceError.value
  if (!code || (code === 'brief_required' && briefTyped.value)) return ''
  return studioReasonText(code, t, te)
})
// A frame that cannot be drawn is priced at 0: show no price rather than "free".
const shownUsd = computed(() => (priceError.value ? null : price.usd.value))
const canDraw = computed(() => !busy.value && !priceError.value && shownUsd.value !== null)

async function saveBrief() {
  const text = brief.value.trim()
  if (text === (props.frame.brief || '').trim()) return true
  sentBrief = text
  return Boolean(await props.studio.patchFrame(props.frame.id, { brief: text }))
}

async function draw() {
  if (!await saveBrief()) return
  await props.studio.startFrame(props.frame.id)
}

function move(step) {
  const ids = (props.studio.work.value?.frames || []).map((f) => f.id)
  props.studio.reorder(studioMoveIds(ids, props.index, props.index + step))
}

async function remove() {
  const ok = await confirm({
    message: t('studio.frame.removeAsk', { n: props.index + 1 }),
    confirmLabel: t('common.delete'),
    tone: 'danger',
  })
  if (ok) await props.studio.deleteFrame(props.frame.id)
}
</script>
