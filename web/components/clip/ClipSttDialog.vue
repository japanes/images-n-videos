<template>
  <ModalShell :open="open" :title="t('clip.stt.title')" @close="$emit('close')">
    <div class="space-y-4">
      <p class="text-sm">{{ t('clip.stt.intro') }}</p>

      <div v-if="loading && !items.length" class="flex justify-center py-6"><Spinner :size="22" /></div>
      <p v-if="error" class="rounded-button bg-rose-50 px-3 py-2 text-sm text-rose-800 dark:bg-rose-500/10 dark:text-rose-200">{{ error }}</p>

      <div
        v-for="m in shown"
        :key="m.name"
        class="space-y-2 rounded-button border p-3"
        :class="m.name === model ? 'border-primary' : 'border-slate-200 dark:border-slate-700'"
      >
        <div class="flex flex-wrap items-center gap-2">
          <div class="min-w-0 flex-1">
            <p class="text-sm font-medium">{{ t(`clip.stt.models.${modelKey(m.name)}`) }}</p>
            <p class="text-xs muted">{{ t('clip.stt.size', { size: sizeText(m.size_mb) }) }}</p>
          </div>
          <span v-if="m.downloaded" class="badge bg-emerald-100 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-200">
            <AppIcon name="check" :size="12" />{{ t('clip.stt.ready') }}
          </span>
          <button
            v-if="m.downloaded"
            type="button"
            class="btn-ghost btn-sm text-rose-600"
            :disabled="busyName === m.name"
            @click="removeModel(m)"
          >
            <AppIcon name="trash" :size="14" />{{ t('clip.stt.delete') }}
          </button>
          <button
            v-else-if="!m.downloading"
            type="button"
            class="btn-primary btn-sm"
            :disabled="busyName === m.name || anyDownloading"
            @click="download(m)"
          >
            <Spinner v-if="busyName === m.name" :size="12" /><AppIcon v-else name="download" :size="14" />
            {{ t('clip.stt.download', { size: sizeText(m.size_mb) }) }}
          </button>
        </div>

        <div v-if="m.downloading" class="space-y-1">
          <div class="h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
            <div class="h-full bg-primary transition-[width]" :style="{ width: `${Math.round((m.progress || 0) * 100)}%` }" />
          </div>
          <p class="text-xs muted tabular-nums">
            {{ t('clip.stt.downloading', { pct: Math.round((m.progress || 0) * 100), done: sizeText((m.progress || 0) * m.size_mb), size: sizeText(m.size_mb) }) }}
          </p>
        </div>
        <p v-if="m.error && !m.downloading" class="text-xs text-rose-700 dark:text-rose-300">{{ t('clip.stt.failed') }}</p>
      </div>

      <p class="text-xs muted">{{ t('clip.stt.where') }}</p>
    </div>
    <template #footer>
      <button type="button" class="btn-ghost" @click="$emit('close')">{{ t('common.close') }}</button>
      <button v-if="current?.downloaded" type="button" class="btn-primary" @click="$emit('ready', model)">
        {{ t('clip.stt.continue') }}
      </button>
    </template>
  </ModalShell>
</template>

<script setup>
import { clipErrorText, clipSttModel } from '~/utils/clipState.js'

const props = defineProps({
  open: { type: Boolean, default: false },
  model: { type: String, default: '' }, // the model the person wants to use now
})
const emit = defineEmits(['close', 'ready', 'changed'])
const { t, te } = useI18n()
const api = useApi()
const { confirm } = useConfirm()

const items = ref([])
const loading = ref(false)
const error = ref('')
const busyName = ref('')
let timer = null
let wasDownloading = false

const shown = computed(() => {
  // the wanted model first, the other one below it for housekeeping
  const list = [...items.value]
  return list.sort((a, b) => (a.name === props.model ? -1 : b.name === props.model ? 1 : 0))
})
const current = computed(() => clipSttModel(items.value, props.model))
const anyDownloading = computed(() => items.value.some((m) => m.downloading))

const modelKey = (name) => (name === 'small' ? 'small' : 'turbo')

function sizeText(mb) {
  const v = Number(mb) || 0
  return v >= 1000 ? t('clip.stt.gb', { n: (v / 1000).toFixed(1) }) : t('clip.stt.mb', { n: Math.round(v) })
}

async function load() {
  loading.value = true
  try {
    const res = await api.get('/api/clip/stt/models')
    items.value = res.items || []
    error.value = ''
    const downloading = anyDownloading.value
    if (wasDownloading && !downloading) {
      emit('changed')
      if (current.value?.downloaded) emit('ready', props.model)
    }
    wasDownloading = downloading
  } catch (err) {
    error.value = clipErrorText(err, t, te)
  } finally {
    loading.value = false
  }
}

function poll() {
  clearInterval(timer)
  timer = setInterval(() => {
    if (props.open) load()
  }, 1000)
}

async function download(m) {
  busyName.value = m.name
  error.value = ''
  try {
    await api.post(`/api/clip/stt/models/${encodeURIComponent(m.name)}/download`)
    wasDownloading = true
    await load()
    poll()
  } catch (err) {
    error.value = clipErrorText(err, t, te)
  } finally {
    busyName.value = ''
  }
}

async function removeModel(m) {
  const ok = await confirm({ message: t('clip.stt.deleteAsk', { size: sizeText(m.size_mb) }), tone: 'danger',
    confirmLabel: t('clip.stt.delete') })
  if (!ok) return
  busyName.value = m.name
  try {
    await api.del(`/api/clip/stt/models/${encodeURIComponent(m.name)}`)
    await load()
    emit('changed')
  } catch (err) {
    error.value = clipErrorText(err, t, te)
  } finally {
    busyName.value = ''
  }
}

watch(() => props.open, async (open) => {
  clearInterval(timer)
  timer = null
  if (!open) return
  await load()
  wasDownloading = anyDownloading.value
  if (wasDownloading) poll()
}, { immediate: true })

watch(anyDownloading, (on) => {
  if (on && props.open && !timer) poll()
  if (!on && timer && !busyName.value) {
    clearInterval(timer)
    timer = null
  }
})

onBeforeUnmount(() => clearInterval(timer))
</script>
