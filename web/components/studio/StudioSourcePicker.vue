<template>
  <!--
    Pick pictures for the studio: upload new ones (they land in the media
    library) or take ones already there. Emits `pick(files, 'upload' | 'library')`.
  -->
  <ModalShell :open="open" :title="title || t('studio.picker.title')" size="lg" @close="close">
    <div class="mb-4 flex gap-1 border-b border-slate-200 dark:border-slate-700">
      <button
        v-for="tb in ['upload', 'library']"
        :key="tb"
        type="button"
        class="-mb-px border-b-2 px-3 py-2 text-sm"
        :class="tab === tb ? 'border-primary font-medium text-primary' : 'border-transparent muted'"
        @click="tab = tb"
      >
        {{ t(`studio.picker.tabs.${tb}`) }}
      </button>
    </div>

    <!-- Upload -->
    <div v-if="tab === 'upload'" class="space-y-3">
      <label
        class="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-card border-2 border-dashed border-slate-300 px-4 py-10 text-center hover:border-primary dark:border-slate-600"
        :class="uploading && 'pointer-events-none opacity-60'"
        @dragover.prevent
        @drop.prevent="onDrop"
      >
        <AppIcon name="upload" :size="28" />
        <span class="text-sm">{{ multiple ? t('studio.picker.dropMany', { max: limit }) : t('studio.picker.dropOne') }}</span>
        <span class="muted text-xs">{{ t('studio.picker.types') }}</span>
        <input type="file" class="sr-only" :accept="STUDIO_IMAGE_ACCEPT" :multiple="multiple" @change="onInput">
      </label>
      <div v-if="uploading" class="flex items-center gap-2 text-sm">
        <Spinner :size="16" />{{ t('studio.picker.uploading', { percent: Math.round(progress * 100) }) }}
      </div>
    </div>

    <!-- Library -->
    <div v-else class="space-y-3">
      <input
        v-model="query"
        type="search"
        class="input"
        :placeholder="t('studio.picker.search')"
        :aria-label="t('studio.picker.search')"
      >
      <div v-if="loading && !items.length" class="flex justify-center py-10"><Spinner /></div>
      <EmptyState v-else-if="!items.length" icon="image" :title="t('studio.picker.empty')" />
      <div v-else class="grid grid-cols-3 gap-2 sm:grid-cols-5">
        <button
          v-for="item in items"
          :key="item.id"
          type="button"
          class="group relative aspect-square overflow-hidden rounded-button border"
          :class="chosen.includes(item.id) ? 'border-primary ring-2 ring-primary' : 'border-slate-200 dark:border-slate-600'"
          :title="mediaDisplayName(item)"
          @click="choose(item)"
        >
          <img :src="item.thumb_url || item.url" alt="" loading="lazy" class="h-full w-full object-cover">
          <span
            v-if="chosen.includes(item.id)"
            class="absolute right-1 top-1 inline-flex h-5 w-5 items-center justify-center rounded-full bg-primary text-white"
          ><AppIcon name="check" :size="12" /></span>
        </button>
      </div>
      <div v-if="page < pages" class="flex justify-center">
        <button type="button" class="btn-ghost btn-sm" :disabled="loading" @click="loadPage(page + 1)">
          {{ t('studio.picker.more') }}
        </button>
      </div>
    </div>

    <template v-if="tab === 'library' && multiple" #footer>
      <span class="muted mr-auto text-sm">{{ t('studio.picker.chosen', { n: chosen.length, max: limit }) }}</span>
      <button type="button" class="btn-secondary" @click="close">{{ t('common.cancel') }}</button>
      <button type="button" class="btn-primary" :disabled="!chosen.length" @click="done">{{ t('studio.picker.take') }}</button>
    </template>
  </ModalShell>
</template>

<script setup>
import { useDebounceFn } from '@vueuse/core'
import { STUDIO_IMAGE_ACCEPT, studioErrorText } from '~/utils/studioView.js'

const props = defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, default: '' },
  multiple: { type: Boolean, default: false },
  max: { type: Number, default: 1 },
})
const emit = defineEmits(['pick', 'close'])
const { t, te } = useI18n()
const api = useApi()
const toast = useToast()

const PAGE = 30
const tab = ref('upload')
const items = ref([])
const page = ref(1)
const pages = ref(1)
const loading = ref(false)
const query = ref('')
const chosen = ref([])
const chosenItems = ref([])
const uploading = ref(false)
const progress = ref(0)
let seq = 0

const limit = computed(() => (props.multiple ? Math.max(1, props.max) : 1))

async function loadPage(n = 1) {
  const mine = ++seq
  loading.value = true
  try {
    const res = await api.get('/api/media/files', { kind: 'image', page: n, limit: PAGE, q: query.value || undefined })
    if (mine !== seq) return
    items.value = n === 1 ? (res.items || []) : [...items.value, ...(res.items || [])]
    page.value = res.page || n
    pages.value = res.pages || 1
  } catch (err) {
    if (mine === seq) toast.error(studioErrorText(err, t, te))
  } finally {
    if (mine === seq) loading.value = false
  }
}

const search = useDebounceFn(() => loadPage(1), 300)
watch(query, search)
watch(() => [props.open, tab.value], ([open, tb]) => {
  if (open && tb === 'library' && !items.value.length) loadPage(1)
})
watch(() => props.open, (open) => {
  if (open) { chosen.value = []; chosenItems.value = [] }
})

function choose(item) {
  if (!props.multiple) { emit('pick', [item], 'library'); return }
  const at = chosen.value.indexOf(item.id)
  if (at >= 0) {
    chosen.value = chosen.value.filter((id) => id !== item.id)
    chosenItems.value = chosenItems.value.filter((i) => i.id !== item.id)
  } else if (chosen.value.length < limit.value) {
    chosen.value = [...chosen.value, item.id]
    chosenItems.value = [...chosenItems.value, item]
  } else {
    toast.info(t('studio.picker.full', { max: limit.value }))
  }
}

function done() {
  if (chosenItems.value.length) emit('pick', chosenItems.value, 'library')
}

function close() {
  if (!uploading.value) emit('close')
}

async function upload(list) {
  const fileList = [...(list || [])].slice(0, limit.value)
  if (!fileList.length) return
  uploading.value = true
  const got = []
  try {
    for (const [i, file] of fileList.entries()) {
      progress.value = i / fileList.length
      try {
        got.push(await mediaUploadFile(file, {
          kinds: ['image'],
          onProgress: (f) => { progress.value = (i + f) / fileList.length },
        }))
      } catch (err) {
        toast.error(`${file.name}: ${studioErrorText(err, t, te)}`)
      }
    }
  } finally {
    uploading.value = false
    progress.value = 0
  }
  if (got.length) emit('pick', got, 'upload')
}

const onInput = (e) => { upload(e.target.files); e.target.value = '' }
const onDrop = (e) => upload(e.dataTransfer?.files)
</script>
