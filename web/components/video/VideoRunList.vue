<template>
  <!-- Recent videos: open one or start a new one. Emits `open(item)` with { id, link, … }. -->
  <section class="space-y-4">
    <div class="flex items-center gap-2">
      <h2 class="font-semibold">{{ t('video.list.title') }}</h2>
      <button type="button" class="btn-primary btn-sm ml-auto" :disabled="creating" @click="create">
        <Spinner v-if="creating" :size="14" /><AppIcon v-else name="plus" :size="16" />{{ t('video.list.new') }}
      </button>
    </div>

    <div v-if="list.loading.value && !list.items.value.length" class="flex justify-center py-16"><Spinner /></div>
    <EmptyState v-else-if="!list.items.value.length" icon="video" :title="t('video.list.empty')" :text="t('video.list.emptyHint')" />
    <div v-else class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <button
        v-for="item in list.items.value"
        :key="item.id"
        type="button"
        class="card flex flex-col overflow-hidden text-left hover:border-primary"
        @click="$emit('open', item)"
      >
        <span class="relative block w-full bg-slate-100 dark:bg-slate-900" :style="{ aspectRatio: videoAspectRatio(item.aspect) }">
          <img v-if="item.thumb_url" :src="item.thumb_url" alt="" loading="lazy" class="h-full w-full object-cover">
          <span v-else class="absolute inset-0 flex items-center justify-center text-slate-400"><AppIcon name="video" :size="32" /></span>
        </span>
        <span class="flex flex-col gap-1 p-3">
          <span class="truncate font-medium">{{ item.title || t('video.workspace.untitled') }}</span>
          <span class="muted text-xs">
            {{ t(`video.statuses.${item.status}`) }}
            <template v-if="item.duration"> · {{ t('video.form.seconds', { n: videoSeconds(item.duration) }) }}</template>
            · {{ formatDateTime(item.updated_at, locale) }}
          </span>
        </span>
      </button>
    </div>
  </section>
</template>

<script setup>
import { formatDateTime } from '~/utils/format.js'
import { videoAspectRatio, videoSeconds } from '~/utils/videoView.js'

const props = defineProps({
  limit: { type: Number, default: 50 },
})
const emit = defineEmits(['open'])
const { t, locale } = useI18n()
const list = useVideoRuns({ limit: props.limit })
const creating = ref(false)

onMounted(() => list.load())

async function create() {
  creating.value = true
  try {
    const run = await list.create({})
    if (run) emit('open', run)
  } finally {
    creating.value = false
  }
}
</script>
