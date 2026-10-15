<template>
  <nav class="text-sm" :aria-label="t('library.categories')">
    <button
      type="button"
      class="flex w-full items-center gap-2 rounded-button px-2 py-1.5 text-left"
      :class="!selected ? 'bg-primary/10 font-medium text-primary' : 'hover:bg-slate-100 dark:hover:bg-slate-700/60'"
      @click="$emit('select', '')"
    >
      <AppIcon name="library" :size="14" />
      <span class="min-w-0 flex-1 truncate">{{ t('library.allCategories') }}</span>
      <span class="text-xs tabular-nums muted">{{ total }}</span>
    </button>

    <ul class="mt-1 space-y-px">
      <li v-for="row in rows" :key="row.node.slug" class="flex items-center" :style="{ paddingLeft: `${row.depth * 0.75}rem` }">
        <button
          v-if="row.node.children.length"
          type="button"
          class="grid h-6 w-6 shrink-0 place-items-center rounded text-slate-500 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-700/60"
          :aria-expanded="open.has(row.node.slug)"
          :aria-label="open.has(row.node.slug) ? t('library.collapse') : t('library.expand')"
          @click="toggle(row.node.slug)"
        >
          <AppIcon :name="open.has(row.node.slug) ? 'chevron-down' : 'chevron-right'" :size="14" />
        </button>
        <span v-else class="w-6 shrink-0" />
        <button
          type="button"
          class="flex min-w-0 flex-1 items-center gap-2 rounded-button px-2 py-1 text-left"
          :class="selected === row.node.slug
            ? 'bg-primary/10 font-medium text-primary'
            : ['hover:bg-slate-100 dark:hover:bg-slate-700/60', !row.node.count && 'text-slate-400 dark:text-slate-500']"
          :title="titleOf(row.node)"
          :aria-current="selected === row.node.slug ? 'true' : undefined"
          @click="pick(row.node)"
        >
          <span class="min-w-0 flex-1 truncate">{{ titleOf(row.node) }}</span>
          <span class="text-xs tabular-nums muted">{{ row.node.count }}</span>
        </button>
      </li>
    </ul>

    <div class="mt-3 border-t border-slate-200 px-1 pt-3 dark:border-slate-700">
      <ToggleSwitch :model-value="hideEmpty" :label="t('library.hideEmpty')" @update:model-value="$emit('update:hideEmpty', $event)" />
    </div>
  </nav>
</template>

<script setup>
import { libraryAncestors, libraryCategoryTitle, libraryPruneEmpty, libraryVisibleRows } from '~/composables/useLibrary.js'

const props = defineProps({
  nodes: { type: Array, default: () => [] }, // libraryBuildTree() output
  total: { type: Number, default: 0 },
  selected: { type: String, default: '' },
  hideEmpty: { type: Boolean, default: false },
})
const emit = defineEmits(['select', 'update:hideEmpty'])
const { t, locale } = useI18n()

const open = ref(new Set())
const titleOf = (node) => libraryCategoryTitle(node, locale.value)
const shown = computed(() => (props.hideEmpty ? libraryPruneEmpty(props.nodes) : props.nodes))
const rows = computed(() => libraryVisibleRows(shown.value, open.value))

function toggle(slug) {
  const next = new Set(open.value)
  if (next.has(slug)) next.delete(slug)
  else next.add(slug)
  open.value = next
}

function pick(node) {
  if (node.children.length && !open.value.has(node.slug)) toggle(node.slug)
  emit('select', node.slug)
}

// The chosen category is always visible: open its parents.
watch(() => props.selected, (slug) => {
  const missing = libraryAncestors(slug).filter((s) => !open.value.has(s))
  if (missing.length) open.value = new Set([...open.value, ...missing])
}, { immediate: true })
</script>
