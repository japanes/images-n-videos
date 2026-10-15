<template>
  <ModalShell :open="open" size="lg" :title="item?.title || t('library.title')" @close="$emit('close')">
    <div v-if="loading && !item" class="grid place-items-center py-16"><Spinner :size="24" /></div>
    <EmptyState v-else-if="loadError" icon="alert" :title="loadError" />

    <div v-else-if="item" class="space-y-5">
      <div class="grid gap-5 md:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <div class="overflow-hidden rounded-card bg-slate-100 dark:bg-slate-900">
          <a v-if="item.preview_full_url && !broken" :href="item.preview_full_url" target="_blank" rel="noopener">
            <img :src="item.preview_full_url" :alt="item.title" class="max-h-[60vh] w-full object-contain" @error="broken = true">
          </a>
          <div v-else class="grid aspect-square place-items-center text-slate-400">
            <AppIcon :name="item.kind === 'photo_style' ? 'image' : 'sparkles'" :size="40" />
          </div>
        </div>

        <div class="min-w-0 space-y-3 text-sm">
          <div class="flex flex-wrap gap-1.5">
            <span class="badge bg-slate-100 text-slate-700 dark:bg-slate-700 dark:text-slate-200">{{ t(`library.kindOne.${item.kind}`) }}</span>
            <span v-if="item.is_builtin" class="badge bg-primary/10 text-primary">{{ t('library.builtinBadge') }}</span>
            <span v-else class="badge bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300">{{ t('library.mineBadge') }}</span>
            <span v-if="item.removed" class="badge bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300">{{ t('library.removedBadge') }}</span>
          </div>
          <div>
            <p class="label">{{ t('library.details.category') }}</p>
            <p class="break-words">{{ categoryLine || t('library.noCategory') }}</p>
          </div>
          <div v-if="item.description">
            <p class="label">{{ t('library.details.description') }}</p>
            <p class="whitespace-pre-line break-words">{{ item.description }}</p>
          </div>
          <p v-if="item.text_zone_count" class="muted">{{ t('library.details.zones', { n: item.text_zone_count }) }}</p>
          <p v-if="item.copied_from" class="muted">{{ t('library.details.copiedFrom') }}</p>
          <p v-if="item.removed" class="rounded-card bg-amber-50 p-3 text-amber-900 dark:bg-amber-900/30 dark:text-amber-200">
            {{ t('library.details.removedNote') }}
          </p>
        </div>
      </div>

      <section v-if="item.variables?.length" class="space-y-3">
        <div>
          <h3 class="text-sm font-semibold">{{ t('library.details.fields') }}</h3>
          <p class="text-xs muted">{{ t('library.details.fieldsHint') }}</p>
        </div>
        <div class="grid gap-3 sm:grid-cols-2">
          <label v-for="v in item.variables" :key="v.key" class="block min-w-0">
            <span class="label flex items-center gap-1.5">
              <span class="truncate">{{ v.name }}</span>
              <span class="rounded-badge bg-slate-100 px-1.5 text-[10px] font-normal dark:bg-slate-700">{{ t(`library.editor.fieldTypes.${v.type}`) }}</span>
            </span>
            <span class="flex items-center gap-2">
              <input
                v-if="v.type === 'color'"
                type="color"
                class="h-9 w-10 shrink-0 cursor-pointer rounded-input border border-slate-300 bg-white p-0.5 dark:border-slate-600 dark:bg-slate-950"
                :value="hexOf(values[v.key])"
                :title="t('library.details.pickColor')"
                :aria-label="t('library.details.pickColor')"
                @input="values[v.key] = $event.target.value"
              >
              <input v-model="values[v.key]" type="text" class="input" :maxlength="LIBRARY_LIMITS.value" :placeholder="v.default">
            </span>
            <span class="mt-1 block text-xs muted">
              {{ v.default ? t('library.details.fieldEmpty', { value: v.default }) : t('library.details.fieldDropped') }}
            </span>
          </label>
        </div>
      </section>

      <label class="block">
        <span class="label">{{ t('library.details.extra') }}</span>
        <textarea v-model="extra" rows="2" class="input" :maxlength="LIBRARY_LIMITS.extra" />
        <span class="mt-1 block text-xs muted">{{ t('library.details.extraHint') }}</span>
      </label>

      <section class="space-y-1">
        <div class="flex items-center gap-2">
          <h3 class="text-sm font-semibold">{{ t('library.details.result') }}</h3>
          <Spinner v-if="rendering" :size="12" />
        </div>
        <p class="text-xs muted">{{ t('library.details.resultHint') }}</p>
        <p v-if="renderError" class="text-sm text-rose-600 dark:text-rose-400">{{ renderError }}</p>
        <pre v-else class="max-h-72 overflow-y-auto whitespace-pre-wrap break-words rounded-card bg-slate-50 p-3 font-sans text-sm dark:bg-slate-900">{{ rendered }}</pre>
      </section>

      <details v-if="item.variables?.length" class="text-sm">
        <summary class="cursor-pointer muted">{{ t('library.details.source') }}</summary>
        <pre class="mt-2 max-h-72 overflow-y-auto whitespace-pre-wrap break-words rounded-card bg-slate-50 p-3 font-mono text-xs dark:bg-slate-900">{{ item.prompt }}</pre>
      </details>
    </div>

    <template v-if="item" #footer>
      <template v-if="item.is_builtin">
        <button type="button" class="btn-primary" :disabled="busy" @click="copyStyle">
          <Spinner v-if="busy === 'copy'" :size="14" /><AppIcon v-else name="copy" :size="16" />{{ t('library.details.copyToMine') }}
        </button>
      </template>
      <template v-else>
        <button type="button" class="btn-ghost mr-auto text-rose-600 dark:text-rose-400" :disabled="busy" @click="deleteStyle">
          <Spinner v-if="busy === 'delete'" :size="14" /><AppIcon v-else name="trash" :size="16" />{{ t('common.delete') }}
        </button>
        <button type="button" class="btn-secondary" :disabled="busy" @click="copyStyle">
          <Spinner v-if="busy === 'copy'" :size="14" /><AppIcon v-else name="copy" :size="16" />{{ t('library.details.duplicate') }}
        </button>
        <button type="button" class="btn-primary" :disabled="busy" @click="$emit('edit', item)">
          <AppIcon name="edit" :size="16" />{{ t('common.edit') }}
        </button>
      </template>
    </template>
  </ModalShell>
