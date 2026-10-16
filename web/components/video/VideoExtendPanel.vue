<template>
  <!--
    Making the video longer. Two ways:
      1. Extend: the end of the video goes to the model and comes back with new
         seconds; one piece or a list of pieces (pausing after each by default).
      2. Continue from the last frame: a new take that starts on the last frame.
    Every paid button shows its price (the worst case for a list), and what will
    change is said before pressing: another model, a smaller size.
  -->
  <div class="space-y-4 text-sm">
    <p v-if="!hasVideo" class="muted">{{ t('video.extend.noVideo') }}</p>

    <template v-else>
      <!-- A plan that is on its way or waiting -->
      <section v-if="activePlan" class="space-y-2 rounded-card border border-slate-200 p-3 dark:border-slate-600">
        <div class="flex flex-wrap items-center gap-2">
          <span class="font-medium">{{ t(`video.extend.plan.${activePlan.status}`) }}</span>
          <span class="muted text-xs">{{ t('video.extend.plan.progress', { done: progress.done, total: progress.total }) }}</span>
        </div>
        <ol class="space-y-1">
          <li v-for="(s, i) in activePlan.steps" :key="i" class="flex items-start gap-2 text-xs">
            <span class="badge shrink-0" :class="stepClass(s.status)">{{ t(`video.stepStatuses.${s.status}`) }}</span>
            <span class="min-w-0 flex-1 break-words">
              {{ s.typed === false ? t('video.extend.stepBrief') : s.text }}
              <span class="muted">· {{ t('video.form.seconds', { n: s.seconds }) }}</span>
              <span v-if="s.status === 'error' && s.error_code" class="block text-rose-600 dark:text-rose-400">
                {{ videoReasonText(s.error_code, t, te) }}
              </span>
            </span>
          </li>
        </ol>
        <div class="flex flex-wrap items-center gap-2">
          <button v-if="progress.running" type="button" class="btn-secondary btn-sm" :disabled="video.isPending('stop')" @click="video.stop()">
            <AppIcon name="stop" :size="16" />{{ t('video.extend.stop') }}
          </button>
          <template v-else>
            <PriceButton
              icon="play"
              :label="t('video.extend.next')"
              :usd="restTotal"
              :disabled="restTotal === null || run.busy"
              :busy="video.isPending('extend')"
              @click="video.continuePlan()"
            />
            <button type="button" class="btn-ghost btn-sm" :disabled="video.isPending('drop') || run.busy" @click="video.dropPlan()">
              <AppIcon name="close" :size="16" />{{ t('video.extend.drop') }}
            </button>
          </template>
        </div>
        <p v-if="!progress.running" class="muted text-xs">{{ t('video.extend.restHelp') }}</p>
      </section>

      <!-- Undo the last extension (free) -->
      <div v-if="info.can_undo && !activePlan" class="flex flex-wrap items-center gap-2">
        <PriceButton
          variant="ghost"
          icon="reply"
          :label="t('video.extend.undo')"
          :usd="0"
          :disabled="run.busy"
          :busy="video.isPending('undo')"
          @click="undo"
        />
      </div>

      <!-- A new plan -->
      <section v-if="!activePlan" class="space-y-3">
        <h3 class="font-semibold">{{ t('video.extend.title') }}</h3>
        <p v-if="!info.available && info.reason" class="text-xs text-amber-700 dark:text-amber-300">
          {{ videoReasonText(info.reason, t, te) }}
        </p>

        <label v-if="(info.models || []).length > 1" class="block space-y-1">
          <span class="label">{{ t('video.extend.model') }}</span>
          <select v-model="modelId" class="input" :disabled="run.busy">
            <option v-for="m in info.models" :key="m.id" :value="m.id" :disabled="m.available === false">{{ m.title || m.id }}</option>
          </select>
        </label>

        <div v-if="info.other_model" class="rounded-card bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:bg-amber-500/10 dark:text-amber-100">
          {{ t('video.extend.otherModel', { model: modelTitle(info.model_id) }) }}
        </div>
        <div v-if="info.downscale" class="rounded-card bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:bg-amber-500/10 dark:text-amber-100">
          {{ t('video.extend.downscale', { from: info.source_resolution, to: info.resolution }) }}
        </div>
        <p v-if="info.tail_seconds" class="muted text-xs">
          {{ t('video.extend.tail', { n: videoSeconds(info.tail_seconds), length: videoSeconds(info.source_seconds) }) }}
        </p>

        <ol class="space-y-2">
          <li v-for="(s, i) in steps" :key="s.key" class="space-y-1 rounded-card border border-slate-200 p-2 dark:border-slate-600">
            <div class="flex items-center gap-2">
              <span class="text-xs font-medium">{{ t('video.extend.piece', { n: i + 1 }) }}</span>
              <select v-model.number="s.seconds" class="input ml-auto w-28" :disabled="run.busy" :aria-label="t('video.form.duration')">
                <option v-for="n in lengths" :key="n" :value="n">{{ t('video.form.seconds', { n }) }}</option>
              </select>
              <button
                v-if="steps.length > 1"
                type="button"
                class="btn-ghost btn-sm"
                :title="t('video.extend.removePiece')"
                :aria-label="t('video.extend.removePiece')"
                @click="steps.splice(i, 1)"
              >
                <AppIcon name="trash" :size="16" />
              </button>
            </div>
            <textarea
              v-model="s.text"
              class="input"
              rows="2"
              :maxlength="VIDEO_LIMITS.stepText"
              :placeholder="t('video.extend.whatNext')"
              :disabled="run.busy"
            />
          </li>
        </ol>
        <button
          v-if="steps.length < VIDEO_LIMITS.steps"
          type="button"
          class="btn-ghost btn-sm"
          :disabled="run.busy"
          @click="addStep"
        >
          <AppIcon name="plus" :size="16" />{{ t('video.extend.addPiece') }}
        </button>

        <div v-if="steps.length > 1" class="space-y-1">
          <ToggleSwitch v-model="pauseEach" :label="t('video.extend.pauseEach')" :disabled="run.busy" />
          <p class="muted text-xs">{{ pauseEach ? t('video.extend.pauseOn') : t('video.extend.pauseOff') }}</p>
        </div>

        <div class="flex flex-wrap items-center gap-2">
          <PriceButton
            icon="plus"
            :label="steps.length > 1 ? t('video.extend.startMany', { n: steps.length }) : t('video.extend.start')"
            :usd="planTotal"
            :disabled="!info.available || planTotal === null || run.busy"
            :busy="video.isPending('extend')"
            @click="start"
          />
          <span v-if="planEstimate" class="muted text-xs">
            {{ t('video.extend.lengthAfter', { n: videoSeconds(planEstimate.length_after) }) }}
          </span>
        </div>
        <p v-if="steps.length > 1" class="muted text-xs">{{ t('video.extend.worstCase') }}</p>
        <p v-if="planPrice.error.value" class="text-xs text-rose-600 dark:text-rose-400">
          {{ videoErrorText(planPrice.error.value, t, te) }}
        </p>
      </section>

      <!-- Continue from the last frame -->
      <section v-if="!activePlan" class="space-y-2 border-t border-slate-200 pt-4 dark:border-slate-700">
        <h3 class="font-semibold">{{ t('video.extend.fromLast.title') }}</h3>
        <p class="muted text-xs">{{ t('video.extend.fromLast.help') }}</p>
        <div class="grid gap-2 sm:grid-cols-2">
          <label class="block space-y-1">
            <span class="label">{{ t('video.extend.model') }}</span>
            <select v-model="contModelId" class="input" :disabled="run.busy">
              <option v-for="m in contModels" :key="m.id" :value="m.id">{{ m.title || m.id }}</option>
            </select>
          </label>
          <label class="block space-y-1">
            <span class="label">{{ t('video.form.duration') }}</span>
            <select v-model.number="contSeconds" class="input" :disabled="run.busy">
              <option v-for="n in contLengths" :key="n" :value="n">{{ t('video.form.seconds', { n }) }}</option>
            </select>
          </label>
        </div>
        <textarea
          v-model="contText"
          class="input"
          rows="2"
          :maxlength="VIDEO_LIMITS.stepText"
          :placeholder="t('video.extend.whatNext')"
          :disabled="run.busy"
        />
        <p v-if="contEstimate && contEstimate.downscale" class="text-xs text-amber-700 dark:text-amber-300">
          {{ t('video.extend.downscale', { from: info.source_resolution, to: contEstimate.resolution }) }}
        </p>
        <div class="flex flex-wrap items-center gap-2">
          <PriceButton
            variant="secondary"
            icon="play"
            :label="t('video.extend.fromLast.start')"
            :usd="contEstimate ? contEstimate.estimate_usd : null"
            :disabled="!contEstimate || run.busy || !contModels.length"
            :busy="video.isPending('continue')"
            @click="continueFromLast"
          />
          <span v-if="contEstimate" class="muted text-xs">
            {{ t('video.extend.lengthAfter', { n: videoSeconds(contEstimate.length_after) }) }}
          </span>
        </div>
      </section>
    </template>
  </div>
