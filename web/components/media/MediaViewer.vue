<template>
  <ModalShell :open="open && !!item" size="full" body-class="p-0" @close="$emit('close')">
    <template #header>
      <div class="flex min-w-0 flex-1 items-center gap-2">
        <h2 class="min-w-0 truncate text-base font-semibold" :title="name">{{ name }}</h2>
        <span v-if="position" class="shrink-0 text-xs tabular-nums muted">{{ position }}</span>
      </div>
      <button
        type="button"
        class="btn-ghost p-1.5"
        :disabled="!hasPrev"
        :title="t('media.viewer.prev')"
        :aria-label="t('media.viewer.prev')"
        @click="$emit('prev')"
      >
        <AppIcon name="play" :size="16" class="rotate-180" />
      </button>
      <button
        type="button"
        class="btn-ghost p-1.5"
        :disabled="!hasNext"
        :title="t('media.viewer.next')"
        :aria-label="t('media.viewer.next')"
        @click="$emit('next')"
      >
        <AppIcon name="play" :size="16" />
      </button>
    </template>

    <div v-if="file" class="flex h-full min-h-0 flex-col lg:flex-row">
      <div class="flex min-h-[40vh] flex-1 items-center justify-center bg-slate-950 p-3 lg:min-h-0">
        <img
          v-if="file.kind === 'image'"
          :key="`i${file.id}`"
          :src="file.url"
          :alt="name"
          class="max-h-[70vh] max-w-full object-contain lg:max-h-full"
        >
        <video
          v-else-if="file.kind === 'video'"
          :key="`v${file.id}`"
          :src="file.url"
          :poster="file.thumb_url || undefined"
          controls
          preload="metadata"
          class="max-h-[70vh] max-w-full lg:max-h-full"
        />
        <div v-else-if="file.kind === 'audio'" class="flex w-full max-w-md flex-col items-center gap-6 text-slate-400">
          <MediaAudioGlyph :size="72" />
          <audio :key="`a${file.id}`" :src="file.url" controls preload="metadata" class="w-full" />
        </div>
        <AppIcon v-else name="paperclip" :size="48" class="text-slate-500" />
      </div>

      <aside class="w-full shrink-0 space-y-5 overflow-y-auto border-t border-slate-200 p-5 dark:border-slate-700 lg:w-96 lg:border-l lg:border-t-0">
        <form class="space-y-2" @submit.prevent="saveTitle">
          <label class="block">
            <span class="label">{{ t('media.viewer.name') }}</span>
            <input
              v-model="titleDraft"
              type="text"
              class="input"
              maxlength="200"
              :placeholder="file.original_name || ''"
            >
          </label>
          <div v-if="titleChanged" class="flex gap-2">
            <button type="submit" class="btn-primary btn-sm" :disabled="saving">
              <Spinner v-if="saving" :size="12" />{{ t('common.save') }}
            </button>
            <button type="button" class="btn-ghost btn-sm" :disabled="saving" @click="resetTitle">{{ t('common.cancel') }}</button>
          </div>
          <p class="text-xs muted">{{ t('media.viewer.nameHint') }}</p>
        </form>

        <dl class="grid grid-cols-[auto,1fr] gap-x-4 gap-y-1.5 text-sm">
          <dt class="muted">{{ t('media.viewer.type') }}</dt>
          <dd>{{ t(`media.kinds.${file.kind}`) }}<span v-if="file.ext"> · {{ file.ext.toUpperCase() }}</span></dd>
          <template v-if="sizeText">
            <dt class="muted">{{ t('media.viewer.dimensions') }}</dt>
            <dd class="tabular-nums">{{ sizeText }}</dd>
          </template>
          <template v-if="file.duration">
            <dt class="muted">{{ t('media.viewer.duration') }}</dt>
            <dd class="tabular-nums">{{ formatDuration(file.duration) }}</dd>
          </template>
          <dt class="muted">{{ t('media.viewer.fileSize') }}</dt>
          <dd class="tabular-nums">{{ formatBytes(file.size_bytes) }}</dd>
          <dt class="muted">{{ t('media.viewer.added') }}</dt>
          <dd>{{ formatDateTime(file.created_at, locale) }}</dd>
          <template v-if="file.source_group">
            <dt class="muted">{{ t('media.viewer.source') }}</dt>
            <dd>{{ t(`media.sources.${file.source_group}`) }}</dd>
          </template>
          <template v-if="file.title && file.original_name">
            <dt class="muted">{{ t('media.viewer.originalName') }}</dt>
            <dd class="min-w-0 break-words">{{ file.original_name }}</dd>
          </template>
        </dl>

        <section v-if="file.kind === 'video' || file.kind === 'audio'" class="space-y-2">
          <h3 class="text-sm font-semibold">{{ t('media.ingest.title') }}</h3>
          <p v-if="ingestBusy" class="flex items-center gap-2 text-sm muted">
            <Spinner :size="14" />{{ t(file.kind === 'video' ? 'media.ingest.busyVideo' : 'media.ingest.busyAudio') }}
          </p>
          <div
            v-else-if="ingestFailed"
            class="space-y-1 rounded-button bg-rose-50 px-3 py-2 text-sm text-rose-800 dark:bg-rose-500/10 dark:text-rose-200"
          >
            <p>{{ t('media.ingest.failed') }}</p>
            <p class="text-xs opacity-80">{{ ingestErrorText }}</p>
          </div>
          <p v-else-if="ingestDone" class="text-sm muted">
            {{ t(file.kind === 'video' ? 'media.ingest.doneVideo' : 'media.ingest.doneAudio') }}
          </p>
          <p v-else class="text-sm muted">{{ t('media.ingest.none') }}</p>
          <button v-if="!ingestBusy" type="button" class="btn-secondary btn-sm" :disabled="reingesting" @click="reingest">
            <Spinner v-if="reingesting" :size="12" /><AppIcon v-else name="refresh" :size="14" />
            {{ t('media.ingest.again') }}
          </button>
        </section>

        <section class="space-y-2">
          <h3 class="text-sm font-semibold">{{ t('media.usages.title') }}</h3>
          <div v-if="loading" class="flex items-center gap-2 text-sm muted"><Spinner :size="14" />{{ t('common.loading') }}</div>
          <p v-else-if="loadError" class="text-sm text-rose-700 dark:text-rose-300">{{ loadError }}</p>
          <p
            v-else-if="usages === null"
            class="flex gap-2 rounded-button bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:bg-amber-500/10 dark:text-amber-200"
          >
            <AppIcon name="alert" :size="16" class="mt-0.5" />{{ t('media.usages.unknown') }}
          </p>
          <p v-else-if="!usages.length" class="text-sm muted">{{ t('media.usages.none') }}</p>
          <template v-else>
            <p class="text-sm muted">{{ t('media.usages.blocked') }}</p>
            <ul class="space-y-1">
              <li v-for="(u, i) in usages" :key="`${u.type}-${u.id}-${i}`" class="flex items-center gap-2 text-sm">
                <span class="badge shrink-0 bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300">{{ usageTypeLabel(u.type) }}</span>
                <NuxtLink v-if="mediaUsageLink(u)" :to="mediaUsageLink(u)" class="min-w-0 truncate text-primary hover:underline" @click="$emit('close')">
                  {{ u.title || `#${u.id}` }}
                </NuxtLink>
                <span v-else class="min-w-0 truncate">{{ u.title || `#${u.id}` }}</span>
              </li>
            </ul>
          </template>
        </section>
      </aside>
    </div>

    <template #footer>
      <a v-if="file" :href="`${file.url}?download=1`" class="btn-secondary" download>
        <AppIcon name="download" :size="16" />{{ t('common.download') }}
      </a>
      <button
        type="button"
        class="btn-danger"
        :disabled="!canDelete || deleting"
        :title="deleteHint"
        @click="remove"
      >
        <Spinner v-if="deleting" :size="14" /><AppIcon v-else name="trash" :size="16" />{{ t('common.delete') }}
      </button>
    </template>
  </ModalShell>
