<template>
  <div class="page space-y-4">
    <header class="flex flex-wrap items-start gap-3">
      <div class="min-w-0 flex-1">
        <h1 class="page-title">{{ t('library.title') }}</h1>
        <p class="mt-1 text-sm muted">{{ t('library.subtitle') }}</p>
      </div>
      <button type="button" class="btn-secondary" :disabled="rolling" :title="t('library.random')" :aria-label="t('library.random')" @click="openRandom">
        <Spinner v-if="rolling" :size="16" /><AppIcon v-else name="dice" :size="16" />
      </button>
      <button type="button" class="btn-primary" @click="openCreate">
        <AppIcon name="plus" :size="16" />{{ t('library.newStyle') }}
      </button>
    </header>

    <section class="card">
      <div class="flex flex-wrap items-center gap-1 border-b border-slate-200 px-2 pt-2 dark:border-slate-700" role="tablist">
        <button
          v-for="tab in LIBRARY_TABS"
          :key="tab"
          type="button"
          role="tab"
          :aria-selected="filters.tab === tab"
          class="-mb-px border-b-2 px-3 py-2 text-sm"
          :class="filters.tab === tab ? 'border-primary font-medium text-primary' : 'border-transparent muted hover:text-slate-700 dark:hover:text-slate-200'"
          @click="setFilters({ tab, category: '' })"
        >
          {{ t(`library.tabs.${tab}`) }}
        </button>
      </div>
      <div class="flex flex-wrap items-center gap-3 px-4 py-3">
        <div class="inline-flex rounded-button border border-slate-200 p-0.5 dark:border-slate-700">
          <button
            v-for="k in kindOptions"
            :key="k || 'all'"
            type="button"
            class="rounded-button px-3 py-1.5 text-sm"
            :class="filters.kind === k ? 'bg-primary/10 font-medium text-primary' : 'muted hover:text-slate-700 dark:hover:text-slate-200'"
            :aria-pressed="filters.kind === k"
            @click="setFilters({ kind: k })"
          >
            {{ t(`library.kinds.${k || 'all'}`) }}
          </button>
        </div>
        <label class="relative block min-w-[12rem] flex-1">
          <span class="pointer-events-none absolute inset-y-0 left-3 flex items-center text-slate-400"><AppIcon name="search" :size="16" /></span>
          <input v-model="search" type="search" class="input pl-9" maxlength="200" :placeholder="t('library.searchPlaceholder')" :aria-label="t('common.search')">
        </label>
      </div>
    </section>

    <div class="grid gap-4 md:grid-cols-[16rem_minmax(0,1fr)]">
      <aside class="min-w-0">
        <button type="button" class="btn-secondary w-full justify-between md:hidden" :aria-expanded="treeOpen" @click="treeOpen = !treeOpen">
          <span class="min-w-0 truncate">{{ t('library.categories') }}: {{ selectedTitle || t('library.allCategories') }}</span>
          <AppIcon :name="treeOpen ? 'chevron-down' : 'chevron-right'" :size="16" />
        </button>
        <div
          class="card mt-2 p-2 md:sticky md:top-4 md:mt-0 md:block md:max-h-[calc(100vh-2rem)] md:overflow-y-auto"
          :class="treeOpen ? 'block max-h-[60vh] overflow-y-auto' : 'hidden'"
        >
          <LibraryCategoryTree
            :nodes="tree"
            :total="categories.total"
            :selected="filters.category"
            :hide-empty="hideEmpty"
            @update:hide-empty="setHideEmpty"
            @select="pickCategory"
          />
        </div>
      </aside>

      <section class="min-w-0 space-y-4">
        <div v-if="loading && !items.length" class="grid place-items-center py-16"><Spinner :size="24" /></div>
        <div v-else-if="loadError" class="card">
          <EmptyState icon="alert" :title="t('library.loadError')" :text="loadError">
            <button type="button" class="btn-secondary" @click="reloadAll"><AppIcon name="refresh" :size="16" />{{ t('common.retry') }}</button>
          </EmptyState>
        </div>
        <div v-else-if="!items.length" class="card">
          <EmptyState v-if="mineIsEmpty" icon="library" :title="t('library.emptyMineTitle')" :text="t('library.emptyMineText')">
            <button type="button" class="btn-primary" @click="openCreate"><AppIcon name="plus" :size="16" />{{ t('library.newStyle') }}</button>
          </EmptyState>
          <EmptyState v-else icon="search" :title="t('library.emptyTitle')" :text="t('library.emptyText')" />
        </div>
        <template v-else>
          <div class="grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-4" :class="loading && 'opacity-60'">
            <LibraryStyleCard v-for="it in items" :key="it.id" :item="it" @open="openDetails(it.id)" />
          </div>
          <div class="flex flex-wrap items-center justify-center gap-3 text-sm">
            <span class="muted">{{ t('library.shown', { shown: items.length, total }) }}</span>
            <button v-if="items.length < total" type="button" class="btn-secondary" :disabled="loadingMore" @click="loadMore">
              <Spinner v-if="loadingMore" :size="14" />{{ t('library.more') }}
            </button>
          </div>
        </template>
      </section>
    </div>

    <LibraryStyleDetails
      :open="!!detailsId"
      :style-id="detailsId"
      @close="openDetails(null)"
      @edit="openEdit"
      @copied="showInMine"
      @deleted="onDeleted"
    />
    <LibraryStyleEditor
      :open="editor.open"
      :item="editor.item"
      :nodes="tree"
      :default-kind="filters.kind || 'style'"
      :default-category="filters.category"
      @close="editor.open = false"
      @saved="onSaved"
    />
  </div>
