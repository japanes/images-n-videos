<template>
  <div class="space-y-4">
    <ToggleSwitch v-model="sub.enabled" :disabled="!sub.words.length" :label="t('clip.subtitles.enabled')" />

    <!-- speech recognition -->
    <section class="space-y-3 rounded-button border border-slate-200 p-3 dark:border-slate-700">
      <h3 class="text-sm font-semibold">{{ sub.words.length ? t('clip.subtitles.againTitle') : t('clip.subtitles.recognizeTitle') }}</h3>
      <p v-if="!sub.words.length" class="text-xs muted">{{ t('clip.subtitles.recognizeHint') }}</p>
      <p v-if="project.source?.has_audio === false" class="rounded-button bg-amber-50 px-2 py-1.5 text-xs text-amber-900 dark:bg-amber-500/10 dark:text-amber-100">
        {{ t('clip.subtitles.noSound') }}
      </p>

      <div class="grid grid-cols-2 gap-2">
        <label class="block">
          <span class="label">{{ t('clip.subtitles.model') }}</span>
          <select v-model="model" class="input" :disabled="!!job">
            <option v-for="name in CLIP_STT_MODELS" :key="name" :value="name">{{ modelLabel(name) }}</option>
          </select>
        </label>
        <label class="block">
          <span class="label">{{ t('clip.subtitles.language') }}</span>
          <select v-model="language" class="input" :disabled="!!job">
            <option v-for="code in CLIP_STT_LANGUAGES" :key="code" :value="code">{{ t(`clip.stt.languages.${code}`) }}</option>
          </select>
        </label>
      </div>
      <p class="text-xs muted">{{ t(`clip.stt.modelHint.${model === 'small' ? 'small' : 'turbo'}`) }}</p>

      <p v-if="estimateText" class="text-xs">{{ estimateText }}</p>
      <p v-if="modelInfo && !modelInfo.downloaded" class="text-xs text-amber-800 dark:text-amber-200">
        {{ modelInfo.downloading ? t('clip.subtitles.modelDownloading') : t('clip.subtitles.modelFirst', { size: sizeText(modelInfo.size_mb) }) }}
      </p>
      <p v-if="sttError" class="text-xs text-rose-700 dark:text-rose-300">{{ sttError }}</p>

      <ClipJobProgress v-if="job" :job="job" :label="phaseText" @cancel="cancel" />
      <div v-else class="flex flex-wrap items-center gap-2">
        <PriceButton
          :usd="0"
          icon="sparkles"
          :variant="sub.words.length ? 'secondary' : 'primary'"
          :busy="starting"
          :label="sub.words.length ? t('clip.subtitles.again') : t('clip.subtitles.recognize')"
          @click="start"
        />
        <button type="button" class="btn-ghost btn-sm" @click="sttOpen = true">{{ t('clip.subtitles.models') }}</button>
      </div>
      <p v-if="jobErrors.transcribe" class="text-xs text-rose-700 dark:text-rose-300">{{ jobErrors.transcribe }}</p>
    </section>

    <!-- look -->
    <section v-if="sub.words.length" class="space-y-3">
      <label class="block">
        <span class="label">{{ t('clip.subtitles.style') }}</span>
        <select v-model="sub.preset_code" class="input">
          <option v-for="p in presets" :key="p.code" :value="p.code">{{ presetName(p) }}</option>
        </select>
      </label>
      <p v-if="preset" class="text-xs muted">{{ presetText(preset) }}</p>
      <div class="grid grid-cols-2 gap-2">
        <label class="block">
          <span class="label">{{ t('clip.subtitles.mode') }}</span>
          <select v-model="sub.mode" class="input">
            <option :value="null">{{ t('clip.subtitles.modes.preset') }}</option>
            <option value="line">{{ t('clip.subtitles.modes.line') }}</option>
            <option value="word">{{ t('clip.subtitles.modes.word') }}</option>
          </select>
        </label>
        <label class="block">
          <span class="label">{{ t('clip.subtitles.position') }}</span>
          <select v-model="sub.position" class="input">
            <option value="">{{ t('clip.subtitles.positions.preset') }}</option>
            <option value="bottom">{{ t('clip.subtitles.positions.bottom') }}</option>
            <option value="middle">{{ t('clip.subtitles.positions.middle') }}</option>
            <option value="top">{{ t('clip.subtitles.positions.top') }}</option>
          </select>
        </label>
      </div>
      <div v-if="preset?.use_brand" class="space-y-2">
        <ClipBrandPicker :hint="t('clip.brand.subtitlesHint')" />
        <p v-if="!project.brand" class="text-xs text-amber-800 dark:text-amber-200">{{ t('clip.subtitles.brandMissing') }}</p>
      </div>
    </section>

    <!-- text -->
    <section v-if="sub.words.length" class="space-y-2">
      <div class="flex items-center gap-2">
        <h3 class="flex-1 text-sm font-semibold">{{ t('clip.subtitles.lines', { n: lines.length }, lines.length) }}</h3>
        <button type="button" class="btn-ghost btn-sm text-rose-600" @click="clear">
          <AppIcon name="trash" :size="14" />{{ t('clip.subtitles.clear') }}
        </button>
      </div>
      <p class="text-xs muted">{{ t('clip.subtitles.editHint') }}</p>
      <ul class="max-h-[22rem] space-y-1 overflow-y-auto pr-1">
        <li
          v-for="(line, i) in lines"
          :key="`${i}:${line[0].start}`"
          class="flex items-start gap-2 rounded-button px-1 py-0.5"
          :class="i === currentLine && 'bg-amber-100/70 dark:bg-amber-500/15'"
        >
          <button type="button" class="mt-1.5 shrink-0 text-[11px] tabular-nums text-primary hover:underline" @click="seek(line[0].start)">
            {{ clipFormatTime(line[0].start) }}
          </button>
          <input
            type="text"
            class="input py-1 text-sm"
            :value="line.map((w) => w.text).join(' ')"
            :aria-label="t('clip.subtitles.lineLabel', { time: clipFormatTime(line[0].start) })"
            @change="editLine(i, $event.target.value)"
          >
        </li>
      </ul>
    </section>

    <ClipSttDialog :open="sttOpen" :model="model" @close="sttOpen = false" @ready="onModelReady" @changed="loadModels" />
  </div>