</template>

<script setup>
import { useEventListener } from '@vueuse/core'
import { apiErrorText } from '~/utils/apiErrorText.js'
import { formatBytes, formatDateTime, formatDuration } from '~/utils/format.js'
import {
  mediaDisplayName, mediaIngestBusy, mediaIngestFailed, mediaSizeText, mediaUsageLink,
} from '~/composables/useMediaLibrary.js'

const props = defineProps({
  open: { type: Boolean, default: false },
  // The file as the list knows it (kept fresh by the page from live events).
  item: { type: Object, default: null },
  hasPrev: { type: Boolean, default: false },
  hasNext: { type: Boolean, default: false },
  position: { type: String, default: '' },
})
const emit = defineEmits(['close', 'prev', 'next', 'updated', 'deleted', 'missing'])

const { t, te, locale } = useI18n()
const api = useApi()
const toast = useToast()
const { confirm } = useConfirm()

const detail = ref(null)
const loading = ref(false)
const loadError = ref('')
const titleDraft = ref('')
const saving = ref(false)
const deleting = ref(false)
const reingesting = ref(false)

// Live fields from the list win; usages come from the detail request.
const file = computed(() => {
  if (!props.item) return null
  const own = detail.value && detail.value.id === props.item.id ? detail.value : {}
  return { ...own, ...props.item }
})
const usages = computed(() => (detail.value && detail.value.id === props.item?.id ? detail.value.usages : undefined))
const name = computed(() => mediaDisplayName(file.value))
const sizeText = computed(() => mediaSizeText(file.value))
const ingestBusy = computed(() => mediaIngestBusy(file.value))
const ingestFailed = computed(() => mediaIngestFailed(file.value))
const ingestDone = computed(() => file.value?.ingest?.status === 'done')
const ingestErrorText = computed(() => {
  const ing = file.value?.ingest || {}
  return apiErrorText({ code: ing.error_code || 'render_failed', message: ing.error || '' }, t, te)
})
const titleChanged = computed(() => (titleDraft.value.trim() || null) !== (file.value?.title || null))
const canDelete = computed(() => !loading.value && !loadError.value && Array.isArray(usages.value) && !usages.value.length)
const deleteHint = computed(() => {
  if (usages.value === null) return t('media.usages.unknown')
  if (Array.isArray(usages.value) && usages.value.length) return t('media.usages.blocked')
  return ''
})

