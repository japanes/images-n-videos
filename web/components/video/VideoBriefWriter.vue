<template>
  <!--
    The text of the video: niche, platform and the brief that goes to the video
    model word for word. «Write it for me» shows its price in two parts (the
    brief and the market read), asks before it replaces typed text and can bring
    the previous text back. Changes are saved on their own after a short pause.
  -->
  <div class="space-y-3 text-sm">
    <div class="grid gap-2 sm:grid-cols-2">
      <label class="block space-y-1">
        <span class="label">{{ t('video.brief.niche') }}</span>
        <input
          class="input"
          :value="run.niche || ''"
          :maxlength="VIDEO_LIMITS.niche"
          :placeholder="t('video.brief.nichePlaceholder')"
          :disabled="disabled"
          @input="video.edit({ niche: $event.target.value })"
        >
      </label>
      <label class="block space-y-1">
        <span class="label">{{ t('video.brief.platform') }}</span>
        <input
          class="input"
          :value="run.platform || ''"
          :maxlength="VIDEO_LIMITS.platform"
          :placeholder="t('video.brief.platformPlaceholder')"
          :disabled="disabled"
          @input="video.edit({ platform: $event.target.value })"
        >
      </label>
    </div>

    <label class="block space-y-1">
      <span class="label">{{ t('video.brief.label') }}</span>
      <textarea
        class="input min-h-[8rem]"
        rows="6"
        :value="run.brief || ''"
        :maxlength="VIDEO_LIMITS.brief"
        :placeholder="t('video.brief.placeholder')"
        :disabled="disabled || busy"
        @input="video.edit({ brief: $event.target.value })"
      />
      <span class="muted block text-xs">{{ t('video.brief.verbatim') }}</span>
    </label>

    <div class="space-y-2 rounded-card border border-slate-200 p-3 dark:border-slate-600">
      <ToggleSwitch v-model="research" :label="t('video.brief.research')" :disabled="disabled || busy" />
      <p class="muted text-xs">{{ research ? t('video.brief.researchOn') : t('video.brief.researchOff') }}</p>
      <p v-if="estimate && estimate.research_cached" class="muted text-xs">
        {{ t('video.brief.researchCached', { date: cachedAt }) }}
      </p>
      <p v-if="estimate && estimate.niche_needed" class="text-xs text-amber-700 dark:text-amber-300">
        {{ t('video.brief.nicheNeeded') }}
      </p>
      <p v-if="estimate && estimate.photo" class="muted text-xs">{{ t('video.brief.withPhoto') }}</p>

      <div class="flex flex-wrap items-center gap-2">
        <PriceButton
          icon="sparkles"
          :label="t('video.brief.write')"
          :usd="estimate ? estimate.total_usd : null"
          :disabled="disabled || !canWrite"
          :busy="busy"
          @click="write()"
        />
        <button
          v-if="info.can_restore"
          type="button"
          class="btn-ghost btn-sm"
          :disabled="disabled || busy"
          @click="video.restoreBrief()"
        >
          <AppIcon name="reply" :size="16" />{{ t('video.brief.restore') }}
        </button>
      </div>
      <p v-if="estimate" class="muted text-xs">
        {{ t('video.brief.priceParts', { brief: usd(estimate.brief_usd), research: usd(estimate.research_usd) }) }}
      </p>
      <p v-else-if="price.loading.value" class="muted text-xs">{{ t('common.loading') }}</p>
    </div>

    <div
      v-if="info.duration_changed"
      class="flex flex-wrap items-center gap-2 rounded-card bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:bg-amber-500/10 dark:text-amber-100"
    >
      <span class="min-w-0 flex-1">
        {{ t('video.brief.durationChanged', { was: info.written_for_seconds, now: run.duration }) }}
      </span>
      <PriceButton
        variant="secondary"
        icon="refresh"
        :label="t('video.brief.rewrite', { n: run.duration })"
        :usd="estimate ? estimate.total_usd : null"
        :disabled="disabled || !canWrite"
        :busy="busy"
        @click="write()"
      />
    </div>

    <div
      v-if="suggested"
      class="flex flex-wrap items-center gap-2 rounded-card border border-slate-200 px-3 py-2 text-xs dark:border-slate-600"
    >
      <AppIcon name="video" :size="16" class="opacity-70" />
      <span class="min-w-0 flex-1">{{ t('video.brief.cameraSuggested', { move: moveLabel(suggested) }) }}</span>
      <button type="button" class="btn-secondary btn-sm" :disabled="disabled || video.isPending('camera')" @click="video.applyCamera()">
        {{ t('video.brief.cameraApply') }}
      </button>
    </div>

    <p v-if="info.research_error" class="text-xs text-amber-700 dark:text-amber-300">
      {{ t('video.brief.researchFailed') }}
    </p>
  </div>
</template>

<script setup>
import { formatDateTime, formatUsd } from '~/utils/format.js'
import { VIDEO_LIMITS, videoHasText, videoRunRevision } from '~/utils/videoView.js'

const props = defineProps({
  // The controller from useVideoRun().
  video: { type: Object, required: true },
  disabled: { type: Boolean, default: false },
})
const { t, te, locale } = useI18n()
const { confirm } = useConfirm()
const toast = useToast()

const research = ref(true)
const run = computed(() => props.video.run.value || {})
const info = computed(() => run.value.brief_info || {})
const busy = computed(() => props.video.isPending('brief'))

const price = useVideoPrice(
  () => (run.value.id ? { research: research.value, rev: videoRunRevision(run.value) } : null),
  (req) => props.video.briefEstimate(req.research),
)
const estimate = computed(() => price.data.value)
const canWrite = computed(() => Boolean(estimate.value) && !estimate.value.niche_needed && !busy.value)
const cachedAt = computed(() => formatDateTime(estimate.value?.research_cached_at, locale.value))
const suggested = computed(() => {
  const code = info.value.camera_move_suggested
  return code && code !== run.value.camera_move ? code : ''
})

const usd = (v) => (Number(v) ? formatUsd(v, { approx: true }) : t('common.free'))
const moveLabel = (code) => (te(`video.cameraMove.moves.${code}`) ? t(`video.cameraMove.moves.${code}`) : code)

async function write() {
  let force = false
  if (videoHasText(run.value.brief)) {
    const ok = await confirm({ message: t('video.brief.replaceAsk'), confirmLabel: t('video.brief.replace') })
    if (!ok) return
    force = true
  }
  const result = await props.video.writeBrief({ research: research.value, force })
  if (result?.research_error) toast.info(t('video.brief.researchFailed'))
}
</script>
