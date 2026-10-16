<template>
  <!-- All studio works: open one, start a new one, rename, archive, delete. -->
  <section class="space-y-4">
    <div class="flex flex-wrap items-center gap-2">
      <div class="flex gap-1">
        <button
          v-for="tb in ['active', 'archived']"
          :key="tb"
          type="button"
          class="btn-sm"
          :class="list.status.value === tb ? 'btn-primary' : 'btn-secondary'"
          @click="list.status.value = tb"
        >{{ t(`studio.gallery.tabs.${tb}`) }}</button>
      </div>
      <input
        v-model="list.query.value"
        type="search"
        class="input min-w-0 max-w-xs flex-1"
        :placeholder="t('studio.gallery.search')"
        :aria-label="t('studio.gallery.search')"
      >
      <button type="button" class="btn-primary ml-auto" :disabled="creating" @click="create">
        <Spinner v-if="creating" :size="14" /><AppIcon v-else name="plus" :size="16" />{{ t('studio.gallery.new') }}
      </button>
    </div>

    <div v-if="list.loading.value && !list.items.value.length" class="flex justify-center py-16"><Spinner /></div>
    <EmptyState
      v-else-if="!list.items.value.length"
      icon="image"
      :title="list.status.value === 'archived' ? t('studio.gallery.emptyArchived') : t('studio.gallery.empty')"
      :text="list.status.value === 'archived' ? '' : t('studio.gallery.emptyHint')"
    />
    <div v-else class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
      <article v-for="w in list.items.value" :key="w.id" class="card flex flex-col overflow-hidden">
        <button
          type="button"
          class="relative block bg-slate-100 dark:bg-slate-900"
          :style="{ aspectRatio: studioAspectRatio(w.aspect) }"
          :aria-label="t('studio.gallery.open')"
          @click="$emit('open', w)"
        >
          <img v-if="w.cover" :src="w.cover.thumb_url || w.cover.url" alt="" loading="lazy" class="h-full w-full object-cover">
          <span v-else class="absolute inset-0 flex items-center justify-center text-slate-400"><AppIcon name="image" :size="32" /></span>
        </button>
        <div class="flex flex-1 flex-col gap-1 p-3">
          <button type="button" class="truncate text-left font-medium hover:text-primary" @click="$emit('open', w)">
            {{ w.title || t('studio.gallery.untitled') }}
          </button>
          <p class="muted text-xs">
            {{ t('studio.gallery.progress', { done: w.done_count || 0, total: w.frame_count || 0 }) }}
            <template v-if="w.kit_name"> · {{ w.kit_name }}</template>
            <template v-if="w.cost_usd"> · {{ formatUsd(w.cost_usd) }}</template>
          </p>
          <p class="muted text-xs">{{ formatDateTime(w.updated_at, locale) }}</p>
          <div class="mt-auto flex items-center gap-1 pt-2">
            <button type="button" class="btn-ghost p-1.5" :title="t('studio.gallery.rename')" :aria-label="t('studio.gallery.rename')" @click="startRename(w)">
              <AppIcon name="edit" :size="16" />
            </button>
            <button
              type="button"
              class="btn-ghost p-1.5"
              :title="w.status === 'archived' ? t('studio.gallery.unarchive') : t('studio.gallery.archive')"
              :aria-label="w.status === 'archived' ? t('studio.gallery.unarchive') : t('studio.gallery.archive')"
              @click="w.status === 'archived' ? list.unarchive(w.id) : list.archive(w.id)"
            ><AppIcon name="archive" :size="16" /></button>
            <button
              type="button"
              class="btn-ghost ml-auto p-1.5 text-rose-600 dark:text-rose-400"
              :title="t('common.delete')"
              :aria-label="t('common.delete')"
              @click="remove(w)"
            ><AppIcon name="trash" :size="16" /></button>
          </div>
        </div>
      </article>
    </div>
    <div v-if="list.hasMore.value" class="flex justify-center">
      <button type="button" class="btn-secondary btn-sm" :disabled="list.loading.value" @click="list.loadMore()">{{ t('studio.gallery.more') }}</button>
    </div>

    <ModalShell :open="Boolean(renaming)" :title="t('studio.gallery.rename')" size="sm" @close="renaming = null">
      <input
        v-model="newTitle"
        type="text"
        class="input"
        :maxlength="STUDIO_LIMITS.title"
        :aria-label="t('studio.settings.title')"
        @keydown.enter="saveRename"
      >
      <template #footer>
        <button type="button" class="btn-secondary" @click="renaming = null">{{ t('common.cancel') }}</button>
        <button type="button" class="btn-primary" :disabled="!newTitle.trim()" @click="saveRename">{{ t('common.save') }}</button>
      </template>
    </ModalShell>
  </section>
</template>

<script setup>
import { formatDateTime, formatUsd } from '~/utils/format.js'
import { STUDIO_LIMITS, studioAspectRatio } from '~/utils/studioView.js'

const emit = defineEmits(['open'])
const { t, locale } = useI18n()
const { confirm } = useConfirm()

const list = useStudioWorks()
onMounted(() => list.load())

const creating = ref(false)
async function create() {
  creating.value = true
  try {
    const work = await list.create({})
    if (work?.id) emit('open', work)
  } finally {
    creating.value = false
  }
}

const renaming = ref(null)
const newTitle = ref('')
function startRename(w) {
  renaming.value = w
  newTitle.value = w.title || ''
}
async function saveRename() {
  const text = newTitle.value.trim()
  if (!renaming.value || !text) return
  const id = renaming.value.id
  renaming.value = null
  if (text !== (list.items.value.find((w) => w.id === id)?.title || '')) await list.rename(id, text)
}

async function remove(w) {
  const ok = await confirm({
    message: t('studio.gallery.removeAsk', { title: w.title || t('studio.gallery.untitled') }),
    confirmLabel: t('common.delete'),
    tone: 'danger',
  })
  if (ok) await list.remove(w.id)
}
</script>
