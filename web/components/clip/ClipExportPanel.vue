<template>
  <div class="space-y-4">
    <!-- what will come out -->
    <section class="space-y-1 rounded-button border border-slate-200 p-3 text-sm dark:border-slate-700">
      <div class="flex justify-between gap-2"><span class="muted">{{ t('clip.export.length') }}</span><span class="tabular-nums">{{ clipFormatTime(outputDuration) }}</span></div>
      <div class="flex justify-between gap-2"><span class="muted">{{ t('clip.export.frame') }}</span><span class="tabular-nums">{{ frame.width }} × {{ frame.height }}</span></div>
      <div class="flex justify-between gap-2"><span class="muted">{{ t('clip.export.pieces') }}</span><span class="tabular-nums">{{ segments.length }}</span></div>
      <p v-if="tooMany" class="pt-1 text-xs text-rose-700 dark:text-rose-300">{{ t('clip.errors.clip_too_many_pieces', { max: CLIP_MAX_PIECES }) }}</p>
      <p v-if="!segments.length" class="pt-1 text-xs text-rose-700 dark:text-rose-300">{{ t('clip.errors.clip_empty') }}</p>
    </section>

    <!-- preview render -->
    <section class="space-y-2">
      <h3 class="text-sm font-semibold">{{ t('clip.export.previewTitle') }}</h3>
      <p class="text-xs muted">{{ t('clip.export.previewHint') }}</p>
      <ClipJobProgress v-if="previewJob" :job="previewJob" :label="t('clip.export.previewRunning')" @cancel="cancel(previewJob)" />
      <PriceButton
        v-else
        :usd="0"
        icon="play"
        variant="secondary"
        :busy="busy === 'preview'"
        :disabled="blocked"
        :label="project.preview ? t('clip.export.previewAgain') : t('clip.export.preview')"
        @click="preview"
      />
      <p v-if="jobErrors.preview" class="text-xs text-rose-700 dark:text-rose-300">{{ jobErrors.preview }}</p>
      <video
        v-if="project.preview && !previewJob"
        :key="project.preview.id"
        :src="project.preview.url"
        controls
        preload="metadata"
        class="max-h-72 w-full rounded-button bg-black"
      />
    </section>

    <!-- final export -->
    <section class="space-y-2 border-t border-slate-200 pt-4 dark:border-slate-700">
      <h3 class="text-sm font-semibold">{{ t('clip.export.title') }}</h3>
      <p class="text-xs muted">{{ t('clip.export.hint') }}</p>
      <template v-if="parts.length">
        <ToggleSwitch v-model="exportParts" :label="t('clip.export.parts', { n: parts.length + 1 }, parts.length + 1)" />
        <p class="text-xs muted">{{ t('clip.export.partsHint') }}</p>
      </template>
      <ClipJobProgress v-if="exportJob" :job="exportJob" :label="t('clip.export.running')" @cancel="cancel(exportJob)" />
      <PriceButton
        v-else
        :usd="0"
        icon="download"
        :busy="busy === 'export'"
        :disabled="blocked"
        :label="exportParts && parts.length ? t('clip.export.startParts', { n: parts.length + 1 }, parts.length + 1) : t('clip.export.start')"
        @click="runExport"
      />
      <p v-if="jobErrors.export" class="text-xs text-rose-700 dark:text-rose-300">{{ jobErrors.export }}</p>
      <ul v-if="warnings.length" class="space-y-1">
        <li v-for="w in warnings" :key="w" class="text-xs text-amber-800 dark:text-amber-200">{{ warningText(w) }}</li>
      </ul>
    </section>

    <!-- earlier results -->
    <section class="space-y-2 border-t border-slate-200 pt-4 dark:border-slate-700">
      <h3 class="text-sm font-semibold">{{ t('clip.export.results') }}</h3>
      <p v-if="!exports.length" class="text-sm muted">{{ t('clip.export.noResults') }}</p>
      <ul v-else class="space-y-2">
        <li v-for="item in exports" :key="item.id" class="flex items-center gap-2 rounded-button border border-slate-200 p-2 dark:border-slate-700">
          <div class="flex h-10 w-16 shrink-0 items-center justify-center overflow-hidden rounded bg-slate-100 dark:bg-slate-900">
            <img v-if="item.file?.thumb_url" :src="item.file.thumb_url" alt="" class="max-h-full max-w-full object-contain">
            <AppIcon v-else name="video" :size="18" class="muted" />
          </div>
          <div class="min-w-0 flex-1">
            <p class="truncate text-sm">
              {{ item.file ? mediaDisplayName(item.file) : t('clip.export.deleted') }}
              <span v-if="item.part_count > 1" class="muted">· {{ t('clip.export.part', { i: item.part_index + 1, n: item.part_count }) }}</span>
            </p>
            <p class="text-xs muted tabular-nums">
              {{ clipFormatTime(item.duration || 0) }} · {{ item.width }} × {{ item.height }} · {{ formatDateTime(item.created_at, locale) }}
            </p>
          </div>
          <template v-if="item.file">
            <a :href="`${item.file.url}?download=1`" class="btn-ghost btn-sm" :title="t('common.download')" download>
              <AppIcon name="download" :size="14" />
            </a>
            <NuxtLink :to="`/media?file=${item.file.id}`" class="btn-ghost btn-sm" :title="t('clip.export.openInLibrary')">
              <AppIcon name="media" :size="14" />
            </NuxtLink>
          </template>
        </li>
      </ul>
    </section>
  </div>
</template>

<script setup>
import { formatDateTime } from '~/utils/format.js'
import { CLIP_MAX_PIECES, clipErrorText, clipFormatTime, clipFrameSize, clipPartPoints } from '~/utils/clipState.js'

const { t, te, locale } = useI18n()
const toast = useToast()
const { confirm } = useConfirm()
const ed = useClipContext()
const { state, project, exports, segments, outputDuration, exportParts, jobErrors, lastExport } = ed

const busy = ref('')
const frame = computed(() => clipFrameSize(state.value, project.value?.source))
const parts = computed(() => clipPartPoints(state.value.cuts, segments.value))
const tooMany = computed(() => segments.value.length > CLIP_MAX_PIECES)
const blocked = computed(() => !segments.value.length || tooMany.value)
const previewJob = computed(() => ed.jobOf('preview'))
const exportJob = computed(() => ed.jobOf('export'))
const warnings = computed(() => lastExport.value?.warnings || [])

function warningText(code) {
  const key = `clip.export.warnings.${code}`
  return te(key) ? t(key) : code
}

async function preview() {
  busy.value = 'preview'
  try {
    await ed.startPreview()
  } catch (err) {
    toast.error(clipErrorText(err, t, te))
  } finally {
    busy.value = ''
  }
}

async function runExport() {
  busy.value = 'export'
  try {
    await ed.startExport()
  } catch (err) {
    toast.error(clipErrorText(err, t, te))
  } finally {
    busy.value = ''
  }
}

async function cancel(job) {
  const ok = await confirm({ message: t('clip.export.cancelAsk'), tone: 'danger', confirmLabel: t('clip.jobs.cancel') })
  if (ok) await ed.cancelJob(job)
}
</script>