</template>

<script setup>
import {
  VIDEO_LIMITS, videoDurationsFor, videoErrorText, videoModelById, videoPlanProgress, videoPlanTotal,
  videoReasonText, videoRunRevision, videoSeconds, videoSnapDuration,
} from '~/utils/videoView.js'

const props = defineProps({
  // The controller from useVideoRun().
  video: { type: Object, required: true },
})
const { t, te } = useI18n()
const { confirm } = useConfirm()

const run = computed(() => props.video.run.value || {})
const hasVideo = computed(() => (run.value.versions || []).length > 0)
const baseInfo = computed(() => run.value.extend || {})
const rev = computed(() => videoRunRevision(run.value))

// ── which model extends ─────────────────────────────────────────────────────
const modelId = ref(null) // null = the default one the server picked
const otherInfo = ref(null)
const info = computed(() => (modelId.value && modelId.value !== baseInfo.value.model_id && otherInfo.value
  ? otherInfo.value
  : baseInfo.value))
watch([modelId, rev], async ([id]) => {
  if (!id || id === baseInfo.value.model_id) { otherInfo.value = null; return }
  const res = await props.video.extendInfo(id)
  if (res && id === modelId.value) otherInfo.value = res
})
const lengths = computed(() => info.value.lengths || [])
const modelTitle = (id) => {
  const m = (info.value.models || []).find((x) => x.id === id)
  return m?.title || id || ''
}

