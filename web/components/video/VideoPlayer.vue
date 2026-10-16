<template>
  <!--
    The result: the video of the chosen version, the list of versions, and what
    can be done with it (take a frame, download, extend, reshoot, open in the
    editor). While a clip is being made it shows that, and Stop; when the last
    clip failed it shows why, with Google's own words.
  -->
  <div class="space-y-3 text-sm">
    <div
      v-if="clip"
      class="flex flex-wrap items-center gap-2 rounded-card border border-slate-200 px-3 py-2 dark:border-slate-600"
    >
      <Spinner :size="16" />
      <span class="min-w-0 flex-1">{{ t(`video.player.making.${clip.kind}`, { n: clip.seconds || '' }) }}</span>
      <button type="button" class="btn-ghost btn-sm" :disabled="video.isPending('stop')" @click="video.stop()">
        <AppIcon name="stop" :size="16" />{{ t('video.player.stop') }}
      </button>
    </div>
    <div
      v-else-if="failed"
      class="rounded-card bg-rose-50 px-3 py-2 text-rose-900 dark:bg-rose-500/10 dark:text-rose-100"
    >
      <p class="font-medium">{{ t('video.player.failed') }}</p>
      <p>{{ failedText.text }}</p>
      <p v-if="failedText.detail" class="mt-1 break-words text-xs opacity-80">{{ t('video.player.googleSaid', { text: failedText.detail }) }}</p>
    </div>

    <template v-if="version && version.file">
      <video
        ref="player"
        :key="version.file.id"
        class="w-full rounded-card bg-black"
        :style="{ aspectRatio: videoAspectRatio(run.aspect) }"
        :src="videoFileUrl(version.file)"
        :poster="version.file.thumb_url || undefined"
        controls
        playsinline
        preload="metadata"
      />
      <p class="muted text-xs">
        {{ t('video.player.about', { n: version.number, seconds: videoSeconds(version.duration), kind: t(`video.player.kinds.${version.kind}`) }) }}
      </p>

      <div class="flex flex-wrap items-center gap-2">
        <button type="button" class="btn-secondary btn-sm" :disabled="busyFrame" @click="frame('first')">
          <AppIcon name="image" :size="16" />{{ t('video.player.frameFirst') }}
        </button>
        <button type="button" class="btn-secondary btn-sm" :disabled="busyFrame" @click="frame('now')">
          <AppIcon name="image" :size="16" />{{ t('video.player.frameNow') }}
        </button>
        <button type="button" class="btn-secondary btn-sm" :disabled="busyFrame" @click="frame('last')">
          <AppIcon name="image" :size="16" />{{ t('video.player.frameLast') }}
        </button>
        <a class="btn-secondary btn-sm" :href="videoDownloadUrl(version.file)" download>
          <AppIcon name="download" :size="16" />{{ t('common.download') }}
        </a>
      </div>
      <p class="muted text-xs">{{ t('video.player.frameHelp') }}</p>

      <div class="flex flex-wrap items-center gap-2">
        <button type="button" class="btn-primary btn-sm" :disabled="Boolean(clip)" @click="$emit('extend')">
          <AppIcon name="plus" :size="16" />{{ t('video.player.extend') }}
        </button>
        <PriceButton
          variant="secondary"
          icon="refresh"
          :label="t('video.player.reshoot')"
          :usd="reshootUsd"
          :disabled="Boolean(clip) || reshootUsd === null"
          @click="$emit('reshoot')"
        />
        <button type="button" class="btn-ghost btn-sm" @click="$emit('open-editor', { runId: run.id, fileId: version.file.id })">
          <AppIcon name="scissors" :size="16" />{{ t('video.player.openEditor') }}
        </button>
      </div>
    </template>
    <EmptyState v-else-if="!clip && !failed" icon="video" :title="t('video.player.empty')" :text="t('video.player.emptyHint')" />

    <div v-if="versions.length > 1" class="space-y-1">
      <span class="label">{{ t('video.player.versions') }}</span>
      <div class="flex flex-wrap gap-2">
        <button
          v-for="v in versions"
          :key="v.number"
          type="button"
          class="rounded-button border px-2 py-1 text-xs"
          :class="v.number === version?.number ? 'border-primary text-primary' : 'border-slate-200 hover:border-primary dark:border-slate-600'"
          :aria-pressed="v.number === version?.number"
          :disabled="video.isPending('version') || Boolean(clip)"
          @click="video.chooseVersion(v.number)"
        >
          {{ t('video.player.version', { n: v.number, seconds: videoSeconds(v.duration) }) }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import {
  videoAspectRatio, videoClipError, videoCurrentVersion, videoDownloadUrl, videoFailedClip, videoFileUrl,
  videoRunningClip, videoSeconds,
} from '~/utils/videoView.js'

const props = defineProps({
  // The controller from useVideoRun().
  video: { type: Object, required: true },
})
const emit = defineEmits(['extend', 'reshoot', 'open-editor', 'frame-taken'])
const { t, te } = useI18n()
const toast = useToast()
const player = ref(null)

const run = computed(() => props.video.run.value || {})
const versions = computed(() => run.value.versions || [])
const version = computed(() => videoCurrentVersion(run.value))
const clip = computed(() => videoRunningClip(run.value))
const failed = computed(() => videoFailedClip(run.value))
const failedText = computed(() => videoClipError(failed.value, t, te))
const busyFrame = computed(() => props.video.isPending('frame'))
// A reshoot is a new take with the settings as they are: its price is the take's.
const reshootUsd = computed(() => {
  const take = run.value.take
  return take && take.ready && take.estimate_usd !== null && take.estimate_usd !== undefined ? take.estimate_usd : null
})

/** Save a still of the shown version to the media library (free). */
async function frame(where) {
  let at = where
  if (where === 'now') at = Math.max(0, Math.round((player.value?.currentTime || 0) * 100) / 100)
  const file = await props.video.takeFrame(at, version.value?.number || null)
  if (!file) return
  toast.success(t('video.player.frameSaved'))
  emit('frame-taken', file)
}
</script>
