<template>
  <section class="card space-y-3 p-4">
    <header class="flex flex-wrap items-start gap-3">
      <div class="min-w-0 flex-1 basis-64">
        <h2 class="text-base font-semibold">{{ t('brand.kit.fonts.title') }}</h2>
        <p class="mt-1 text-sm muted">{{ t('brand.kit.fonts.hint') }}</p>
      </div>
      <div class="flex flex-col items-end gap-1">
        <button type="button" class="btn-secondary btn-sm" :disabled="uploading" @click="fileInput?.click()">
          <Spinner v-if="uploading" :size="14" /><AppIcon v-else name="upload" :size="14" />{{ t('brand.kit.fonts.upload') }}
        </button>
        <span class="text-xs muted">{{ uploading ? t('brand.kit.uploading', progress) : t('brand.kit.fonts.formats', { mb: 20 }) }}</span>
      </div>
      <input ref="fileInput" type="file" class="hidden" :accept="FONT_ACCEPT" multiple @change="onFiles">
    </header>

    <p v-if="!fonts.length" class="text-sm muted">{{ t('brand.kit.fonts.empty') }}</p>
    <ul v-else class="divide-y divide-slate-200 dark:divide-slate-700">
      <li v-for="a in fonts" :key="a.id" class="flex flex-wrap items-start gap-3 py-3">
        <div class="min-w-0 flex-1 basis-64">
          <p class="flex flex-wrap items-center gap-2 text-sm font-medium">
            <span class="truncate">{{ a.font?.family || a.name }}</span>
            <span v-if="a.font?.style" class="text-xs muted">{{ a.font.style }}</span>
            <span v-if="a.font?.source === 'google'" class="badge bg-sky-100 text-sky-800 dark:bg-sky-500/15 dark:text-sky-200">{{ t('brand.kit.fonts.catalog') }}</span>
          </p>
          <p class="mt-1 truncate text-xl" :style="previewStyle(a)">{{ t('brand.kit.fonts.sample') }}</p>
          <p v-if="a.font?.source !== 'google' && a.font?.detected_category" class="mt-1 text-xs" :class="a.font.detected_by === 'default' ? 'text-amber-700 dark:text-amber-300' : 'muted'">
            {{ a.font.detected_by === 'default'
              ? t('brand.kit.fonts.guessed', { category: categoryLabel(a.font.detected_category) })
              : t('brand.kit.fonts.detected', { category: categoryLabel(a.font.detected_category) }) }}
          </p>
        </div>
        <label class="w-48 shrink-0">
          <span class="label">{{ t('brand.kit.fonts.category') }}</span>
          <select class="input" :value="a.font?.category || 'sans'" :disabled="busyId === a.id" @change="setCategory(a, $event.target.value)">
            <option v-for="c in FONT_CATEGORIES" :key="c" :value="c">{{ categoryLabel(c) }}</option>
          </select>
        </label>
        <button
          type="button"
          class="btn-ghost mt-5 p-2 text-rose-600 dark:text-rose-400"
          :disabled="busyId === a.id"
          :title="t('brand.kit.fonts.remove')"
          :aria-label="t('brand.kit.fonts.remove')"
          @click="remove(a)"
        >
          <AppIcon name="trash" :size="16" />
        </button>
      </li>
    </ul>
  </section>
</template>

<script setup>
import { FONT_ACCEPT, FONT_CATEGORIES, assetsOfKind, brandErrorText } from '~/utils/brand.js'

const props = defineProps({
  kit: { type: Object, required: true },
})
const emit = defineEmits(['changed'])
const { t, te } = useI18n()
const api = useApi()
const toast = useToast()
const { confirm } = useConfirm()

const fonts = computed(() => assetsOfKind(props.kit.assets, 'font'))
const fileInput = ref(null)
const uploading = ref(false)
const progress = ref({ done: 0, total: 0 })
const busyId = ref(null)

const categoryLabel = (c) => t(`brand.kit.fonts.categories.${c}`)

// Each uploaded font is loaded into the page under its own name for the preview.
const loaded = ref(new Set())
const faceName = (a) => `vf-font-${a.id}`
function loadFaces() {
  if (typeof FontFace === 'undefined' || typeof document === 'undefined') return
  for (const a of fonts.value) {
    if (!a.file?.url || loaded.value.has(a.id)) continue
    const face = new FontFace(faceName(a), `url(${a.file.url})`)
    face.load().then((f) => {
      document.fonts.add(f)
      loaded.value = new Set([...loaded.value, a.id])
    }).catch(() => {})
  }
}
watch(fonts, loadFaces, { immediate: true })

function previewStyle(a) {
  if (loaded.value.has(a.id)) return { fontFamily: `'${faceName(a)}', sans-serif` }
  if (a.font?.source === 'google' && a.font.google_family) return { fontFamily: `'${a.font.google_family}', sans-serif` }
  return {}
}

async function onFiles(e) {
  const files = [...(e.target.files || [])]
  e.target.value = ''
  if (!files.length) return
  uploading.value = true
  progress.value = { done: 0, total: files.length }
  for (const file of files) {
    try {
      await api.upload(`/api/brand/kits/${props.kit.id}/fonts`, file)
    } catch (err) {
      toast.error(`${file.name}: ${brandErrorText(err, t, te)}`)
    }
    progress.value = { done: progress.value.done + 1, total: files.length }
  }
  uploading.value = false
  emit('changed')
}

async function setCategory(a, category) {
  busyId.value = a.id
  try {
    await api.patch(`/api/brand/assets/${a.id}`, { font_category: category })
    emit('changed')
  } catch (err) {
    toast.error(brandErrorText(err, t, te))
  } finally {
    busyId.value = null
  }
}

async function remove(a) {
  const name = a.font?.family || a.name
  const ok = await confirm({ message: t('brand.kit.fonts.removeConfirm', { name }), confirmLabel: t('common.delete'), tone: 'danger' })
  if (!ok) return
  busyId.value = a.id
  try {
    await api.del(`/api/brand/assets/${a.id}`)
    emit('changed')
  } catch (err) {
    toast.error(brandErrorText(err, t, te))
  } finally {
    busyId.value = null
  }
}
</script>
