<template>
  <ModalShell :open="open" size="lg" :title="item ? t('library.editor.editTitle') : t('library.editor.createTitle')" :close-on-overlay="false" @close="$emit('close')">
    <form id="library-style-form" class="space-y-4" novalidate @submit.prevent="save">
      <label class="block">
        <span class="label">{{ t('library.editor.titleLabel') }}</span>
        <input v-model="form.title" type="text" class="input" :maxlength="LIBRARY_LIMITS.title" :placeholder="t('library.editor.titlePlaceholder')" required>
      </label>

      <div class="grid gap-4 sm:grid-cols-2">
        <label class="block">
          <span class="label">{{ t('library.editor.kindLabel') }}</span>
          <select v-model="form.kind" class="input">
            <option v-for="k in LIBRARY_KINDS" :key="k" :value="k">{{ t(`library.kindOne.${k}`) }}</option>
          </select>
          <span class="mt-1 block text-xs muted">{{ t(`library.kindHint.${form.kind}`) }}</span>
        </label>
        <label class="block">
          <span class="label">{{ t('library.editor.categoryLabel') }}</span>
          <select v-model="form.category" class="input">
            <option value="">{{ t('library.noCategory') }}</option>
            <option v-for="o in categoryOptions" :key="o.slug" :value="o.slug">{{ o.label }}</option>
          </select>
        </label>
      </div>

      <label class="block">
        <span class="label">{{ t('library.editor.descriptionLabel') }}</span>
        <textarea v-model="form.description" rows="2" class="input" :maxlength="LIBRARY_LIMITS.description" :placeholder="t('library.editor.descriptionPlaceholder')" />
      </label>

      <label class="block">
        <span class="label flex items-center justify-between gap-2">
          <span>{{ t('library.editor.promptLabel') }}</span>
          <span class="font-normal tabular-nums">{{ t('library.editor.chars', { n: form.prompt.length, max: LIBRARY_LIMITS.prompt }) }}</span>
        </span>
        <textarea v-model="form.prompt" rows="7" class="input font-mono text-xs" :maxlength="LIBRARY_LIMITS.prompt" :placeholder="t('library.editor.promptPlaceholder')" required />
        <span class="mt-1 block text-xs muted">{{ t('library.editor.promptHint', { example: promptExample }) }}</span>
      </label>
      <div class="text-xs">
        <p v-if="slotCount > LIBRARY_LIMITS.variables" class="text-rose-600 dark:text-rose-400">
          {{ t('library.editor.tooManyFields', { n: slotCount, max: LIBRARY_LIMITS.variables }) }}
        </p>
        <template v-else-if="fields.length">
          <p class="muted">{{ t('library.editor.fieldsFound', { n: fields.length }) }}</p>
          <ul class="mt-1 flex flex-wrap gap-1.5">
            <li v-for="f in fields" :key="f.key" class="badge bg-slate-100 font-normal text-slate-700 dark:bg-slate-700 dark:text-slate-200">
              <span class="font-medium">{{ f.name }}</span>
              <span class="muted">· {{ t(`library.editor.fieldTypes.${f.type}`) }}</span>
            </li>
          </ul>
        </template>
        <p v-else-if="form.prompt.trim()" class="muted">{{ t('library.editor.noFields') }}</p>
      </div>

      <section class="space-y-2">
        <div>
          <p class="label">{{ t('library.editor.previewLabel') }}</p>
          <p class="text-xs muted">{{ t('library.editor.previewHint') }}</p>
        </div>
        <div class="flex flex-wrap items-center gap-3">
          <div class="grid h-24 w-24 shrink-0 place-items-center overflow-hidden rounded-card bg-slate-100 text-slate-400 dark:bg-slate-900">
            <img v-if="previewSrc" :src="previewSrc" alt="" class="h-full w-full object-cover">
            <AppIcon v-else name="image" :size="24" />
          </div>
          <div class="flex flex-wrap gap-2">
            <button type="button" class="btn-secondary btn-sm" :disabled="!!previewBusy || saving" @click="picker?.click()">
              <Spinner v-if="previewBusy === 'upload'" :size="12" /><AppIcon v-else name="upload" :size="14" />
              {{ previewSrc ? t('library.editor.replacePreview') : t('library.editor.uploadPreview') }}
            </button>
            <button v-if="previewSrc" type="button" class="btn-ghost btn-sm" :disabled="!!previewBusy || saving" @click="removePreview">
              <Spinner v-if="previewBusy === 'remove'" :size="12" /><AppIcon v-else name="close" :size="14" />{{ t('library.editor.removePreview') }}
            </button>
          </div>
          <input ref="picker" type="file" class="hidden" :accept="LIBRARY_PREVIEW_ACCEPT" @change="onPick">
        </div>
        <p v-if="item && previewSrc" class="text-xs muted">{{ t('library.editor.previewKept') }}</p>
      </section>

      <details class="text-sm" :open="!!form.zones.trim()">
        <summary class="cursor-pointer muted">{{ t('library.editor.zonesLabel') }}</summary>
        <div class="mt-2">
          <textarea v-model="form.zones" rows="6" class="input font-mono text-xs" spellcheck="false" />
          <span class="mt-1 block text-xs muted">{{ t('library.editor.zonesHint') }}</span>
        </div>
      </details>

      <p v-if="error" class="rounded-card bg-rose-50 p-3 text-sm text-rose-700 dark:bg-rose-900/30 dark:text-rose-300" role="alert">{{ error }}</p>
    </form>

    <template #footer>
      <button type="button" class="btn-ghost" :disabled="saving" @click="$emit('close')">{{ t('common.cancel') }}</button>
      <button type="submit" form="library-style-form" class="btn-primary" :disabled="saving || !!previewBusy">
        <Spinner v-if="saving" :size="14" /><AppIcon v-else name="check" :size="16" />
        {{ item ? t('common.save') : t('library.editor.create') }}
      </button>
    </template>
  </ModalShell>