</template>

<script setup>
import { useDebounceFn } from '@vueuse/core'
import {
  LIBRARY_KINDS, LIBRARY_PAGE_SIZE, LIBRARY_TABS, libraryBuildTree, libraryCategoryTitle, libraryErrorText,
  libraryFiltersFromQuery, libraryFiltersToQuery, useLibrary,
} from '~/composables/useLibrary.js'

const { t, te, locale } = useI18n()
const route = useRoute()
const router = useRouter()
const lib = useLibrary()
const toast = useToast()
const { on } = useEvents()

const HIDE_EMPTY_KEY = 'vf.library.hideEmpty'
const kindOptions = ['', ...LIBRARY_KINDS]

const filters = ref(libraryFiltersFromQuery(route.query))
const search = ref(filters.value.q)
const items = ref([])
const total = ref(0)
const loading = ref(false)
const loadingMore = ref(false)
const loadError = ref('')
const categories = ref({ items: [], total: 0, uncategorized: 0 })
const treeOpen = ref(false)
const hideEmpty = ref(readHideEmpty())
const rolling = ref(false)
const editor = ref({ open: false, item: null })

const tree = computed(() => libraryBuildTree(categories.value.items))
const selectedTitle = computed(() => {
  const cat = categories.value.items.find((c) => c.slug === filters.value.category)
  return cat ? libraryCategoryTitle(cat, locale.value) : ''
})
const mineIsEmpty = computed(() => filters.value.tab === 'mine' && !filters.value.kind && !filters.value.category && !filters.value.q)
const detailsId = computed(() => {
  const n = Number(Array.isArray(route.query.style) ? route.query.style[0] : route.query.style)
  return Number.isInteger(n) && n > 0 ? n : null
})

// --- the "hide empty categories" switch is a per-browser convenience ---------------------------

function readHideEmpty() {
  try { return localStorage.getItem(HIDE_EMPTY_KEY) === '1' } catch { return false }
}
function setHideEmpty(value) {
  hideEmpty.value = value
  try { localStorage.setItem(HIDE_EMPTY_KEY, value ? '1' : '0') } catch { /* storage may be blocked */ }
}

// --- loading -----------------------------------------------------------------------------------

let listSeq = 0
let catSeq = 0