</template>

<script setup>
import { useDebounceFn } from '@vueuse/core'
import { LIBRARY_LIMITS, libraryCategoryTitle, libraryErrorText, useLibrary } from '~/composables/useLibrary.js'

const props = defineProps({
  open: { type: Boolean, default: false },
  styleId: { type: Number, default: null },
})
const emit = defineEmits(['close', 'edit', 'copied', 'deleted'])
const { t, te, locale } = useI18n()
const lib = useLibrary()
const toast = useToast()
const { confirm } = useConfirm()

const item = ref(null)
const loading = ref(false)
const loadError = ref('')
const broken = ref(false)
const values = ref({})
const extra = ref('')
const rendered = ref('')
const rendering = ref(false)
const renderError = ref('')
const busy = ref('')
let loadSeq = 0
let renderSeq = 0

const categoryLine = computed(() => (item.value?.category_path || [])
  .map((c) => libraryCategoryTitle(c, locale.value)).join(' / '))

const hexOf = (value) => (/^#[0-9a-f]{6}$/i.test(String(value || '').trim()) ? String(value).trim() : '#000000')

async function load({ keepInput = false } = {}) {
  if (!props.styleId) return
  const seq = ++loadSeq
  loading.value = true
  loadError.value = ''
  try {
    const res = await lib.style(props.styleId)
    if (seq !== loadSeq) return
    item.value = res
    broken.value = false
    if (!keepInput) {
      values.value = Object.fromEntries((res.variables || []).map((v) => [v.key, '']))
      extra.value = ''
    }
    await renderNow()
  } catch (err) {
    if (seq !== loadSeq) return
    item.value = null
    loadError.value = libraryErrorText(err, t, te)
  } finally {
    if (seq === loadSeq) loading.value = false
  }
}

async function renderNow() {
  if (!item.value) return
  const seq = ++renderSeq
  rendering.value = true
  try {
    const res = await lib.render({ style_id: item.value.id, values: { ...values.value }, extra: extra.value })
    if (seq !== renderSeq) return
    rendered.value = res.prompt || ''
    renderError.value = ''
  } catch (err) {
    if (seq !== renderSeq) return
    renderError.value = libraryErrorText(err, t, te)
  } finally {
    if (seq === renderSeq) rendering.value = false
  }
}
const renderSoon = useDebounceFn(renderNow, 300)
watch([values, extra], () => { if (item.value) renderSoon() }, { deep: true })

watch(() => [props.open, props.styleId], ([isOpen, id], old) => {
  if (!isOpen || !id) return
  if (old && old[0] && old[1] === id && item.value?.id === id) return
  item.value = null
  rendered.value = ''
  load()
}, { immediate: true })

useEvents().on('library.updated', (data) => {
  if (!props.open || !item.value || data?.id !== item.value.id) return
  if (data.action === 'deleted') emit('close')
  else load({ keepInput: true })
})

async function copyStyle() {
  busy.value = 'copy'
  try {
    const copy = await lib.copy(item.value.id)
    toast.success(t('library.details.copied'))
    emit('copied', copy)
  } catch (err) {
    toast.error(libraryErrorText(err, t, te))
  } finally {
    busy.value = ''
  }
}

async function deleteStyle() {
  const ok = await confirm({
    message: t('library.details.deleteConfirm', { title: item.value.title }),
    confirmLabel: t('common.delete'),
    tone: 'danger',
  })
  if (!ok) return
  busy.value = 'delete'
  try {
    const id = item.value.id
    await lib.remove(id)
    toast.success(t('library.details.deleted'))
    emit('deleted', id)
  } catch (err) {
    toast.error(libraryErrorText(err, t, te))
  } finally {
    busy.value = ''
  }
}
</script>
