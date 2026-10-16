<template>
  <ModalShell :open="open" :title="title" size="lg" @close="$emit('close')">
    <div class="space-y-4">
      <div v-if="extra.length" class="space-y-2">
        <p class="text-sm font-medium">{{ extraTitle }}</p>
        <div class="grid grid-cols-3 gap-2 sm:grid-cols-5">
          <button
            v-for="item in extra"
            :key="`x${item.id}`"
            type="button"
            class="group overflow-hidden rounded-button border border-slate-200 text-left hover:border-primary dark:border-slate-700"
            @click="$emit('pick', item)"
          >
            <div class="clip-checker flex aspect-square items-center justify-center">
              <img :src="`/files/${item.id}?w=240`" alt="" class="max-h-full max-w-full object-contain">
            </div>
            <p class="truncate px-1.5 py-1 text-xs">{{ item.title || `#${item.id}` }}</p>
          </button>
        </div>
      </div>

      <div class="flex flex-wrap items-end gap-2">
        <label class="block min-w-[10rem] flex-1">
          <span class="label">{{ t('clip.picker.search') }}</span>
          <input v-model="q" type="search" class="input" :placeholder="t('clip.picker.searchHint')">
        </label>
        <button type="button" class="btn-secondary" :disabled="uploading" @click="fileInput?.click()">
          <Spinner v-if="uploading" :size="14" /><AppIcon v-else name="upload" :size="16" />
          {{ uploading ? t('clip.picker.uploading', { pct: Math.round(uploadProgress * 100) }) : t('clip.picker.upload') }}
        </button>
        <input ref="fileInput" type="file" class="hidden" :accept="accept" @change="onUpload">
      </div>

      <p v-if="error" class="rounded-button bg-rose-50 px-3 py-2 text-sm text-rose-800 dark:bg-rose-500/10 dark:text-rose-200">{{ error }}</p>

      <div v-if="loading && !items.length" class="flex justify-center py-8"><Spinner :size="24" /></div>
      <EmptyState v-else-if="!items.length" icon="media" :title="t('clip.picker.empty')" />
      <div v-else class="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <button
          v-for="item in items"
          :key="item.id"
          type="button"
          class="group overflow-hidden rounded-button border border-slate-200 text-left hover:border-primary dark:border-slate-700"
          @click="$emit('pick', item)"
        >
          <div class="flex aspect-video items-center justify-center bg-slate-100 dark:bg-slate-900" :class="kind === 'image' && 'clip-checker'">
            <img v-if="item.thumb_url" :src="item.thumb_url" alt="" class="max-h-full max-w-full object-contain">
            <AppIcon v-else :name="kind === 'audio' ? 'play' : 'video'" :size="28" class="muted" />
          </div>
          <div class="px-1.5 py-1">
            <p class="truncate text-xs font-medium">{{ mediaDisplayName(item) }}</p>
            <p v-if="item.duration" class="text-[11px] muted tabular-nums">{{ formatDuration(item.duration) }}</p>
          </div>
        </button>
      </div>
      <div v-if="items.length < total" class="flex justify-center">
        <button type="button" class="btn-ghost btn-sm" :disabled="loading" @click="loadMore">
          <Spinner v-if="loading" :size="12" />{{ t('clip.picker.more') }}
        </button>
      </div>
    </div>
  </ModalShell>
</template>

<script setup>
import { useDebounceFn } from '@vueuse/core'
import { formatDuration } from '~/utils/format.js'
import { clipErrorText } from '~/utils/clipState.js'

const props = defineProps({
  open: { type: Boolean, default: false },
  kind: { type: String, default: 'image' }, // image | video | audio
  title: { type: String, default: '' },
  extra: { type: Array, default: () => [] }, // [{ id, title }] shown first (brand logos)
  extraTitle: { type: String, default: '' },
})
const emit = defineEmits(['pick', 'close'])
const { t, te } = useI18n()
const api = useApi()

const PAGE = 24
const items = ref([])
const total = ref(0)
const page = ref(1)
const q = ref('')
const loading = ref(false)
const error = ref('')
const uploading = ref(false)
const uploadProgress = ref(0)
const fileInput = ref(null)
const accept = computed(() => `${props.kind}/*`)

async function load(reset = true) {
  loading.value = true
  error.value = ''
  try {
    if (reset) page.value = 1
    const res = await api.get('/api/media/files', { kind: props.kind, q: q.value || undefined, page: page.value, limit: PAGE })
    items.value = reset ? res.items : [...items.value, ...res.items]
    total.value = res.total ?? items.value.length
  } catch (err) {
    error.value = clipErrorText(err, t, te)
  } finally {
    loading.value = false
  }
}

function loadMore() {
  page.value += 1
  load(false)
}

const reload = useDebounceFn(() => load(true), 300)
watch(q, reload)
watch(() => [props.open, props.kind], ([open]) => { if (open) load(true) }, { immediate: true })

async function onUpload(e) {
  const file = e.target.files?.[0]
  e.target.value = ''
  if (!file) return
  uploading.value = true
  uploadProgress.value = 0
  error.value = ''
  try {
    const item = await mediaUploadFile(file, { kinds: [props.kind], onProgress: (p) => { uploadProgress.value = p } })
    emit('pick', item)
  } catch (err) {
    error.value = clipErrorText(err, t, te)
  } finally {
    uploading.value = false
  }
}
</script>

<style scoped>
.clip-checker {
  background-color: #e2e8f0;
  background-image: linear-gradient(45deg, #cbd5e1 25%, transparent 25%), linear-gradient(-45deg, #cbd5e1 25%, transparent 25%),
    linear-gradient(45deg, transparent 75%, #cbd5e1 75%), linear-gradient(-45deg, transparent 75%, #cbd5e1 75%);
  background-size: 12px 12px;
  background-position: 0 0, 0 6px, 6px -6px, -6px 0;
}
</style>
