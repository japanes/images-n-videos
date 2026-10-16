<template>
  <div class="flex h-full flex-col bg-slate-50 dark:bg-slate-900">
    <!-- the editor -->
    <template v-if="mode === 'editor'">
      <header class="flex flex-wrap items-center gap-2 border-b border-slate-200 bg-white px-3 py-2 dark:border-slate-700 dark:bg-slate-800">
        <button type="button" class="btn-ghost btn-sm" :title="t('clip.page.back')" @click="goBack">
          <AppIcon name="chevron-left" :size="16" /><span class="hidden sm:inline">{{ t('clip.page.back') }}</span>
        </button>
        <input
          v-model="titleDraft"
          type="text"
          maxlength="200"
          class="input w-48 py-1 text-sm font-semibold sm:w-64"
          :aria-label="t('clip.page.name')"
          @change="rename"
          @keydown.enter="$event.target.blur()"
        >
        <div class="flex items-center gap-1">
          <button type="button" class="btn-ghost btn-sm" :disabled="!canUndo" :title="t('clip.page.undoHint')" @click="ed.undo()">
            {{ t('clip.page.undo') }}
          </button>
          <button type="button" class="btn-ghost btn-sm" :disabled="!canRedo" :title="t('clip.page.redoHint')" @click="ed.redo()">
            {{ t('clip.page.redo') }}
          </button>
        </div>
        <label class="flex items-center gap-1 text-sm">
          <span class="muted">{{ t('clip.page.aspect') }}</span>
          <select v-model="state.crop.aspect" class="input w-auto py-1 text-sm">
            <option v-for="a in CLIP_ASPECTS" :key="a || 'source'" :value="a">{{ t(`clip.aspects.${aspectKey(a)}`) }}</option>
          </select>
        </label>
        <label v-if="state.crop.aspect" class="flex items-center gap-1 text-sm">
          <span class="muted">{{ t('clip.page.fit') }}</span>
          <select v-model="state.crop.mode" class="input w-auto py-1 text-sm">
            <option v-for="m in CLIP_CROP_MODES" :key="m" :value="m">{{ t(`clip.cropModes.${m}`) }}</option>
          </select>
        </label>
        <span class="flex-1" />
        <span class="flex items-center gap-1 text-xs" :class="saveStatus === 'failed' ? 'text-rose-700 dark:text-rose-300' : 'muted'" :title="saveError">
          <Spinner v-if="saveStatus === 'saving'" :size="12" />
          <AppIcon v-else-if="saveStatus === 'saved'" name="check" :size="12" />
          <AppIcon v-else-if="saveStatus === 'failed'" name="alert" :size="12" />
          {{ t(`clip.page.save.${saveStatus}`) }}
        </span>
        <button v-if="saveStatus === 'failed'" type="button" class="btn-ghost btn-sm" @click="ed.save()">{{ t('common.retry') }}</button>
        <button type="button" class="btn-ghost btn-sm text-rose-600" :title="t('clip.page.delete')" @click="removeProject">
          <AppIcon name="trash" :size="14" />
        </button>
        <button type="button" class="btn-primary btn-sm" @click="sideTab = 'export'">
          <AppIcon name="download" :size="14" />{{ t('clip.page.export') }}
        </button>
      </header>

      <p v-if="!project.source_file" class="bg-rose-50 px-3 py-2 text-sm text-rose-800 dark:bg-rose-500/10 dark:text-rose-200">
        {{ t('clip.page.sourceMissing') }}
      </p>

      <div class="flex min-h-0 flex-1 flex-col lg:flex-row">
        <main class="flex min-h-[18rem] min-w-0 flex-1 flex-col">
          <ClipCanvas />
          <ClipTimeline />
        </main>
        <aside class="flex min-h-0 w-full shrink-0 flex-col border-t border-slate-200 bg-white lg:w-[24rem] lg:border-l lg:border-t-0 dark:border-slate-700 dark:bg-slate-800">
          <nav class="flex border-b border-slate-200 dark:border-slate-700" role="tablist">
            <button
              v-for="tab in TABS"
              :key="tab.id"
              type="button"
              role="tab"
              :aria-selected="sideTab === tab.id"
              class="flex flex-1 items-center justify-center gap-1 border-b-2 px-2 py-2 text-sm"
              :class="sideTab === tab.id ? 'border-primary font-medium text-primary' : 'border-transparent muted hover:text-slate-900 dark:hover:text-slate-100'"
              @click="sideTab = tab.id"
            >
              <AppIcon :name="tab.icon" :size="14" />{{ t(`clip.tabs.${tab.id}`) }}
            </button>
          </nav>
          <div class="min-h-0 flex-1 overflow-y-auto p-3">
            <ClipLayerPanel v-if="sideTab === 'layers'" />
            <ClipSubtitlePanel v-else-if="sideTab === 'subtitles'" />
            <ClipAudioPanel v-else-if="sideTab === 'audio'" />
            <ClipExportPanel v-else />
          </div>
        </aside>
      </div>
    </template>

    <!-- opening a project -->
    <div v-else-if="mode === 'opening'" class="flex flex-1 flex-col items-center justify-center gap-3">
      <Spinner :size="28" />
      <p class="text-sm muted">{{ t('clip.page.opening') }}</p>
    </div>

    <!-- something went wrong -->
    <div v-else-if="mode === 'error'" class="page">
      <EmptyState icon="alert" :title="t('clip.page.errorTitle')" :text="errorText">
        <div class="flex flex-wrap justify-center gap-2">
          <button type="button" class="btn-secondary" @click="goBack">{{ t('clip.page.back') }}</button>
          <NuxtLink to="/clip/new" class="btn-ghost">{{ t('clip.page.startOver') }}</NuxtLink>
        </div>
      </EmptyState>
    </div>

    <!-- no video yet: pick one or reopen a project -->
    <div v-else class="overflow-y-auto">
      <div class="page space-y-6">
        <div class="flex flex-wrap items-center gap-3">
          <button type="button" class="btn-ghost btn-sm -ml-2" @click="goBack">
            <AppIcon name="chevron-left" :size="14" />{{ t('clip.page.back') }}
          </button>
        </div>
        <div class="space-y-2">
          <h1 class="page-title">{{ t('clip.page.title') }}</h1>
          <p class="text-sm muted">{{ t('clip.page.intro') }}</p>
          <button type="button" class="btn-primary" @click="pickerOpen = true">
            <AppIcon name="video" :size="16" />{{ t('clip.page.pick') }}
          </button>
        </div>
        <section v-if="recent.length" class="space-y-2">
          <h2 class="text-sm font-semibold">{{ t('clip.page.recent') }}</h2>
          <ul class="card divide-y divide-slate-200 dark:divide-slate-700">
            <li v-for="item in recent" :key="item.id">
              <NuxtLink :to="clipProjectRoute(item.id)" class="flex items-center gap-3 px-4 py-3 hover:bg-slate-50 dark:hover:bg-slate-700/40">
                <AppIcon name="video" :size="18" class="muted" />
                <span class="min-w-0 flex-1 truncate text-sm">{{ item.title }}</span>
                <span class="text-xs muted">{{ formatDateTime(item.updated_at, locale) }}</span>
              </NuxtLink>
            </li>
          </ul>
        </section>
      </div>
      <ClipMediaPicker :open="pickerOpen" kind="video" :title="t('clip.page.pick')" @pick="onPick" @close="pickerOpen = false" />
    </div>
  </div>
