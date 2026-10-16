<template>
  <!--
    The storyboard sheet: one picture with panels, drawn before the video is
    shot. The "shot" text is editable (by default it is the brief), the whole
    text the image model gets is shown before the paid button. The person can
    also use a sheet of their own, and choose whether it goes with the take.
  -->
  <ModalShell :open="open" :title="t('video.storyboard.title')" size="xl" @close="$emit('close')">
    <div class="grid gap-5 lg:grid-cols-[minmax(0,1fr)_280px]">
      <div class="space-y-3 text-sm">
        <label class="block space-y-1">
          <span class="label">{{ t('video.storyboard.shot') }}</span>
          <textarea
            v-model="shot"
            class="input min-h-[7rem]"
            rows="5"
            :maxlength="VIDEO_LIMITS.brief"
            :placeholder="t('video.storyboard.shotPlaceholder')"
            :disabled="busy"
          />
          <span class="flex flex-wrap items-center gap-2 text-xs">
            <span class="muted">{{ t('video.storyboard.shotHelp') }}</span>
            <button
              v-if="preview && shot !== preview.default_shot"
              type="button"
              class="btn-ghost btn-sm"
              :disabled="busy"
              @click="shot = preview.default_shot || ''"
            >
              {{ t('video.storyboard.shotReset') }}
            </button>
          </span>
        </label>

        <div class="flex flex-wrap items-end gap-3">
          <ToggleSwitch v-model="autoPanels" :label="t('video.storyboard.autoPanels')" :disabled="busy" />
          <label v-if="!autoPanels" class="block space-y-1">
            <span class="label">{{ t('video.storyboard.panels') }}</span>
            <input
              v-model.number="panels"
              type="number"
              class="input w-24"
              :min="VIDEO_LIMITS.minPanels"
              :max="VIDEO_LIMITS.maxPanels"
              :disabled="busy"
            >
          </label>
          <span v-if="preview" class="muted text-xs">
            {{ t('video.storyboard.grid', { panels: preview.panels, cols: preview.cols, rows: preview.rows }) }}
          </span>
        </div>

        <details class="rounded-card border border-slate-200 p-3 dark:border-slate-600" open>
          <summary class="cursor-pointer text-xs font-medium">{{ t('video.storyboard.fullText') }}</summary>
          <p v-if="!preview && price.loading.value" class="muted mt-2 text-xs">{{ t('common.loading') }}</p>
          <pre v-else-if="preview" class="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words text-xs">{{ preview.text }}</pre>
        </details>

        <p v-if="preview" class="muted text-xs">
          {{ t('video.storyboard.sent', { count: preview.cast_count, model: preview.model_id, size: preview.image_size }) }}
        </p>
        <p v-if="preview && !preview.ready" class="text-xs text-amber-700 dark:text-amber-300">
          {{ videoReasonText(preview.refusal, t, te, preview.refusal_details || {}) }}
        </p>

        <div class="flex flex-wrap items-center gap-2">
          <PriceButton
            icon="sparkles"
            :label="current ? t('video.storyboard.remake') : t('video.storyboard.make')"
            :usd="preview ? preview.estimate_usd : null"
            :disabled="!preview || !preview.ready"
            :busy="busy"
            @click="make"
          />
          <button type="button" class="btn-secondary btn-sm" :disabled="busy" @click="picking = true">
            <AppIcon name="upload" :size="16" />{{ t('video.storyboard.own') }}
          </button>
        </div>
      </div>

      <aside class="space-y-3 text-sm">
        <span class="label">{{ t('video.storyboard.current') }}</span>
        <EmptyState v-if="!current" icon="image" :title="t('video.storyboard.none')" />
        <template v-else>
          <a :href="current.file ? current.file.url : videoThumbUrl(current.file_id, 1600)" target="_blank" rel="noopener" class="block overflow-hidden rounded-card border border-slate-200 dark:border-slate-600">
            <img :src="videoThumbUrl(current.file_id, 640)" alt="" class="w-full object-contain">
          </a>
          <p class="muted text-xs">
            {{ current.own ? t('video.storyboard.ownSheet') : t('video.storyboard.madeSheet', { panels: current.panels || '' }) }}
          </p>
          <ToggleSwitch
            :model-value="Boolean(current.attached)"
            :label="t('video.storyboard.attach')"
            :disabled="busy"
            @update:model-value="video.attachStoryboard($event)"
          />
          <p class="muted text-xs">{{ t('video.storyboard.attachHelp') }}</p>
          <button type="button" class="btn-ghost btn-sm text-rose-600 dark:text-rose-400" :disabled="busy" @click="clear">
            <AppIcon name="trash" :size="16" />{{ t('video.storyboard.clear') }}
          </button>
        </template>
      </aside>
    </div>

    <StudioSourcePicker :open="picking" :title="t('video.storyboard.own')" @pick="pickOwn" @close="picking = false" />
  </ModalShell>
</template>

<script setup>
import { VIDEO_LIMITS, videoReasonText, videoRunRevision, videoThumbUrl } from '~/utils/videoView.js'

const props = defineProps({
  open: { type: Boolean, default: false },
  // The controller from useVideoRun().
  video: { type: Object, required: true },
})
defineEmits(['close'])
const { t, te } = useI18n()
const { confirm } = useConfirm()

const shot = ref(null) // null until the first answer fills it
const autoPanels = ref(true)
const panels = ref(4)
const picking = ref(false)

const run = computed(() => props.video.run.value || {})
const current = computed(() => run.value.storyboard || null)
const busy = computed(() => props.video.isPending('storyboard'))

function body() {
  const out = {}
  if (shot.value !== null) out.shot = shot.value
  if (!autoPanels.value) {
    const n = Math.round(Number(panels.value) || 0)
    out.panels = Math.max(VIDEO_LIMITS.minPanels, Math.min(VIDEO_LIMITS.maxPanels, n || VIDEO_LIMITS.minPanels))
  }
  return out
}

const price = useVideoPrice(
  () => (props.open && run.value.id ? { ...body(), rev: videoRunRevision(run.value) } : null),
  ({ rev: _rev, ...req }) => props.video.storyboardPreview(req),
)
const preview = computed(() => price.data.value)

// The first answer brings the text to edit (the saved shot, or the brief).
watch(preview, (p) => {
  if (!p) return
  if (shot.value === null) shot.value = p.shot || ''
  if (autoPanels.value) panels.value = p.panels
})
watch(() => props.open, (now) => {
  if (now) { shot.value = null; autoPanels.value = !(current.value && current.value.auto_panels === false) }
})

async function make() {
  await props.video.makeStoryboard(body())
}

async function pickOwn(files) {
  picking.value = false
  const file = (files || [])[0]
  if (file?.id) await props.video.pickStoryboard(file.id)
}

async function clear() {
  const ok = await confirm({ message: t('video.storyboard.clearAsk'), confirmLabel: t('video.storyboard.clear'), tone: 'danger' })
  if (ok) await props.video.clearStoryboard()
}
</script>
