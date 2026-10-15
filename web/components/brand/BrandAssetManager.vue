<template>
  <section class="card space-y-4 p-4">
    <header class="flex flex-wrap items-start gap-3">
      <div class="min-w-0 flex-1 basis-64">
        <h2 class="text-base font-semibold">{{ title }}</h2>
        <p class="mt-1 text-sm muted">{{ hint }}</p>
      </div>
      <div class="flex flex-col items-end gap-1">
        <div class="flex flex-wrap items-center justify-end gap-2">
          <label v-if="kinds.length > 1" class="flex items-center gap-2 text-xs muted">
            {{ t('brand.kit.elements.uploadAs') }}
            <select v-model="uploadKind" class="input w-36 py-1.5 text-xs" :disabled="uploading">
              <option v-for="k in kinds" :key="k" :value="k">{{ kindLabel(k) }}</option>
            </select>
          </label>
          <button type="button" class="btn-secondary btn-sm" :disabled="uploading" @click="fileInput?.click()">
            <Spinner v-if="uploading" :size="14" /><AppIcon v-else name="upload" :size="14" />{{ uploadLabel }}
          </button>
        </div>
        <span class="text-xs muted">{{ uploading ? t('brand.kit.uploading', progress) : t('brand.kit.formats', { mb: 40 }) }}</span>
      </div>
      <input ref="fileInput" type="file" class="hidden" :accept="IMAGE_ACCEPT" multiple @change="onFiles">
    </header>

    <div v-if="kinds.length > 1 && total" class="flex flex-wrap gap-1.5">
      <button
        v-for="chip in chips"
        :key="chip.key"
        type="button"
        class="badge border px-2.5 py-1"
        :class="filter === chip.key
          ? 'border-primary bg-primary/10 text-primary'
          : 'border-slate-200 text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-700/40'"
        @click="filter = chip.key"
      >
        {{ chip.label }} <span class="tabular-nums opacity-70">{{ chip.count }}</span>
      </button>
    </div>

    <p v-if="!visibleGroups.length" class="text-sm muted">{{ emptyText }}</p>
    <div v-for="group in visibleGroups" :key="group.kind" class="space-y-2">
      <div v-if="kinds.length > 1">
        <h3 class="text-sm font-medium">{{ kindLabel(group.kind) }}</h3>
        <p class="text-xs muted">{{ t(`brand.kit.elements.kindHints.${group.kind}`) }}</p>
      </div>
      <p v-if="!group.items.length" class="text-sm muted">{{ emptyText }}</p>
      <div v-else class="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
        <div
          v-for="(a, i) in group.items"
          :key="a.id"
          :draggable="armedId === a.id"
          class="rounded-card transition-shadow"
          :class="[dragId === a.id && 'opacity-50', overId === a.id && dragId !== a.id && 'ring-2 ring-primary']"
          @dragstart="onDragStart($event, group.kind, a)"
          @dragover="onDragOver($event, group.kind, a)"
          @dragleave="overId === a.id && (overId = null)"
          @drop="onDrop($event, group, i)"
          @dragend="resetDrag"
          @mouseup="armedId = null"
        >
          <BrandAssetCard
            :asset="a"
            :reorderable="group.items.length > 1"
            @arm="armedId = a.id"
            @nudge="(d) => reorder(group, i, i + d)"
            @changed="$emit('changed')"
          />
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { IMAGE_ACCEPT, assetsOfKind, brandErrorText, moveItem } from '~/utils/brand.js'

const props = defineProps({
  kit: { type: Object, required: true },
  kinds: { type: Array, required: true },
  title: { type: String, default: '' },
  hint: { type: String, default: '' },
  uploadLabel: { type: String, default: '' },
  emptyText: { type: String, default: '' },
})
const emit = defineEmits(['changed'])
const { t, te } = useI18n()
const api = useApi()
const toast = useToast()

const fileInput = ref(null)
const uploadKind = ref(props.kinds[0])
const uploading = ref(false)
const progress = ref({ done: 0, total: 0 })
const filter = ref('all')

// Order shown right after a drag, until the reloaded kit arrives.
const pendingOrder = ref({})
watch(() => props.kit.assets, () => { pendingOrder.value = {} })

const kindLabel = (k) => (k === 'reference' ? t('brand.kit.references.title') : t(`brand.kit.elements.kinds.${k}`))

const groups = computed(() => props.kinds.map((kind) => {
  let items = assetsOfKind(props.kit.assets, kind)
  const ids = pendingOrder.value[kind]
  if (ids) items = ids.map((id) => items.find((a) => a.id === id)).filter(Boolean)
  return { kind, items }
}))
const total = computed(() => groups.value.reduce((n, g) => n + g.items.length, 0))
const chips = computed(() => [
  { key: 'all', label: t('brand.kit.elements.all'), count: total.value },
  ...groups.value.map((g) => ({ key: g.kind, label: kindLabel(g.kind), count: g.items.length })),
])
const visibleGroups = computed(() => {
  if (filter.value !== 'all') return groups.value.filter((g) => g.kind === filter.value)
  return groups.value.filter((g) => g.items.length)
})

async function onFiles(e) {
  const files = [...(e.target.files || [])]
  e.target.value = ''
  if (!files.length) return
  const kind = uploadKind.value
  uploading.value = true
  progress.value = { done: 0, total: files.length }
  for (const file of files) {
    try {
      await api.upload(`/api/brand/kits/${props.kit.id}/assets`, file, { kind })
    } catch (err) {
      toast.error(`${file.name}: ${brandErrorText(err, t, te)}`)
    }
    progress.value = { done: progress.value.done + 1, total: files.length }
  }
  uploading.value = false
  if (props.kinds.length > 1 && filter.value !== 'all') filter.value = kind
  emit('changed')
}

async function reorder(group, from, to) {
  if (to < 0 || to >= group.items.length || from === to) return
  const ids = moveItem(group.items, from, to).map((a) => a.id)
  pendingOrder.value = { ...pendingOrder.value, [group.kind]: ids }
  try {
    await api.put(`/api/brand/kits/${props.kit.id}/assets/order`, { ids })
  } catch (err) {
    toast.error(brandErrorText(err, t, te))
  }
  emit('changed')
}

// Drag and drop inside one kind; a card only becomes draggable while its handle is pressed.
const armedId = ref(null)
const dragId = ref(null)
const dragKind = ref(null)
const overId = ref(null)

function onDragStart(e, kind, a) {
  if (armedId.value !== a.id) { e.preventDefault(); return }
  dragId.value = a.id
  dragKind.value = kind
  e.dataTransfer.effectAllowed = 'move'
  e.dataTransfer.setData('text/plain', String(a.id))
}

function onDragOver(e, kind, a) {
  if (!dragId.value || dragKind.value !== kind) return
  e.preventDefault()
  e.dataTransfer.dropEffect = 'move'
  overId.value = a.id
}

function onDrop(e, group, toIndex) {
  if (!dragId.value || dragKind.value !== group.kind) return
  e.preventDefault()
  const from = group.items.findIndex((a) => a.id === dragId.value)
  resetDrag()
  reorder(group, from, toIndex)
}

function resetDrag() {
  dragId.value = null
  dragKind.value = null
  overId.value = null
  armedId.value = null
}
</script>