const usageTypeLabel = (type) => (te(`media.usageTypes.${type}`) ? t(`media.usageTypes.${type}`) : type)

let loadSeq = 0
async function load(id) {
  const seq = ++loadSeq
  loading.value = true
  loadError.value = ''
  try {
    const res = await api.get(`/api/media/files/${id}`)
    if (seq !== loadSeq) return
    detail.value = res
  } catch (err) {
    if (seq !== loadSeq) return
    if (err.status === 404) emit('missing', id)
    else loadError.value = apiErrorText(err, t, te)
  } finally {
    if (seq === loadSeq) loading.value = false
  }
}

function resetTitle() {
  titleDraft.value = file.value?.title || ''
}

watch(() => (props.open ? props.item?.id : null), (id) => {
  if (!id) return
  detail.value = null
  resetTitle()
  load(id)
}, { immediate: true })

// The name follows renames made elsewhere (another tab, another screen).
watch(() => props.item?.title, () => { if (!saving.value) resetTitle() })

async function saveTitle() {
  if (!titleChanged.value || !file.value) return
  saving.value = true
  try {
    const res = await api.patch(`/api/media/files/${file.value.id}`, { title: titleDraft.value.trim() || null })
    detail.value = res
    emit('updated', res)
    titleDraft.value = res.title || ''
    toast.success(t('common.saved'))
  } catch (err) {
    toast.error(apiErrorText(err, t, te))
  } finally {
    saving.value = false
  }
}

async function reingest() {
  if (!file.value) return
  reingesting.value = true
  try {
    await api.post(`/api/media/files/${file.value.id}/ingest`)
    emit('updated', { ...file.value, ingest: { ...(file.value.ingest || {}), status: 'queued', error_code: null, error: null } })
  } catch (err) {
    toast.error(apiErrorText(err, t, te))
  } finally {
    reingesting.value = false
  }
}

async function remove() {
  const target = file.value
  if (!target || !canDelete.value) return
  const ok = await confirm({
    title: t('media.delete.oneTitle'),
    message: t('media.delete.oneAsk', { name: mediaDisplayName(target) }),
    tone: 'danger',
    confirmLabel: t('common.delete'),
  })
  if (!ok) return
  deleting.value = true
  try {
    await api.del(`/api/media/files/${target.id}`)
    toast.success(t('media.delete.doneOne'))
    emit('deleted', target.id)
  } catch (err) {
    if (err.code === 'file_in_use' && Array.isArray(err.details?.usages)) {
      detail.value = { ...(detail.value || target), usages: err.details.usages }
    }
    toast.error(apiErrorText(err, t, te))
  } finally {
    deleting.value = false
  }
}

// Arrow keys flip through the files, except while typing.
useEventListener(typeof window !== 'undefined' ? window : null, 'keydown', (e) => {
  if (!props.open || !props.item || e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey) return
  const tag = (e.target?.tagName || '').toLowerCase()
  if (['input', 'textarea', 'select', 'video', 'audio'].includes(tag) || e.target?.isContentEditable) return
  if (e.key === 'ArrowLeft' && props.hasPrev) emit('prev')
  else if (e.key === 'ArrowRight' && props.hasNext) emit('next')
})
</script>
