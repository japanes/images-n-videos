<template>
  <button
    type="button"
    class="card group flex flex-col overflow-hidden text-left transition-colors hover:border-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-primary"
    @click="$emit('open', item)"
  >
    <div class="relative aspect-square w-full bg-slate-100 dark:bg-slate-900">
      <img
        v-if="item.preview_url && !broken"
        :src="item.preview_url"
        :alt="item.title"
        loading="lazy"
        decoding="async"
        class="h-full w-full object-cover"
        @error="broken = true"
      >
      <div v-else class="flex h-full flex-col gap-2 p-3 pt-10 text-xs muted">
        <AppIcon :name="item.kind === 'photo_style' ? 'image' : 'sparkles'" :size="20" />
        <p class="line-clamp-6 break-words">{{ item.description || item.prompt }}</p>
      </div>
      <span class="badge absolute left-2 top-2 bg-white/90 text-slate-700 shadow-sm dark:bg-slate-800/90 dark:text-slate-200">
        {{ t(`library.kindOne.${item.kind}`) }}
      </span>
    </div>
    <div class="min-w-0 p-3">
      <p class="line-clamp-2 break-words text-sm font-medium">{{ item.title }}</p>
      <p v-if="categoryName" class="mt-0.5 truncate text-xs muted" :title="categoryName">{{ categoryName }}</p>
    </div>
  </button>
</template>

<script setup>
import { libraryCategoryTitle } from '~/composables/useLibrary.js'

const props = defineProps({
  item: { type: Object, required: true },
})
defineEmits(['open'])
const { t, locale } = useI18n()

const broken = ref(false)
watch(() => props.item.preview_url, () => { broken.value = false })

const categoryName = computed(() => {
  const path = props.item.category_path || []
  return path.length ? libraryCategoryTitle(path[path.length - 1], locale.value) : ''
})
</script>