</template>

<script setup>
import {
  CLIP_STT_LANGUAGES, CLIP_STT_MODELS, clipErrorText, clipFormatTime, clipGroupLines, clipReplaceLine,
  clipRoundSeconds, clipSttModel,
} from '~/utils/clipState.js'

const { t, te } = useI18n()
const api = useApi()
const toast = useToast()
const { confirm } = useConfirm()
const ed = useClipContext()
const { state, project, presets, presetsByCode, jobErrors, time, seek } = ed

const sub = computed(() => state.value.subtitles)
const model = ref(CLIP_STT_MODELS[0])
const language = ref('auto')
const models = ref([])
const sttError = ref('')
const estimate = ref(null)
const starting = ref(false)
const sttOpen = ref(false)
let pendingReplace = false

const job = computed(() => ed.jobOf('transcribe'))
const modelInfo = computed(() => clipSttModel(models.value, model.value))
const preset = computed(() => presetsByCode.value[sub.value.preset_code] || null)
const lines = computed(() => clipGroupLines(sub.value.words, preset.value?.max_words_per_line || 4))
const currentLine = computed(() => {
  const now = time.value
  let found = -1
  lines.value.forEach((line, i) => {
    if (now >= line[0].start && now <= line[line.length - 1].end + 0.35) found = i
  })
  return found
})

function sizeText(mb) {
  const v = Number(mb) || 0
  return v >= 1000 ? t('clip.stt.gb', { n: (v / 1000).toFixed(1) }) : t('clip.stt.mb', { n: Math.round(v) })
}

