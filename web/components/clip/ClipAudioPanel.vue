<template>
  <div class="space-y-4">
    <!-- the video's own sound -->
    <section class="space-y-2 rounded-button border border-slate-200 p-3 dark:border-slate-700">
      <h3 class="text-sm font-semibold">{{ t('clip.audio.original') }}</h3>
      <p v-if="noSound" class="text-xs muted">{{ t('clip.audio.noSound') }}</p>
      <template v-else>
        <ToggleSwitch v-model="audio.keep_original" :label="t('clip.audio.keepOriginal')" />
        <label v-if="audio.keep_original" class="block">
          <span class="label">{{ t('clip.audio.volume', { pct: pct(audio.original_volume) }) }}</span>
          <input v-model.number="audio.original_volume" type="range" min="0" max="2" step="0.05" class="w-full">
        </label>
        <p v-if="audio.keep_original && audio.original_volume > 1" class="text-xs muted">{{ t('clip.audio.louderHint') }}</p>
      </template>
    </section>

    <!-- added tracks -->
    <section class="space-y-3">
      <div class="flex items-center gap-2">
        <h3 class="flex-1 text-sm font-semibold">{{ t('clip.audio.tracks') }}</h3>
        <button type="button" class="btn-secondary btn-sm" :disabled="!canAdd" @click="pickerOpen = true">
          <AppIcon name="plus" :size="14" />{{ t('clip.audio.add') }}
        </button>
      </div>
      <p class="text-xs muted">{{ t('clip.audio.tracksHint') }}</p>
      <p v-if="!canAdd" class="text-xs text-amber-800 dark:text-amber-200">{{ t('clip.audio.limit', { n: CLIP_MAX_TRACKS }) }}</p>
      <p v-if="!audio.tracks.length" class="text-sm muted">{{ t('clip.audio.empty') }}</p>

      <div
        v-for="track in audio.tracks"
        :key="track.id"
        class="space-y-2 rounded-button border border-slate-200 p-3 dark:border-slate-700"
      >
        <div class="flex items-center gap-2">
          <p class="min-w-0 flex-1 truncate text-sm font-medium" :title="trackName(track)">{{ trackName(track) }}</p>
          <button type="button" class="btn-ghost btn-sm text-rose-600" :title="t('clip.audio.remove')" @click="removeTrack(track)">
            <AppIcon name="trash" :size="14" />
          </button>
        </div>
        <p v-if="names[track.file_id] === null" class="text-xs text-rose-700 dark:text-rose-300">{{ t('clip.audio.missing') }}</p>
        <audio v-else :src="`/files/${track.file_id}`" controls preload="none" class="h-8 w-full" />

        <div class="grid grid-cols-2 gap-2">
          <label class="block">
            <span class="label">{{ t('clip.audio.role') }}</span>
            <select v-model="track.role" class="input">
              <option v-for="role in CLIP_TRACK_ROLES" :key="role" :value="role" :disabled="role === 'voice' && voiceTaken(track)">
                {{ t(`clip.audio.roles.${role}`) }}
              </option>
            </select>
          </label>
          <label class="block">
            <span class="label">{{ t('clip.audio.trackVolume', { pct: pct(track.volume) }) }}</span>
            <input v-model.number="track.volume" type="range" min="0" max="2" step="0.05" class="mt-2 w-full">
          </label>
          <label class="block">
            <span class="label">{{ t('clip.audio.delay') }}</span>
            <input v-model.number="track.delay" type="number" min="0" step="0.1" class="input" @change="fix(track, 'delay', 24 * 3600)">
          </label>
          <div />
          <label class="block">
            <span class="label">{{ t('clip.audio.fadeIn') }}</span>
            <input v-model.number="track.fade_in" type="number" min="0" max="30" step="0.1" class="input" @change="fix(track, 'fade_in', 30)">
          </label>
          <label class="block">
            <span class="label">{{ t('clip.audio.fadeOut') }}</span>
            <input v-model.number="track.fade_out" type="number" min="0" max="30" step="0.1" class="input" @change="fix(track, 'fade_out', 30)">
          </label>
        </div>
        <p class="text-xs muted">{{ t(`clip.audio.roleHint.${track.role}`) }}</p>
        <template v-if="track.role !== 'voice'">
          <ToggleSwitch v-model="track.duck" :disabled="!hasVoice" :label="t('clip.audio.duck')" />
          <p class="text-xs muted">{{ hasVoice ? t('clip.audio.duckHint') : t('clip.audio.duckNeedsVoice') }}</p>
        </template>
      </div>
    </section>

    <p class="rounded-button bg-sky-50 px-3 py-2 text-xs text-sky-900 dark:bg-sky-500/10 dark:text-sky-100">
      {{ t('clip.audio.previewHint') }}
    </p>

    <ClipMediaPicker
      :open="pickerOpen"
      kind="audio"
      :title="t('clip.audio.pick')"
      @pick="addTrack"
      @close="pickerOpen = false"
    />
  </div>
</template>

<script setup>
import { CLIP_MAX_TRACKS, CLIP_TRACK_ROLES, clipNewTrack } from '~/utils/clipState.js'

const { t } = useI18n()
const api = useApi()
const { confirm } = useConfirm()
const ed = useClipContext()
const { state, project } = ed

const audio = computed(() => state.value.audio)
const pickerOpen = ref(false)
// file id -> display name; null when the file is gone from the library
const names = ref({})

const noSound = computed(() => project.value?.source?.has_audio === false)
const canAdd = computed(() => audio.value.tracks.length < CLIP_MAX_TRACKS)
const hasVoice = computed(() => audio.value.tracks.some((x) => x.role === 'voice'))
const pct = (v) => Math.round((Number(v) || 0) * 100)
const voiceTaken = (track) => audio.value.tracks.some((x) => x.role === 'voice' && x.id !== track.id)

function trackName(track) {
  const name = names.value[track.file_id]
  return name || `#${track.file_id}`
}

async function loadName(fileId) {
  if (fileId in names.value) return
  names.value = { ...names.value, [fileId]: '' }
  try {
    const item = await api.get(`/api/media/files/${fileId}`)
    names.value = { ...names.value, [fileId]: mediaDisplayName(item) }
  } catch (err) {
    names.value = { ...names.value, [fileId]: err?.status === 404 ? null : '' }
  }
}

watch(() => audio.value.tracks.map((x) => x.file_id), (ids) => ids.forEach(loadName), { immediate: true })

function fix(track, key, max) {
  const v = Number(track[key])
  track[key] = Number.isFinite(v) ? Math.min(max, Math.max(0, Math.round(v * 100) / 100)) : 0
}

function addTrack(item) {
  pickerOpen.value = false
  if (!item?.id || !canAdd.value) return
  if (item.title || item.original_name) names.value = { ...names.value, [item.id]: mediaDisplayName(item) }
  audio.value.tracks.push(clipNewTrack(item.id))
}

async function removeTrack(track) {
  const ok = await confirm({ message: t('clip.audio.removeAsk', { name: trackName(track) }), tone: 'danger',
    confirmLabel: t('clip.audio.remove') })
  if (!ok) return
  audio.value.tracks = audio.value.tracks.filter((x) => x.id !== track.id)
  if (!audio.value.tracks.some((x) => x.role === 'voice')) audio.value.tracks.forEach((x) => { x.duck = false })
}
</script>
