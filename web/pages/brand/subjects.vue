<template>
  <section class="space-y-4">
    <p class="text-sm muted">{{ t('brand.subjects.hint') }}</p>

    <div class="flex flex-wrap items-center gap-2">
      <div class="inline-flex rounded-button border border-slate-200 p-0.5 dark:border-slate-700" role="tablist">
        <button
          v-for="s in scopes"
          :key="s.key"
          type="button"
          role="tab"
          :aria-selected="scope === s.key"
          class="btn-sm rounded-button px-3"
          :class="scope === s.key ? 'bg-primary/10 font-medium text-primary' : 'muted hover:text-slate-700 dark:hover:text-slate-200'"
          @click="setScope(s.key)"
        >
          {{ t(s.label) }} <span class="tabular-nums opacity-70">{{ counts[s.key] ?? 0 }}</span>
        </button>
      </div>
      <label class="relative min-w-0 flex-1 basis-48">
        <AppIcon name="search" :size="16" class="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
        <input v-model="query" type="search" class="input pl-8" :placeholder="t('brand.subjects.search')" :aria-label="t('brand.subjects.search')">
      </label>
      <select v-model="kind" class="input w-36" :aria-label="t('brand.subjects.kind')">
        <option value="">{{ t('brand.subjects.allKinds') }}</option>
        <option v-for="k in SUBJECT_KINDS" :key="k" :value="k">{{ t(`brand.subjects.kinds.${k}`) }}</option>
      </select>
      <button type="button" class="btn-primary" :disabled="creating" @click="create">
        <Spinner v-if="creating" :size="14" /><AppIcon v-else name="plus" :size="16" />{{ t('brand.subjects.new') }}
      </button>
    </div>

    <p v-if="scope === 'one_off'" class="text-xs muted">{{ t('brand.subjects.oneOffHint') }}</p>
    <p v-if="error" class="rounded-button bg-rose-50 px-3 py-2 text-sm text-rose-800 dark:bg-rose-500/10 dark:text-rose-200">{{ error }}</p>

    <div v-if="loading && !items.length" class="flex justify-center py-12"><Spinner :size="24" /></div>
    <EmptyState
      v-else-if="!items.length && !error"
      icon="image"
      :title="emptyTitle"
      :text="emptyText"
    />
    <div v-else class="space-y-4">
      <BrandSubjectCard
        v-for="s in items"
        :id="`brand-subject-${s.id}`"
        :key="s.id"
        :subject="s"
        :limits="limits"
        @updated="onUpdated"
        @removed="onRemoved"
      />
    </div>
  </section>
</template>

<script setup>
import { useDebounceFn } from '@vueuse/core'
import { SUBJECT_KINDS, brandErrorText } from '~/utils/brand.js'

const { t, te } = useI18n()
const api = useApi()
const toast = useToast()
const { on } = useEvents()

const scopes = [
  { key: 'library', label: 'brand.subjects.tabs.library' },
  { key: 'one_off', label: 'brand.subjects.tabs.oneOff' },
]
const scope = ref('library')
const query = ref('')
const kind = ref('')
const items = ref([])
const counts = ref({ library: 0, one_off: 0 })
const limits = ref({ photos: 12, sent: 4, describe_photos: 3 })
const loading = ref(false)
const creating = ref(false)
const error = ref('')

const filtered = computed(() => !!(query.value.trim() || kind.value))
const emptyTitle = computed(() => {
  if (filtered.value) return t('brand.subjects.filteredTitle')
  return scope.value === 'one_off' ? t('brand.subjects.oneOffEmptyTitle') : t('brand.subjects.emptyTitle')
})
const emptyText = computed(() => {
  if (filtered.value) return t('brand.subjects.filteredText')
  return scope.value === 'one_off' ? t('brand.subjects.oneOffEmptyText') : t('brand.subjects.emptyText')
})

let seq = 0
async function load() {
  const mine = ++seq
  loading.value = true
  try {
    const params = { scope: scope.value }
    if (query.value.trim()) params.q = query.value.trim()
    if (kind.value) params.kind = kind.value
    const res = await api.get('/api/brand/subjects', params)
    if (mine !== seq) return
    items.value = res.items
    counts.value = res.counts || counts.value
    if (res.limits) limits.value = res.limits
    error.value = ''
  } catch (err) {
    if (mine === seq) error.value = brandErrorText(err, t, te)
  } finally {
    if (mine === seq) loading.value = false
  }
}

const reloadSoon = useDebounceFn(load, 300)

function setScope(key) {
  if (scope.value === key) return
  scope.value = key
  items.value = []
  load()
}

async function create() {
  creating.value = true
  try {
    const subject = await api.post('/api/brand/subjects', { name: '', kind: kind.value || 'product' })
    scope.value = 'library'
    query.value = ''
    await load()
    // New subjects go to the end of the list: bring the new card into view.
    await nextTick()
    const card = document.getElementById(`brand-subject-${subject.id}`)
    card?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    card?.querySelector('input')?.focus({ preventScroll: true })
  } catch (err) {
    toast.error(brandErrorText(err, t, te))
  } finally {
    creating.value = false
  }
}

function onUpdated(subject) {
  const i = items.value.findIndex((s) => s.id === subject.id)
  if (i < 0) return
  const inScope = scope.value === 'one_off' ? subject.one_off : !subject.one_off
  if (inScope) items.value.splice(i, 1, subject)
  else reloadSoon() // promoted: it moves to the other tab
}

function onRemoved(id) {
  items.value = items.value.filter((s) => s.id !== id)
  reloadSoon()
}

watch(query, reloadSoon)
watch(kind, load)

on('brand.updated', (data) => {
  if (['subject', 'subject_deleted', 'subject_order'].includes(data?.what)) reloadSoon()
})
on('reconnect', reloadSoon)

onMounted(load)
</script>