</template>

<script setup>
import { onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'
import { formatDateTime } from '~/utils/format.js'
import { CLIP_ASPECTS, CLIP_CROP_MODES, clipErrorText, clipProjectRoute } from '~/utils/clipState.js'

definePageMeta({ layout: 'bare' })

const TABS = [
  { id: 'layers', icon: 'text' },
  { id: 'subtitles', icon: 'chat' },
  { id: 'audio', icon: 'play' },
  { id: 'export', icon: 'download' },
]
const ASPECT_KEYS = { '': 'source', '9:16': 'vertical', '1:1': 'square', '4:5': 'portrait', '16:9': 'wide' }

const { t, te, locale } = useI18n()
const api = useApi()
const route = useRoute()
const router = useRouter()
const toast = useToast()
const { confirm } = useConfirm()
const ed = useClipEditor()
const { project, state, loadError, saveStatus, saveError, sideTab, canUndo, canRedo } = ed

const openError = ref('')
const recent = ref([])
const pickerOpen = ref(false)
const titleDraft = ref('')

const isNew = computed(() => route.params.id === 'new')
const mode = computed(() => {
  if (openError.value) return 'error'
  if (isNew.value) return route.query.file ? 'opening' : 'start'
  if (loadError.value) return 'error'
  if (project.value && state.value && project.value.id === Number(route.params.id)) return 'editor'
  return 'opening'
})
const errorText = computed(() => {
  if (openError.value) return openError.value
  if (loadError.value?.status === 404) return t('clip.page.notFound')
  return loadError.value ? clipErrorText(loadError.value, t, te) : ''
})

const aspectKey = (a) => ASPECT_KEYS[a] || 'source'

// ── opening ─────────────────────────────────────────────────────────────────

async function openFor(fileId, fresh) {
  try {
    const res = await api.post('/api/clip/projects', { file_id: Number(fileId), new: !!fresh })
    await router.replace(clipProjectRoute(res.id))
  } catch (err) {
    openError.value = clipErrorText(err, t, te)
  }
}

async function loadRecent() {
  try {
    recent.value = (await api.get('/api/clip/projects', { limit: 20 })).items || []
  } catch {
    recent.value = []
  }
}

async function init() {
  openError.value = ''
  const id = route.params.id
  if (id === 'new') {
    if (route.query.file) await openFor(route.query.file, route.query.new === '1')
    else loadRecent()
    return
  }
  const num = Number(id)
  if (!Number.isInteger(num) || num <= 0) {
    openError.value = t('clip.page.notFound')
    return
  }
  try {
    await ed.load(num)
  } catch {
    // loadError holds it; the page shows it
  }
}

watch(() => [route.params.id, route.query.file, route.query.new], init, { immediate: true })
watch(() => project.value?.title, (v) => { titleDraft.value = v || '' }, { immediate: true })

function onPick(item) {
  pickerOpen.value = false
  if (item?.id) router.push({ path: '/clip/new', query: { file: String(item.id), new: '1' } })
}

function goBack() {
  if (window.history.state?.back) router.back()
  else router.push('/media')
}

// ── top bar ─────────────────────────────────────────────────────────────────

async function rename() {
  const text = titleDraft.value.trim()
  if (!text || text === project.value?.title) {
    titleDraft.value = project.value?.title || ''
    return
  }
  try {
    await ed.rename(text)
  } catch (err) {
    titleDraft.value = project.value?.title || ''
    toast.error(clipErrorText(err, t, te))
  }
}

async function removeProject() {
  const ok = await confirm({ message: t('clip.page.deleteAsk'), tone: 'danger', confirmLabel: t('clip.page.delete') })
  if (!ok) return
  try {
    await ed.remove()
    toast.success(t('clip.page.deleted'))
    router.replace('/clip/new')
  } catch (err) {
    toast.error(clipErrorText(err, t, te))
  }
}

async function removeSelected() {
  const layer = ed.selected.value
  if (!layer) return
  const name = layer.type === 'text' ? layer.text?.trim() || t('clip.layers.emptyText') : t('clip.layers.picture')
  const ok = await confirm({ message: t('clip.layers.removeAsk', { name }), tone: 'danger', confirmLabel: t('clip.layers.remove') })
  if (!ok) return
  state.value.layers = state.value.layers.filter((l) => l.id !== layer.id)
  ed.selectedId.value = null
}

// ── keyboard ────────────────────────────────────────────────────────────────

function onKey(e) {
  if (mode.value !== 'editor' || e.defaultPrevented) return
  if (document.querySelector('[aria-modal="true"]')) return
  const el = e.target
  if (el?.closest?.('input, textarea, select, [contenteditable="true"]')) return
  const mod = e.ctrlKey || e.metaKey
  const key = String(e.key || '').toLowerCase()
  if (mod && key === 'z') {
    e.preventDefault()
    if (e.shiftKey) ed.redo()
    else ed.undo()
  } else if (mod && key === 'y') {
    e.preventDefault()
    ed.redo()
  } else if (mod || e.altKey) {
    // leave other shortcuts to the browser
  } else if (e.key === ' ' && !el?.closest?.('button, a')) {
    e.preventDefault()
    ed.togglePlay()
  } else if ((e.key === 'Delete' || e.key === 'Backspace') && ed.selected.value) {
    e.preventDefault()
    removeSelected()
  }
}

// ── leaving ─────────────────────────────────────────────────────────────────

async function beforeLeave() {
  if (!project.value || !ed.hasUnsaved()) return true
  try {
    await ed.flush()
    return true
  } catch {
    return confirm({ message: t('clip.page.leaveAsk'), tone: 'danger', confirmLabel: t('clip.page.leave') })
  }
}

onBeforeRouteLeave(beforeLeave)
onBeforeRouteUpdate((to, from) => (to.params.id !== from.params.id ? beforeLeave() : true))

function beforeUnload(e) {
  if (!project.value || !ed.hasUnsaved()) return
  ed.save()
  e.preventDefault()
  e.returnValue = ''
}

onMounted(() => {
  window.addEventListener('keydown', onKey)
  window.addEventListener('beforeunload', beforeUnload)
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
  window.removeEventListener('beforeunload', beforeUnload)
  ed.stop()
})
</script>
