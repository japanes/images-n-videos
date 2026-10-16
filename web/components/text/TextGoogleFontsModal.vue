<template>
  <!--
    Google Fonts: the catalog kept in the app (no request until «Add»). «Add»
    downloads one file from fonts.gstatic.com into the brand kit; then the
    renderer and the type specimen can use it.
  -->
  <ModalShell open :title="t('text.google.title')" size="lg" body-class="p-0" @close="$emit('close')">
    <div class="space-y-3 px-5 pb-5 pt-4 text-sm">
      <p class="text-xs muted">{{ t('text.google.hint') }}</p>
      <div class="flex flex-wrap items-center gap-2">
        <input v-model="q" class="input min-w-0 flex-1" :placeholder="t('text.google.search')" maxlength="80">
        <select v-model="category" class="input w-auto">
          <option value="">{{ t('text.google.anyCategory') }}</option>
          <option v-for="c in categories" :key="c" :value="c">{{ te(`text.google.categories.${c}`) ? t(`text.google.categories.${c}`) : c }}</option>
        </select>
        <ToggleSwitch v-model="cyrillic" :label="t('text.google.cyrillic')" />
      </div>
      <p v-if="error" class="rounded-card bg-rose-50 px-3 py-2 text-sm text-rose-800 dark:bg-rose-500/10 dark:text-rose-200">{{ error }}</p>
      <div v-if="loading && !items.length" class="flex justify-center py-6"><Spinner :size="20" /></div>
      <p v-else-if="!items.length" class="py-4 text-center muted">{{ t('text.google.nothing') }}</p>
      <ul v-else class="divide-y divide-slate-200 dark:divide-slate-700">
        <li v-for="font in items" :key="font.family" class="flex items-center gap-3 py-2">
          <div class="min-w-0 flex-1">
            <p class="truncate font-medium">{{ font.family }}</p>
            <p class="text-xs muted">
              {{ te(`text.google.categories.${font.category}`) ? t(`text.google.categories.${font.category}`) : font.category }}
              <template v-if="font.cyrillic"> · {{ t('text.google.hasCyrillic') }}</template>
              <template v-if="font.weights?.length"> · {{ t('text.google.weights', { n: font.weights.length }, font.weights.length) }}</template>
            </p>
          </div>
          <span v-if="added.includes(font.family)" class="badge bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300">
            <AppIcon name="check" :size="12" />{{ t('text.google.added') }}
          </span>
          <button
            v-else
            type="button"
            class="btn-secondary btn-sm"
            :disabled="!kitId || Boolean(adding)"
            @click="add(font.family)"
          >
            <Spinner v-if="adding === font.family" :size="12" />
            <AppIcon v-else name="plus" :size="14" />{{ t('text.google.add') }}
          </button>
        </li>
      </ul>
      <div class="flex flex-wrap items-center gap-2">
        <span class="mr-auto text-xs muted">
          {{ t('text.google.shown', { n: items.length, total }) }}
          <template v-if="takenAt"> · {{ t('text.google.takenAt', { date: takenText }) }}</template>
        </span>
        <button v-if="items.length < total" type="button" class="btn-secondary btn-sm" :disabled="loading" @click="load(true)">
          <Spinner v-if="loading" :size="12" />{{ t('text.google.more') }}
        </button>
      </div>
    </div>
  </ModalShell>
</template>

<script setup>
import { useDebounceFn } from '@vueuse/core'
import { formatDate } from '~/utils/format.js'
import { textErrorText } from '~/utils/textView.js'

const props = defineProps({
  kitId: { type: Number, default: null },
  cyrillicFirst: { type: Boolean, default: true }, // the words are in Russian or Ukrainian
})
const emit = defineEmits(['close', 'added'])
const { t, te, locale } = useI18n()
const api = useApi()
const toast = useToast()

const PAGE = 40
const q = ref('')
const category = ref('')
const cyrillic = ref(props.cyrillicFirst)
const items = ref([])
const total = ref(0)
const takenAt = ref('')
const categories = ref([])
const loading = ref(false)
const error = ref('')
const adding = ref('')
const added = ref([])
let seq = 0
// The catalog's date is a plain day (`2026-10-16`).
const takenText = computed(() => formatDate(/^\d{4}-\d\d-\d\d$/.test(takenAt.value) ? `${takenAt.value}T12:00:00Z` : takenAt.value, locale.value))

async function load(more = false) {
  const mine = ++seq
  loading.value = true
  error.value = ''
  try {
    const res = await api.get('/api/text/fonts/google', {
      q: q.value.trim() || undefined, category: category.value || undefined, cyrillic: cyrillic.value || undefined,
      offset: more ? items.value.length : 0, limit: PAGE,
    })
    if (mine !== seq) return
    items.value = more ? [...items.value, ...(res?.items || [])] : (res?.items || [])
    total.value = res?.total || 0
    takenAt.value = res?.taken_at || ''
    categories.value = res?.categories || categories.value
  } catch (err) {
    if (mine === seq) error.value = textErrorText(err, t, te)
  } finally {
    if (mine === seq) loading.value = false
  }
}

const loadLater = useDebounceFn(() => load(false), 300)
watch(q, () => loadLater())
watch([category, cyrillic], () => load(false))
onMounted(() => load(false))

async function add(family) {
  if (!props.kitId || adding.value) return
  adding.value = family
  error.value = ''
  try {
    await api.post('/api/text/fonts/google/add', { kit_id: props.kitId, family })
    added.value = [...added.value, family]
    toast.success(t('text.google.addedToast', { family }))
    emit('added', family)
  } catch (err) {
    error.value = textErrorText(err, t, te)
  } finally {
    adding.value = ''
  }
}
</script>
