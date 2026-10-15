<template>
  <div class="page space-y-4 pb-24">
    <header>
      <h1 class="page-title">{{ t('settings.title') }}</h1>
      <p class="mt-1 text-sm muted">{{ t('settings.subtitle') }}</p>
    </header>

    <section class="card p-4">
      <div class="grid gap-2 md:grid-cols-[minmax(0,1fr)_minmax(14rem,20rem)] md:gap-6">
        <div>
          <label for="settings-ui-language" class="text-sm font-medium">{{ t('settings.language.title') }}</label>
          <p class="mt-0.5 text-sm muted">{{ t('settings.language.help') }}</p>
        </div>
        <select id="settings-ui-language" class="input" :value="locale" @change="setLocale($event.target.value)">
          <option v-for="l in locales" :key="l.code" :value="l.code">{{ languageName(l.code) }}</option>
        </select>
      </div>
    </section>

    <div v-if="!loaded && loading" class="flex justify-center py-12"><Spinner :size="24" /></div>

    <EmptyState v-else-if="!loaded && loadError" icon="alert" :title="t('settings.loadFailed')" :text="loadError">
      <button type="button" class="btn-secondary" @click="load">{{ t('common.retry') }}</button>
    </EmptyState>

    <form v-else id="settings-form" class="space-y-4" @submit.prevent="save">
      <section v-for="g in groups" :key="g.group" class="card px-4 pt-3">
        <h2 class="font-semibold">{{ groupTitle(g.group) }}</h2>
        <p v-if="groupHint(g.group)" class="mt-0.5 text-sm muted">{{ groupHint(g.group) }}</p>
        <div class="divide-y divide-slate-100 dark:divide-slate-700">
          <SettingsField
            v-for="item in g.items"
            :key="item.key"
            :item="item"
            :model-value="drafts[item.key]"
            :error="errors[item.key] || ''"
            :dirty="dirtyKeys.includes(item.key)"
            :at-default="atDefault(item)"
            @update:model-value="edit(item, $event)"
            @reset="resetToDefault(item)"
          />
        </div>
      </section>
    </form>

    <div
      v-if="dirtyKeys.length"
      class="sticky bottom-0 z-10 -mx-4 flex flex-wrap items-center gap-3 border-t border-slate-200 bg-white/95 px-4 py-3 backdrop-blur dark:border-slate-700 dark:bg-slate-900/95 md:-mx-8 md:px-8"
    >
      <span class="flex-1 text-sm">{{ t('settings.unsaved', { count: dirtyKeys.length }, dirtyKeys.length) }}</span>
      <button type="button" class="btn-ghost" :disabled="saving" @click="discard">{{ t('settings.discard') }}</button>
      <button type="submit" form="settings-form" class="btn-primary" :disabled="saving">
        <Spinner v-if="saving" :size="14" />{{ t('settings.save') }}
      </button>
    </div>
  </div>
</template>

<script setup>
import { useDebounceFn } from '@vueuse/core'
import { onBeforeRouteLeave } from 'vue-router'
import { apiErrorText } from '~/utils/apiErrorText.js'
import {
  ASPECT_SIDE_MAX, ASPECT_SIDE_MIN, aspectSizeRows, aspectSizesValue,
  parseSettingInput, sameSettingValue, settingsGroups,
} from '~/utils/modelsView.js'

const { t, te, locale, locales, setLocale } = useI18n()
const api = useApi()
const toast = useToast()
const { confirm } = useConfirm()
const { on } = useEvents()

const items = ref([])
const drafts = ref({})
const errors = ref({})
const loading = ref(false)
const loaded = ref(false)
const loadError = ref('')
const saving = ref(false)

const groups = computed(() => settingsGroups(items.value))
const byKey = computed(() => new Map(items.value.map((i) => [i.key, i])))

const languageName = (code) => (te(`settings.language.names.${code}`) ? t(`settings.language.names.${code}`) : code)
const groupTitle = (g) => (te(`settings.groups.${g}.title`) ? t(`settings.groups.${g}.title`) : g)
const groupHint = (g) => (te(`settings.groups.${g}.hint`) ? t(`settings.groups.${g}.hint`) : '')

const isAspect = (item) => item.meta?.widget === 'aspect_sizes'

/** What the input shows for a stored value. */
function toDraft(item, value) {
  if (item.kind === 'bool') return !!value
  if (isAspect(item)) return aspectSizeRows(value, item.default)
  if (item.kind === 'json' || item.kind === 'any') return value === null || value === undefined ? '' : JSON.stringify(value, null, 2)
  return value === null || value === undefined ? '' : String(value)
}