</template>

<script setup>
import {
  LIBRARY_KINDS, LIBRARY_LIMITS, LIBRARY_PREVIEW_ACCEPT, libraryCategoryOptions, libraryCheckZones,
  libraryErrorText, librarySlotCount, libraryVariables, libraryZonesText, useLibrary,
} from '~/composables/useLibrary.js'

const props = defineProps({
  open: { type: Boolean, default: false },
  item: { type: Object, default: null }, // null: a new style
  nodes: { type: Array, default: () => [] }, // category tree for the select
  defaultKind: { type: String, default: 'style' },
  defaultCategory: { type: String, default: '' },
})
const emit = defineEmits(['close', 'saved'])
const { t, te, locale } = useI18n()
const lib = useLibrary()
const toast = useToast()

// Shown inside the hint; built here so the locale text holds no curly brackets.
const promptExample = '{{subject|red sneaker}}'

const form = ref(blank())
const error = ref('')
const saving = ref(false)
const previewBusy = ref('')
const previewUrl = ref('') // the saved style's picture
const pendingFile = ref(null) // a new style: uploaded right after it is created
const pendingUrl = ref('')
const picker = ref(null)

function blank() {
  return { title: '', kind: 'style', category: '', description: '', prompt: '', zones: '' }
}

const categoryOptions = computed(() => libraryCategoryOptions(props.nodes, locale.value))
const fields = computed(() => libraryVariables(form.value.prompt))
const slotCount = computed(() => librarySlotCount(form.value.prompt))
const previewSrc = computed(() => pendingUrl.value || previewUrl.value)

function dropPending() {
  if (pendingUrl.value) URL.revokeObjectURL(pendingUrl.value)
  pendingUrl.value = ''
  pendingFile.value = null
}

watch(() => props.open, (isOpen) => {
  if (!isOpen) { dropPending(); return }
  const it = props.item
  error.value = ''
  dropPending()
  previewUrl.value = it?.preview_url || ''
  form.value = it
    ? {
        title: it.title || '',
        kind: it.kind || 'style',
        category: it.category || '',
        description: it.description || '',
        prompt: it.prompt || '',
        zones: libraryZonesText(it.text_zones),
      }
    : { ...blank(), kind: LIBRARY_KINDS.includes(props.defaultKind) ? props.defaultKind : 'style', category: props.defaultCategory || '' }
}, { immediate: true })

onBeforeUnmount(dropPending)

function localCheck() {
  const f = form.value
  if (!f.title.trim()) return { code: 'library_title_required' }
  if (!f.prompt.trim()) return { code: 'library_prompt_required' }
  if (slotCount.value > LIBRARY_LIMITS.variables) return { code: 'library_too_many_variables', details: { max: LIBRARY_LIMITS.variables } }
  const zonesCode = libraryCheckZones(f.zones)
  if (zonesCode) return { code: zonesCode, details: { max_chars: LIBRARY_LIMITS.zones } }
  return null
}

async function save() {
  error.value = ''
  const problem = localCheck()
  if (problem) { error.value = libraryErrorText(problem, t, te); return }
  const f = form.value
  const body = {
    title: f.title,
    kind: f.kind,
    category: f.category || null,
    description: f.description,
    prompt: f.prompt,
    text_zones: f.zones.trim() ? f.zones : null,
  }
  saving.value = true
  try {
    let saved
    if (props.item) {
      saved = await lib.update(props.item.id, body)
      toast.success(t('library.editor.saved'))
    } else {
      saved = await lib.create(body)
      toast.success(t('library.editor.created'))
      if (pendingFile.value) {
        try {
          saved = await lib.uploadPreview(saved.id, pendingFile.value)
        } catch (err) {
          // The style exists; only its picture failed. Say so and go on.
          toast.error(libraryErrorText(err, t, te))
        }
      }
    }
    dropPending()
    emit('saved', saved)
  } catch (err) {
    error.value = libraryErrorText(err, t, te)
  } finally {
    saving.value = false
  }
}

async function onPick(e) {
  const file = e.target.files?.[0]
  e.target.value = ''
  if (!file) return
  error.value = ''
  if (!props.item) {
    dropPending()
    pendingFile.value = file
    pendingUrl.value = URL.createObjectURL(file)
    return
  }
  previewBusy.value = 'upload'
  try {
    const saved = await lib.uploadPreview(props.item.id, file)
    previewUrl.value = saved.preview_url || ''
    toast.success(t('library.editor.previewUploaded'))
  } catch (err) {
    error.value = libraryErrorText(err, t, te)
  } finally {
    previewBusy.value = ''
  }
}

async function removePreview() {
  error.value = ''
  if (!props.item) { dropPending(); return }
  previewBusy.value = 'remove'
  try {
    await lib.removePreview(props.item.id)
    previewUrl.value = ''
  } catch (err) {
    error.value = libraryErrorText(err, t, te)
  } finally {
    previewBusy.value = ''
  }
}
</script>
