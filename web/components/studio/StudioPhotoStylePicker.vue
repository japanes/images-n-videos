<template>
  <!-- The photo style: a button with the current choice that opens a grid of styles with previews. -->
  <div>
    <button
      type="button"
      class="input flex items-center gap-2 text-left"
      :disabled="disabled"
      @click="show"
    >
      <span class="flex h-7 w-7 shrink-0 items-center justify-center overflow-hidden rounded bg-slate-100 dark:bg-slate-700">
        <img v-if="current?.preview_url" :src="current.preview_url" alt="" class="h-full w-full object-cover">
        <AppIcon v-else name="image" :size="14" class="opacity-60" />
      </span>
      <span class="min-w-0 flex-1 truncate">{{ current ? current.title : t('studio.settings.plainPhoto') }}</span>
      <AppIcon name="more" :size="16" class="shrink-0 opacity-60" />
    </button>

    <ModalShell :open="open" :title="t('studio.photoStyle.title')" size="xl" @close="open = false">
      <p class="muted mb-3 text-sm">{{ t('studio.photoStyle.hint') }}</p>
      <input
        v-model="q"
        type="search"
        class="input mb-3"
        :placeholder="t('studio.photoStyle.search')"
        :aria-label="t('studio.photoStyle.search')"
      >
      <div v-if="lists.categories.length > 1" class="mb-4 flex flex-wrap gap-1.5">
        <button
          v-for="c in [{ key: '', title: t('studio.photoStyle.all') }, ...lists.categories]"
          :key="c.key"
          type="button"
          class="rounded-full border px-3 py-1 text-xs"
          :class="category === c.key ? 'border-primary bg-primary/10 text-primary' : 'border-slate-200 hover:border-primary dark:border-slate-600'"
          :aria-pressed="category === c.key"
          @click="category = c.key"
        >
          {{ c.title || t('studio.photoStyle.other') }}
        </button>
      </div>

      <div class="space-y-5">
        <button
          type="button"
          class="flex w-full items-center gap-3 rounded-card border px-3 py-2 text-left text-sm"
          :class="draft === null ? 'border-primary text-primary' : 'border-slate-200 hover:border-primary dark:border-slate-600'"
          :aria-pressed="draft === null"
          @click="draft = null"
          @dblclick="apply(null)"
        >
          <AppIcon name="close" :size="18" class="shrink-0 opacity-70" />
          <span>
            <span class="block font-medium">{{ t('studio.settings.plainPhoto') }}</span>
            <span class="muted block text-xs">{{ t('studio.photoStyle.noneHint') }}</span>
          </span>
        </button>

        <p v-if="loading && !items.length" class="muted py-6 text-center text-sm">{{ t('common.loading') }}</p>
        <p v-else-if="!lists.groups.length" class="muted py-6 text-center text-sm">{{ t('studio.photoStyle.empty') }}</p>

        <section v-for="g in lists.groups" :key="g.key" class="space-y-2">
          <h3 class="muted text-[11px] font-semibold uppercase tracking-wide">{{ g.title || t('studio.photoStyle.other') }}</h3>
          <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <button
              v-for="st in g.items"
              :key="st.id"
              type="button"
              class="group min-w-0 text-left"
              :aria-pressed="draft === st.id"
              :title="st.description || st.title"
              @click="draft = st.id"
              @dblclick="apply(st.id)"
            >
              <span
                class="relative block aspect-square overflow-hidden rounded-card border-2 bg-slate-100 dark:bg-slate-700"
                :class="draft === st.id ? 'border-primary' : 'border-transparent group-hover:border-slate-300 dark:group-hover:border-slate-500'"
              >
                <template v-if="st.preview_url">
                  <img :src="st.preview_url" alt="" class="absolute inset-0 h-full w-full scale-110 object-cover opacity-60 blur-xl" aria-hidden="true">
                  <img :src="st.preview_url" alt="" class="relative h-full w-full object-contain" loading="lazy">
                </template>
                <span v-else class="flex h-full w-full flex-col items-center justify-center gap-1 opacity-50">
                  <AppIcon name="image" :size="28" />
                  <span class="text-[11px]">{{ t('studio.photoStyle.noPreview') }}</span>
                </span>
              </span>
              <span class="mt-1 block truncate text-sm" :class="draft === st.id ? 'text-primary' : ''">{{ st.title }}</span>
            </button>
          </div>
        </section>

        <p v-if="total > items.length" class="muted text-center text-xs">
          {{ t('studio.photoStyle.more', { count: total - items.length }) }}
        </p>
      </div>

      <template #footer>
        <button type="button" class="btn-secondary" @click="open = false">{{ t('common.cancel') }}</button>
        <button type="button" class="btn-primary" @click="apply(draft)">{{ t('common.save') }}</button>
      </template>
    </ModalShell>
  </div>
</template>

<script setup>
import { studioPhotoStyleGroups } from '~/utils/studioView.js'

const props = defineProps({
  modelValue: { type: Number, default: null }, // library style id or null
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue'])
const { t, locale } = useI18n()
const api = useApi()

const open = ref(false)
const items = ref([])
const total = ref(0)
const loading = ref(false)
const draft = ref(null)
const q = ref('')
const category = ref('')

const current = computed(() => items.value.find((st) => st.id === props.modelValue) || null)
const lists = computed(() => studioPhotoStyleGroups(items.value, { q: q.value, category: category.value }, locale.value))

async function load() {
  loading.value = true
  try {
    const res = await api.get('/api/library/styles', { kind: 'photo_style', tab: 'all', limit: 200 })
    items.value = res.items || []
    total.value = res.total || items.value.length
  } catch {
    // The button still works with what was loaded before; the grid says it is empty.
  } finally {
    loading.value = false
  }
}

function show() {
  draft.value = props.modelValue ?? null
  q.value = ''
  category.value = ''
  open.value = true
  load()
}

function apply(id) {
  open.value = false
  if (id !== (props.modelValue ?? null)) emit('update:modelValue', id)
}

onMounted(load)
</script>