/** The value to store, `{ value }` or `{ error }`; an empty text means "not set". */
function fromDraft(item, draft) {
  if (item.kind === 'bool') return { value: !!draft }
  if (item.kind === 'enum') {
    const choice = (item.choices || []).find((c) => String(c) === String(draft))
    return choice === undefined ? { value: draft } : { value: choice }
  }
  if (isAspect(item)) {
    const value = aspectSizesValue(draft || [])
    return value ? { value } : { error: 'sizes' }
  }
  if (item.kind === 'str') return { value: String(draft ?? '').trim() || null }
  if ((item.kind === 'json' || item.kind === 'any') && !String(draft ?? '').trim()) return { value: null }
  return parseSettingInput(item, draft)
}

// Compare what is typed, not what it means: "3" and 3 are the same text.
const draftText = (d) => JSON.stringify(d ?? null, (_k, v) => (typeof v === 'number' ? String(v) : v))

const dirtyKeys = computed(() => items.value
  .filter((item) => item.key in drafts.value && draftText(drafts.value[item.key]) !== draftText(toDraft(item, item.value)))
  .map((item) => item.key))

function atDefault(item) {
  const parsed = fromDraft(item, drafts.value[item.key])
  if (parsed.error) return false
  return sameSettingValue(parsed.value, item.default) || (item.kind === 'str' && !parsed.value && !item.default)
}

function errorText(item, code) {
  if (code === 'range') return t('settings.errors.range', { min: item.min, max: item.max })
  if (code === 'sizes') return t('settings.errors.sizes', { min: ASPECT_SIDE_MIN, max: ASPECT_SIDE_MAX })
  return t(`settings.errors.${code}`)
}

function edit(item, value) {
  drafts.value = { ...drafts.value, [item.key]: value }
  if (errors.value[item.key]) {
    const { [item.key]: _gone, ...rest } = errors.value
    errors.value = rest
  }
}

const resetToDefault = (item) => edit(item, toDraft(item, item.default))

/** Take fresh values; keep what the user is still editing unless `all`. */
function apply(list, { all = false } = {}) {
  const keep = all ? new Set() : new Set(dirtyKeys.value)
  items.value = list || []
  const next = {}
  for (const item of items.value) {
    next[item.key] = keep.has(item.key) ? drafts.value[item.key] : toDraft(item, item.value)
  }
  drafts.value = next
}

async function load({ all = true } = {}) {
  loading.value = true
  try {
    const res = await api.get('/api/settings')
    apply(res?.items || [], { all })
    loadError.value = ''
    loaded.value = true
  } catch (err) {
    loadError.value = apiErrorText(err, t, te)
  } finally {
    loading.value = false
  }
}

function discard() {
  apply(items.value, { all: true })
  errors.value = {}
}

async function save() {
  const body = {}
  const found = {}
  for (const key of dirtyKeys.value) {
    const item = byKey.value.get(key)
    const parsed = fromDraft(item, drafts.value[key])
    if (parsed.error) {
      found[key] = errorText(item, parsed.error)
      continue
    }
    // The default value is stored as "not set", so a later default applies.
    body[key] = sameSettingValue(parsed.value, item.default) ? null : parsed.value
  }
  errors.value = found
  if (Object.keys(found).length) {
    toast.error(t('settings.fixFirst'))
    return
  }
  if (!Object.keys(body).length) return
  saving.value = true
  try {
    const res = await api.put('/api/settings', body)
    apply(res?.items || items.value, { all: true })
    toast.success(t('settings.saved'))
  } catch (err) {
    const key = err?.details?.key
    if (key && byKey.value.has(key)) errors.value = { [key]: apiErrorText(err, t, te) }
    toast.error(apiErrorText(err, t, te))
    // The values before the bad one may already be saved: show what is stored now.
    await load({ all: false })
  } finally {
    saving.value = false
  }
}

// Another tab or screen changed a setting: refresh, keeping unsaved edits.
const refresh = useDebounceFn(() => {
  if (!saving.value) load({ all: false })
}, 300)
on('settings.changed', refresh)

onBeforeRouteLeave(async () => {
  if (!dirtyKeys.value.length) return true
  return confirm({ message: t('settings.leaveAsk'), confirmLabel: t('settings.leave') })
})

// Closing the tab with unsaved changes: the browser asks on its own.
function beforeUnload(e) {
  if (!dirtyKeys.value.length) return
  e.preventDefault()
  e.returnValue = ''
}
onMounted(() => {
  window.addEventListener('beforeunload', beforeUnload)
  load()
})
onBeforeUnmount(() => window.removeEventListener('beforeunload', beforeUnload))
</script>
