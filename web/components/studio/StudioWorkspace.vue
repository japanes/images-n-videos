<template>
  <!--
    One studio work: the frames, the settings panel beside them and the frame
    viewer. The chat (module 15) puts it in its feed; the controller is exposed
    so the chat can drive the same work (generate, open a frame).
  -->
  <div class="space-y-4">
    <div v-if="studio.loading.value && !work" class="flex justify-center py-16"><Spinner /></div>
    <EmptyState
      v-else-if="!work"
      icon="image"
      :title="t('studio.workspace.missing')"
      :text="studio.error.value ? studioErrorText(studio.error.value, t, te) : ''"
    />

    <template v-else>
      <header class="flex flex-wrap items-center gap-2">
        <h2 class="min-w-0 truncate text-lg font-semibold">{{ work.title || t('studio.gallery.untitled') }}</h2>
        <span v-if="work.status === 'archived'" class="badge bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300">
          {{ t('studio.gallery.archived') }}
        </span>
        <span class="ml-auto flex flex-wrap items-center gap-1">
          <button
            v-if="showSettings"
            type="button"
            class="btn-ghost btn-sm"
            :aria-pressed="settingsOpen"
            @click="settingsOpen = !settingsOpen"
          ><AppIcon name="settings" :size="16" />{{ t('studio.workspace.settings') }}</button>
          <button
            type="button"
            class="btn-ghost btn-sm"
            :disabled="studio.isPending('archive')"
            @click="work.status === 'archived' ? studio.unarchive() : studio.archive()"
          >
            <AppIcon name="archive" :size="16" />
            {{ work.status === 'archived' ? t('studio.gallery.unarchive') : t('studio.gallery.archive') }}
          </button>
          <button type="button" class="btn-ghost btn-sm text-rose-600 dark:text-rose-400" :disabled="studio.isPending('remove')" @click="remove">
            <AppIcon name="trash" :size="16" />{{ t('common.delete') }}
          </button>
        </span>
      </header>

      <div class="grid gap-6" :class="showSettings && settingsOpen ? 'lg:grid-cols-[minmax(0,1fr)_340px]' : ''">
        <StudioResultGrid :studio="studio" @open="openFrame" />
        <aside v-if="showSettings && settingsOpen" class="card self-start p-4">
          <StudioSettingsPanel :studio="studio" />
        </aside>
      </div>

      <StudioFrameViewer :studio="studio" :frame-id="openFrameId" @open="openFrame" @close="openFrameId = null" />
    </template>
  </div>
</template>

<script setup>
import { studioErrorText } from '~/utils/studioView.js'

const props = defineProps({
  workId: { type: Number, required: true },
  initialFrameId: { type: Number, default: null },
  showSettings: { type: Boolean, default: true },
})
const emit = defineEmits(['removed'])
const { t, te } = useI18n()
const { confirm } = useConfirm()

const studio = useStudioWork(() => props.workId)
const work = computed(() => studio.work.value)
const settingsOpen = ref(true)
const openFrameId = ref(props.initialFrameId)

onMounted(() => studio.load())

function openFrame(id) {
  openFrameId.value = id || null
}

async function remove() {
  const ok = await confirm({
    message: t('studio.gallery.removeAsk', { title: work.value?.title || t('studio.gallery.untitled') }),
    confirmLabel: t('common.delete'),
    tone: 'danger',
  })
  if (ok && await studio.remove()) emit('removed', props.workId)
}

defineExpose({ studio, openFrame })
</script>