async function loadList({ keep = false } = {}) {
  const seq = ++listSeq
  loading.value = true
  loadError.value = ''
  const limit = keep ? Math.min(200, Math.max(LIBRARY_PAGE_SIZE, items.value.length)) : LIBRARY_PAGE_SIZE
  try {
    const res = await lib.styles({ ...filters.value, limit, offset: 0 })
    if (seq !== listSeq) return
    items.value = res.items || []
    total.value = res.total || 0
  } catch (err) {
    if (seq !== listSeq) return
    items.value = []
    total.value = 0
    loadError.value = libraryErrorText(err, t, te)
  } finally {
    if (seq === listSeq) loading.value = false
  }
}

async function loadMore() {
  const seq = listSeq
  loadingMore.value = true
  try {
    const res = await lib.styles({ ...filters.value, offset: items.value.length })
    if (seq !== listSeq) return
    const seen = new Set(items.value.map((i) => i.id))
    items.value = [...items.value, ...(res.items || []).filter((i) => !seen.has(i.id))]
    total.value = res.total || 0
  } catch (err) {
    toast.error(libraryErrorText(err, t, te))
  } finally {
    loadingMore.value = false
  }
}

async function loadCategories() {
  const seq = ++catSeq
  try {
    const res = await lib.categories({ tab: filters.value.tab, kind: filters.value.kind })
    if (seq === catSeq) categories.value = res
  } catch (err) {
    if (seq === catSeq) toast.error(libraryErrorText(err, t, te))
  }
}

function reloadAll() {
  loadList({ keep: true })
  loadCategories()
}
const scheduleReload = useDebounceFn(reloadAll, 500)

// --- filters and the address bar ---------------------------------------------------------------

function syncQuery(styleId = detailsId.value) {
  const query = libraryFiltersToQuery(filters.value)
  if (styleId) query.style = String(styleId)
  router.replace({ query })
}

function setFilters(patch) {
  const next = { ...filters.value, ...patch }
  if (JSON.stringify(next) === JSON.stringify(filters.value)) return
  const scopeChanged = next.tab !== filters.value.tab || next.kind !== filters.value.kind
  filters.value = next
  if (search.value.trim() !== next.q) search.value = next.q
  syncQuery()
  loadList()
  if (scopeChanged) loadCategories()
}

function pickCategory(slug) {
  treeOpen.value = false
  setFilters({ category: slug })
}

const applySearch = useDebounceFn((value) => setFilters({ q: value.trim().slice(0, 200) }), 350)
watch(search, (v) => { if (v.trim() !== filters.value.q) applySearch(v) })

// Back/forward through filter states.
watch(() => route.query, (q) => {
  const next = libraryFiltersFromQuery(q)
  if (JSON.stringify(next) === JSON.stringify(filters.value)) return
  const scopeChanged = next.tab !== filters.value.tab || next.kind !== filters.value.kind
  filters.value = next
  search.value = next.q
  loadList()
  if (scopeChanged) loadCategories()
})

// --- details, editor, dice ---------------------------------------------------------------------

function openDetails(id) {
  syncQuery(id)
}

function openCreate() {
  editor.value = { open: true, item: null }
}

function openEdit(item) {
  editor.value = { open: true, item }
}

// A new style or a copy lives in "Mine": show that tab with nothing filtered out.
function showInMine(style) {
  filters.value = { tab: 'mine', kind: '', category: '', q: '' }
  search.value = ''
  syncQuery(style?.id || null)
  loadList()
  loadCategories()
}

function onSaved(style) {
  const created = !editor.value.item
  editor.value = { open: false, item: null }
  if (created) showInMine(style)
  else scheduleReload()
}

function onDeleted() {
  openDetails(null)
  scheduleReload()
}

async function openRandom() {
  rolling.value = true
  try {
    const { item } = await lib.random({
      kind: filters.value.kind,
      tab: filters.value.tab,
      category: filters.value.category,
      exclude: detailsId.value,
    })
    if (item) openDetails(item.id)
    else toast.info(t('library.emptyTitle'))
  } catch (err) {
    toast.error(libraryErrorText(err, t, te))
  } finally {
    rolling.value = false
  }
}

on('library.updated', scheduleReload)
on('reconnect', scheduleReload)

onMounted(() => {
  loadList()
  loadCategories()
})
</script>
