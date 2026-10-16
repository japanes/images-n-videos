<template>
  <!--
    One video: the result with its versions on one side, the text, pictures and
    settings with the paid «Make video» button on the other; the extension panel
    under the result. The chat (module 15) puts it in its feed; the controller is
    exposed so the chat can drive the same video (extend, reshoot, take a frame).
  -->
  <div class="space-y-4">
    <div v-if="video.loading.value && !run" class="flex justify-center py-16"><Spinner /></div>
    <EmptyState
      v-else-if="!run"
      icon="video"
      :title="video.deleted.value ? t('video.workspace.deleted') : t('video.workspace.missing')"
      :text="video.error.value ? videoErrorText(video.error.value, t, te) : ''"
    />

    <template v-else>
      <header class="flex flex-wrap items-center gap-2">
        <input
          class="input min-w-0 flex-1 text-lg font-semibold"
          :value="run.title || ''"
          :maxlength="VIDEO_LIMITS.title"
          :placeholder="t('video.workspace.untitled')"
          :aria-label="t('video.workspace.titleLabel')"
          @input="video.edit({ title: $event.target.value })"
        >
        <span class="badge" :class="statusClass">{{ t(`video.statuses.${run.status}`) }}</span>
        <span v-if="run.spent_usd" class="muted text-xs" :title="t('video.workspace.spentHint')">
          {{ t('video.workspace.spent', { usd: formatUsd(run.spent_usd) }) }}
        </span>
        <button type="button" class="btn-ghost btn-sm text-rose-600 dark:text-rose-400" :disabled="video.isPending('remove') || run.busy" @click="remove">
          <AppIcon name="trash" :size="16" />{{ t('common.delete') }}
        </button>
      </header>

      <div class="grid gap-6 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div class="space-y-4">
          <VideoPlayer
            :video="video"
            @extend="openExtend"
            @reshoot="reshoot"
            @open-editor="$emit('open-editor', $event)"
            @frame-taken="$emit('frame-taken', $event)"
          />
          <section v-if="hasVideo" ref="extendBox" class="card p-4">
            <VideoExtendPanel :video="video" />
          </section>
        </div>

        <aside class="card space-y-5 self-start p-4">
          <VideoBriefWriter :video="video" :disabled="run.busy" />

          <div class="space-y-1 border-t border-slate-200 pt-4 dark:border-slate-700">
            <VideoAttachments
              :model-value="attachments"
              :model="model"
              :warnings="(run.take && run.take.warnings) || []"
              :disabled="run.busy"
              @update:model-value="video.edit($event, { now: true })"
            />
          </div>

          <div class="flex flex-wrap items-center gap-2 border-t border-slate-200 pt-4 dark:border-slate-700">
            <button type="button" class="btn-secondary btn-sm" :disabled="run.busy" @click="storyboardOpen = true">
              <AppIcon name="panel" :size="16" />{{ t('video.storyboard.open') }}
            </button>
            <span v-if="run.storyboard" class="muted text-xs">
              {{ run.storyboard.attached ? t('video.storyboard.attached') : t('video.storyboard.notAttached') }}
            </span>
          </div>

          <div class="border-t border-slate-200 pt-4 dark:border-slate-700">
            <VideoSettingsForm
              :model-value="settings"
              :models="catalog.models.value"
              :moves="catalog.moves.value"
              :categories="catalog.categories.value"
              :disabled="run.busy"
              @update:model-value="video.edit($event)"
            />
          </div>

          <div class="border-t border-slate-200 pt-4 dark:border-slate-700">
            <VideoTakeBar ref="takeBar" :video="video" hide-warnings />
          </div>
        </aside>
      </div>

      <VideoStoryboardModal :open="storyboardOpen" :video="video" @close="storyboardOpen = false" />
    </template>
  </div>
</template>

<script setup>
import { formatUsd } from '~/utils/format.js'
import { VIDEO_LIMITS, videoErrorText, videoModelById } from '~/utils/videoView.js'

const props = defineProps({
  runId: { type: Number, required: true },
})
const emit = defineEmits(['removed', 'open-editor', 'frame-taken'])
const { t, te } = useI18n()
const { confirm } = useConfirm()

const video = useVideoRun(() => props.runId)
const catalog = useVideoCatalog()
const run = computed(() => video.run.value)
const model = computed(() => videoModelById(catalog.models.value, run.value?.model_id))
const hasVideo = computed(() => (run.value?.versions || []).length > 0)
const storyboardOpen = ref(false)
const takeBar = ref(null)
const extendBox = ref(null)

const settings = computed(() => {
  const r = run.value || {}
  return {
    model_id: r.model_id, resolution: r.resolution, duration: r.duration, aspect: r.aspect,
    camera_move: r.camera_move || '', sound: r.sound,
  }
})
const attachments = computed(() => {
  const r = run.value || {}
  return {
    first_frame_id: r.first_frame?.id ?? null,
    last_frame_id: r.last_frame?.id ?? null,
    references: (r.references || []).map((f) => f.id),
  }
})
const statusClass = computed(() => ({
  running: 'bg-sky-100 text-sky-800 dark:bg-sky-500/15 dark:text-sky-200',
  paused: 'bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-200',
  done: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-200',
  error: 'bg-rose-100 text-rose-800 dark:bg-rose-500/15 dark:text-rose-200',
}[run.value?.status] || 'bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300'))

onMounted(() => video.load())

function openExtend() {
  extendBox.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function reshoot() {
  return takeBar.value?.shoot()
}

async function remove() {
  const ok = await confirm({
    message: t('video.workspace.removeAsk', { title: run.value?.title || t('video.workspace.untitled') }),
    confirmLabel: t('common.delete'),
    tone: 'danger',
  })
  if (ok && await video.remove()) emit('removed', props.runId)
}

defineExpose({ video, catalog, reshoot, openExtend })
</script>