// ── the active plan ─────────────────────────────────────────────────────────
const activePlan = computed(() => {
  const plan = baseInfo.value.plan
  return plan && plan.status !== 'done' ? plan : null
})
const progress = computed(() => videoPlanProgress(activePlan.value))
const restSteps = computed(() => (activePlan.value?.steps || [])
  .filter((s) => s.status !== 'done')
  .map((s) => ({ text: s.typed === false ? '' : s.text, seconds: s.seconds })))
const restPrice = useVideoPrice(
  () => (activePlan.value && !progress.value.running && restSteps.value.length
    ? { steps: restSteps.value, model: activePlan.value.model_id, rev: rev.value }
    : null),
  (req) => props.video.extendEstimate(req.steps, req.model),
)
const restTotal = computed(() => videoPlanTotal(restPrice.data.value))

function stepClass(status) {
  return {
    done: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-200',
    running: 'bg-sky-100 text-sky-800 dark:bg-sky-500/15 dark:text-sky-200',
    error: 'bg-rose-100 text-rose-800 dark:bg-rose-500/15 dark:text-rose-200',
  }[status] || 'bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300'
}

// ── a new plan ──────────────────────────────────────────────────────────────
let keySeq = 0
const steps = ref([{ key: ++keySeq, text: '', seconds: null }])
const pauseEach = ref(true)

function addStep() {
  steps.value.push({ key: ++keySeq, text: '', seconds: lengths.value[0] ?? null })
}

// Lengths depend on the model: keep every piece inside what it allows.
watch(lengths, (allowed) => {
  for (const s of steps.value) s.seconds = videoSnapDuration(s.seconds ?? allowed[0], allowed)
}, { immediate: true })

const planPrice = useVideoPrice(
  () => (info.value.available && steps.value.length && steps.value.every((s) => s.seconds)
    ? { steps: steps.value.map((s) => ({ text: s.text, seconds: s.seconds })), model: info.value.model_id, rev: rev.value }
    : null),
  (req) => props.video.extendEstimate(req.steps, req.model),
)
const planEstimate = computed(() => planPrice.data.value)
const planTotal = computed(() => videoPlanTotal(planEstimate.value))

async function start() {
  const res = await props.video.extend(steps.value, { modelId: info.value.model_id, pauseEach: pauseEach.value })
  if (res) steps.value = [{ key: ++keySeq, text: '', seconds: lengths.value[0] ?? null }]
}

async function undo() {
  const ok = await confirm({ message: t('video.extend.undoAsk'), confirmLabel: t('video.extend.undo') })
  if (ok) await props.video.undo()
}

// ── continue from the last frame ────────────────────────────────────────────
const contModels = computed(() => (baseInfo.value.continue_models || []).filter((m) => m.first_frame && m.available !== false))
const contModelId = ref(null)
const contModel = computed(() => videoModelById(contModels.value, contModelId.value))
const contSeconds = ref(null)
const contText = ref('')
watch(contModels, (list) => {
  if (contModelId.value && list.some((m) => m.id === contModelId.value)) return
  contModelId.value = (list.find((m) => m.id === run.value.model_id) || list[0])?.id || null
}, { immediate: true })

const contPrice = useVideoPrice(
  () => (hasVideo.value && contModelId.value && contSeconds.value
    ? { seconds: contSeconds.value, model: contModelId.value, rev: rev.value }
    : null),
  (req) => props.video.continueEstimate(req.seconds, req.model),
)
const contEstimate = computed(() => contPrice.data.value)
const contLengths = computed(() => videoDurationsFor(contModel.value, contEstimate.value?.resolution))
watch(contLengths, (allowed) => {
  contSeconds.value = videoSnapDuration(contSeconds.value ?? run.value.duration, allowed)
}, { immediate: true })

async function continueFromLast() {
  const res = await props.video.continueFromLast(contText.value, contSeconds.value, contModelId.value)
  if (res) contText.value = ''
}
</script>