function modelLabel(name) {
  const base = t(`clip.stt.models.${name === 'small' ? 'small' : 'turbo'}`)
  const info = clipSttModel(models.value, name)
  if (!info) return base
  return info.downloaded ? base : `${base} · ${t('clip.subtitles.notDownloaded', { size: sizeText(info.size_mb) })}`
}

function presetName(p) {
  const key = `clip.presets.${p.code}.name`
  return te(key) ? t(key) : p.name
}

function presetText(p) {
  const key = `clip.presets.${p.code}.text`
  return te(key) ? t(key) : p.description || ''
}

function durationText(seconds) {
  const s = clipRoundSeconds(seconds)
  if (s < 60) return t('clip.subtitles.seconds', { n: s }, s)
  const m = Math.round(s / 60)
  return t('clip.subtitles.minutes', { n: m }, m)
}

const estimateText = computed(() => {
  const e = estimate.value
  if (!e || !e.expected_s) return ''
  const time = durationText(e.expected_s)
  return e.measured
    ? t('clip.subtitles.estimateMeasured', { time, n: e.samples }, e.samples)
    : t('clip.subtitles.estimateGuess', { time })
})

const phaseText = computed(() => {
  const note = job.value?.progress_note
  const key = `clip.stt.phase.${note}`
  return note && te(key) ? t(key) : t('clip.stt.phase.starting')
})

async function loadModels() {
  try {
    const res = await api.get('/api/clip/stt/models')
    models.value = res.items || []
    sttError.value = ''
    return res
  } catch (err) {
    sttError.value = clipErrorText(err, t, te)
    return null
  }
}

async function loadEstimate() {
  if (!ed.projectId.value) return
  try {
    estimate.value = await api.get('/api/clip/stt/estimate', { model: model.value, project_id: ed.projectId.value })
  } catch {
    estimate.value = null
  }
}

watch(model, loadEstimate)
watch(job, (now, before) => {
  // a finished run teaches the estimate and may have downloaded the model
  if (before && !now) {
    loadModels()
    loadEstimate()
  }
})

async function start() {
  if (sub.value.words.length) {
    const ok = await confirm({ message: t('clip.subtitles.againAsk'), confirmLabel: t('clip.subtitles.again') })
    if (!ok) return
    pendingReplace = true
  } else {
    pendingReplace = false
  }
  const info = modelInfo.value
  if (info && !info.downloaded) {
    sttOpen.value = true
    return
  }
  await run()
}

async function run() {
  starting.value = true
  try {
    const replace = pendingReplace
    await ed.transcribe({ model: model.value, language: language.value, force: replace, replace })
  } catch (err) {
    toast.error(clipErrorText(err, t, te))
  } finally {
    starting.value = false
    pendingReplace = false
  }
}

function onModelReady() {
  sttOpen.value = false
  loadModels()
  run()
}

async function cancel() {
  if (!job.value) return
  const ok = await confirm({ message: t('clip.subtitles.cancelAsk'), tone: 'danger', confirmLabel: t('clip.jobs.cancel') })
  if (ok) await ed.cancelJob(job.value)
}

function editLine(index, text) {
  sub.value.words = clipReplaceLine(sub.value.words, preset.value?.max_words_per_line || 4, index, text)
  if (!sub.value.words.length) sub.value.enabled = false
}

async function clear() {
  const ok = await confirm({ message: t('clip.subtitles.clearAsk'), tone: 'danger', confirmLabel: t('clip.subtitles.clear') })
  if (!ok) return
  sub.value.words = []
  sub.value.transcript_id = null
  sub.value.language = null
  sub.value.enabled = false
}

onMounted(async () => {
  const res = await loadModels()
  if (res?.default && CLIP_STT_MODELS.includes(res.default)) model.value = res.default
  if (res?.language && CLIP_STT_LANGUAGES.includes(res.language)) language.value = res.language
  loadEstimate()
})
</script>
