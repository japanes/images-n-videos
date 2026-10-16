<template>
  <!-- All frames of a work: progress, "draw all", the pilot of a series, ZIP and the cost so far. -->
  <section class="space-y-4">
    <div class="flex flex-wrap items-center gap-2">
      <span class="text-sm">
        {{ t('studio.grid.progress', { done: progress.done, total: progress.total }) }}
        <template v-if="progress.busy"> · {{ t('studio.grid.busy', { n: progress.busy }) }}</template>
        <span v-if="progress.errors" class="text-rose-600 dark:text-rose-400"> · {{ t('studio.grid.errors', { n: progress.errors }) }}</span>
      </span>
      <SpendCost ref-type="work" :ref-id="work.id" class="muted text-sm" />
      <span class="ml-auto flex flex-wrap items-center gap-2">
        <a
          v-if="progress.done"
          :href="studio.exportUrl.value"
          class="btn-secondary btn-sm"
          download
        ><AppIcon name="download" :size="14" />{{ t('studio.grid.zip') }}</a>
        <PriceButton
          icon="sparkles"
          class="btn-sm"
          :label="t('studio.grid.drawAll')"
          :usd="allPrice.usd.value"
          :busy="studio.isPending('all')"
          :disabled="!allCount"
          @click="drawAll"
        />
      </span>
    </div>
    <p v-if="allPrice.data.value && !allCount && progress.total" class="muted text-xs">{{ t('studio.grid.nothingToDraw') }}</p>

    <!-- Series: the first frame sets the look of the others -->
    <div
      v-if="pilot && !pilot.accepted"
      class="flex flex-wrap items-center gap-3 rounded-card border border-primary/30 bg-primary/5 px-4 py-3 text-sm"
    >
      <AppIcon name="info" :size="18" class="shrink-0 text-primary" />
      <span class="min-w-0 flex-1">{{ pilot.ready ? t('studio.grid.pilotReady') : t('studio.grid.pilotWait') }}</span>
      <PriceButton
        v-if="pilot.ready"
        icon="check"
        class="btn-sm"
        :label="t('studio.grid.pilotAccept')"
        :usd="pilotPrice.usd.value"
        :busy="studio.isPending('pilot')"
        @click="acceptPilot"
      />
    </div>

    <div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
      <StudioFrameCard
        v-for="(f, i) in frames"
        :key="f.id"
        :studio="studio"
        :frame="f"
        :index="i"
        :count="frames.length"
        :aspect="work.aspect"
        @open="$emit('open', $event)"
      />
      <button
        v-if="frames.length < STUDIO_MAX_FRAMES"
        type="button"
        class="card flex min-h-40 flex-col items-center justify-center gap-2 border-2 border-dashed text-sm muted hover:border-primary hover:text-primary"
        :disabled="studio.isPending('add')"
        @click="studio.addFrame()"
      >
        <Spinner v-if="studio.isPending('add')" :size="18" />
        <AppIcon v-else name="plus" :size="22" />
        {{ t('studio.grid.addFrame') }}
      </button>
    </div>
  </section>
</template>

<script setup>
import {
  STUDIO_MAX_FRAMES, studioEstimateRequest, studioReasonText, studioWorkProgress,
} from '~/utils/studioView.js'

const props = defineProps({
  studio: { type: Object, required: true },
})
defineEmits(['open'])
const { t, te } = useI18n()
const toast = useToast()

const work = computed(() => props.studio.work.value || {})
const frames = computed(() => work.value.frames || [])
const progress = computed(() => studioWorkProgress(work.value))
const pilot = computed(() => (work.value.pilot?.frame_id ? work.value.pilot : null))

const allPrice = useStudioEstimate(() => (work.value.id ? studioEstimateRequest('generate_all', { work: work.value }) : null))
const allCount = computed(() => allPrice.data.value?.count || 0)
const pilotPrice = useStudioEstimate(() => (
  pilot.value?.ready ? studioEstimateRequest('accept_pilot', { work: work.value }) : null
))

/** One toast line per reason: "Frame 2, 3: why". */
function reportSkipped(skipped) {
  const byReason = new Map()
  const positions = new Map(frames.value.map((f, i) => [f.id, i + 1]))
  for (const s of skipped || []) {
    // A series without an accepted pilot: the banner already says it.
    if (s.reason === 'pilot_not_ready') continue
    const list = byReason.get(s.reason) || []
    list.push(positions.get(s.frame_id) || '?')
    byReason.set(s.reason, list)
  }
  for (const [reason, list] of byReason) {
    toast.info(t('studio.grid.skipped', { frames: list.join(', '), reason: studioReasonText(reason, t, te) }))
  }
}

async function drawAll() {
  const res = await props.studio.generateAll()
  if (res) reportSkipped(res.skipped)
}

async function acceptPilot() {
  const res = await props.studio.acceptPilot()
  if (res) reportSkipped(res.skipped)
}
</script>
