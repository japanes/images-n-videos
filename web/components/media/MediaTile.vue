<template>
  <li class="group relative min-w-0">
    <button
      type="button"
      class="relative block aspect-square w-full overflow-hidden rounded-card bg-slate-100 outline-none ring-2 ring-offset-2 ring-offset-white focus-visible:ring-primary dark:bg-slate-900 dark:ring-offset-slate-800"
      :class="selected ? 'ring-primary' : 'ring-transparent'"
      :aria-label="name"
      :aria-pressed="selecting ? selected : undefined"
      @click="onClick"
      @mouseenter="hover = true"
      @mouseleave="hover = false"
    >
      <img
        v-if="thumb && !broken"
        :src="thumb"
        alt=""
        loading="lazy"
        decoding="async"
        class="h-full w-full object-cover"
        @error="broken = true"
      >
      <span v-else class="flex h-full w-full flex-col items-center justify-center gap-2 px-2 text-center text-slate-400 dark:text-slate-500">
        <MediaAudioGlyph v-if="item.kind === 'audio'" :size="34" />
        <AppIcon v-else :name="item.kind === 'video' ? 'video' : 'image'" :size="30" />
        <span v-if="busy" class="flex items-center gap-1 text-xs"><Spinner :size="12" />{{ t('media.tile.processing') }}</span>
        <span v-else-if="failed" class="flex items-center gap-1 text-xs text-amber-600 dark:text-amber-400">
          <AppIcon name="alert" :size="12" />{{ t('media.tile.noPreview') }}
        </span>
        <span v-else-if="item.kind === 'audio'" class="max-w-full truncate text-xs">{{ item.ext?.toUpperCase() }}</span>
      </span>

      <img
        v-if="hover && item.preview_url"
        :src="item.preview_url"
        alt=""
        class="absolute inset-0 h-full w-full object-cover"
      >

      <span
        v-if="item.kind === 'video' || item.kind === 'audio'"
        class="absolute bottom-1.5 right-1.5 flex items-center gap-1 rounded-badge bg-slate-950/70 px-1.5 py-0.5 text-[11px] font-medium tabular-nums text-white"
      >
        <AppIcon v-if="item.kind === 'video'" name="play" :size="10" />
        <MediaAudioGlyph v-else :size="10" />
        <span v-if="item.duration">{{ formatDuration(item.duration) }}</span>
      </span>

      <span
        v-if="item.usage_count > 0"
        class="absolute bottom-1.5 left-1.5 rounded-badge bg-primary/90 px-1.5 py-0.5 text-[11px] font-medium text-white"
        :title="t('media.tile.usedTitle', { n: item.usage_count }, item.usage_count)"
      >{{ t('media.tile.used') }}</span>
      <span
        v-else-if="item.usage_count === null"
        class="absolute bottom-1.5 left-1.5 rounded-badge bg-amber-500/90 px-1.5 py-0.5 text-white"
        :title="t('media.usages.unknown')"
      ><AppIcon name="alert" :size="11" /></span>
    </button>

    <label
      class="absolute left-2 top-2 grid h-6 w-6 cursor-pointer place-items-center rounded-badge bg-white/90 shadow-sm transition-opacity dark:bg-slate-800/90"
      :class="selecting || selected ? 'opacity-100' : 'opacity-0 group-hover:opacity-100 focus-within:opacity-100'"
      :title="t('media.select.one')"
    >
      <input
        type="checkbox"
        class="h-4 w-4 cursor-pointer accent-primary"
        :checked="selected"
        :aria-label="t('media.select.oneNamed', { name })"
        @change="$emit('toggle', item)"
      >
    </label>

    <p class="mt-1.5 truncate text-sm" :title="name">{{ name }}</p>
    <p class="truncate text-xs muted">
      {{ formatBytes(item.size_bytes) }} · {{ formatDate(item.created_at, locale) }}
    </p>
  </li>
</template>

<script setup>
import { formatBytes, formatDate, formatDuration } from '~/utils/format.js'
import { mediaDisplayName, mediaIngestBusy, mediaIngestFailed } from '~/composables/useMediaLibrary.js'

const props = defineProps({
  item: { type: Object, required: true },
  selected: { type: Boolean, default: false },
  // Some files are selected: a click selects instead of opening.
  selecting: { type: Boolean, default: false },
})
const emit = defineEmits(['open', 'toggle'])
const { t, locale } = useI18n()

const hover = ref(false)
const broken = ref(false)
const name = computed(() => mediaDisplayName(props.item))
const thumb = computed(() => props.item.thumb_url)
const busy = computed(() => mediaIngestBusy(props.item))
const failed = computed(() => mediaIngestFailed(props.item))

watch(thumb, () => { broken.value = false })

function onClick(e) {
  if (props.selecting || e.ctrlKey || e.metaKey || e.shiftKey) emit('toggle', props.item)
  else emit('open', props.item)
}
</script>
