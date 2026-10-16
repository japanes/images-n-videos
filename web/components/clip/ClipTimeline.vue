<template>
  <div class="space-y-2 border-t border-slate-200 bg-white px-3 py-2 dark:border-slate-700 dark:bg-slate-800">
    <div class="flex flex-wrap items-center gap-1.5">
      <button type="button" class="btn-secondary btn-sm" :title="t('clip.timeline.playHint')" @click="togglePlay">
        <AppIcon :name="playing ? 'pause' : 'play'" :size="14" />{{ playing ? t('clip.timeline.pause') : t('clip.timeline.play') }}
      </button>
      <span class="px-1 text-sm tabular-nums">{{ clipFormatTime(time) }} / {{ clipFormatTime(duration) }}</span>
      <span class="text-xs muted tabular-nums">{{ t('clip.timeline.result', { time: clipFormatTime(outputDuration) }) }}</span>
      <ToggleSwitch v-model="asResult" class="ml-2" :label="t('clip.timeline.asResult')" />
      <span class="flex-1" />
      <button type="button" class="btn-ghost btn-sm" :title="t('clip.timeline.startHereHint')" @click="setStart">
        {{ t('clip.timeline.startHere') }}
      </button>
      <button type="button" class="btn-ghost btn-sm" :title="t('clip.timeline.endHereHint')" @click="setEnd">
        {{ t('clip.timeline.endHere') }}
      </button>
      <button type="button" class="btn-ghost btn-sm" :title="t('clip.timeline.markInHint')" @click="markIn = time">
        {{ t('clip.timeline.markIn') }}
      </button>
      <button type="button" class="btn-ghost btn-sm" :title="t('clip.timeline.markOutHint')" @click="markOut = time">
        {{ t('clip.timeline.markOut') }}
      </button>
      <button type="button" class="btn-secondary btn-sm" :disabled="!canRemove" :title="t('clip.timeline.removeHint')" @click="removePiece">
        <AppIcon name="scissors" :size="14" />{{ t('clip.timeline.remove') }}
      </button>
      <button v-if="removedIndex >= 0" type="button" class="btn-secondary btn-sm" @click="restore(removedIndex)">
        <AppIcon name="refresh" :size="14" />{{ t('clip.timeline.restore') }}
      </button>
      <button type="button" class="btn-ghost btn-sm" :title="t('clip.timeline.splitHint')" @click="toggleSplit">
        {{ hasSplitHere ? t('clip.timeline.unsplit') : t('clip.timeline.split') }}
      </button>
    </div>

    <div
      ref="bar"
      class="relative h-12 cursor-pointer touch-none select-none overflow-hidden rounded-button bg-slate-200 dark:bg-slate-700"
      @pointerdown="startScrub"
    >
      <div class="absolute inset-y-0 left-0 bg-slate-900/50" :style="{ width: pct(trimStart) }" />
      <div class="absolute inset-y-0 right-0 bg-slate-900/50" :style="{ width: pct(duration - trimEnd) }" />
      <div
        v-for="(r, i) in state.removed"
        :key="`r${i}`"
        class="clip-removed absolute inset-y-0 border-x border-rose-500"
        :style="{ left: pct(r[0]), width: pct(r[1] - r[0]) }"
        :title="t('clip.timeline.removedHint', { from: clipFormatTime(r[0]), to: clipFormatTime(r[1]) })"
      />
      <div
        v-if="markRange"
        class="absolute inset-y-0 border-x-2 border-sky-500 bg-sky-400/30"
        :style="{ left: pct(markRange[0]), width: pct(markRange[1] - markRange[0]) }"
      />
      <div
        v-else-if="markIn !== null || markOut !== null"
        class="absolute inset-y-0 w-0.5 bg-sky-500"
        :style="{ left: pct(markIn ?? markOut) }"
      />
      <div
        v-for="c in state.cuts"
        :key="`c${c}`"
        class="absolute inset-y-0 w-0.5 bg-amber-400"
        :style="{ left: pct(c) }"
        :title="t('clip.timeline.splitAt', { time: clipFormatTime(c) })"
      />
      <div
        class="absolute inset-y-0 w-2 -translate-x-1/2 cursor-ew-resize rounded bg-emerald-500"
        :style="{ left: pct(trimStart) }"
        :title="t('clip.timeline.trimStart')"
        @pointerdown.stop="startTrim($event, 'start')"
      />
      <div
        class="absolute inset-y-0 w-2 -translate-x-1/2 cursor-ew-resize rounded bg-emerald-500"
        :style="{ left: pct(trimEnd) }"
        :title="t('clip.timeline.trimEnd')"
        @pointerdown.stop="startTrim($event, 'end')"
      />
      <div class="pointer-events-none absolute inset-y-0 w-0.5 bg-white shadow" :style="{ left: pct(time) }" />
    </div>

    <div v-if="rows.length" class="max-h-28 space-y-1 overflow-y-auto pr-1">
      <div v-for="row in rows" :key="row.key" class="relative h-5 rounded bg-slate-100 dark:bg-slate-900/60">
        <button
          v-for="(item, i) in row.items"
          :key="i"
          type="button"
          class="absolute inset-y-0 truncate rounded px-1 text-left text-[11px] leading-5"
          :class="item.selected ? 'bg-sky-500 text-white' : row.cls"
          :style="{ left: pct(item.start), width: pct(Math.max(item.end - item.start, duration / 400)) }"
          :title="item.label"
          @click="item.onClick()"
        >{{ item.label }}</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import {
  CLIP_MAX_REMOVED, CLIP_MIN_CLIP, clipAddRemoved, clipClamp, clipFormatTime, clipGroupLines, clipRemovedAt,
  clipToggleCut, clipTrimEnd,
} from '~/utils/clipState.js'

const { t } = useI18n()
const ed = useClipContext()
const { state, time, playing, duration, outputDuration, asResult, selectedId, presetsByCode, togglePlay, seek } = ed

const bar = ref(null)
const markIn = ref(null)
const markOut = ref(null)

const trimStart = computed(() => Number(state.value.trim.start) || 0)
const trimEnd = computed(() => clipTrimEnd(state.value, duration.value))
const pct = (v) => `${duration.value ? clipClamp((v / duration.value) * 100, 0, 100) : 0}%`
const round3 = (v) => Math.round(v * 1000) / 1000

const markRange = computed(() => {
  if (markIn.value === null || markOut.value === null) return null
  const a = Math.min(markIn.value, markOut.value)
  const b = Math.max(markIn.value, markOut.value)
  return b - a >= 0.05 ? [a, b] : null
})
const canRemove = computed(() => !!markRange.value && state.value.removed.length < CLIP_MAX_REMOVED)
const removedIndex = computed(() => clipRemovedAt(state.value.removed, time.value))
const hasSplitHere = computed(() => state.value.cuts.some((c) => Math.abs(c - time.value) <= 0.15))

function timeAt(clientX) {
  const rect = bar.value?.getBoundingClientRect()
  if (!rect || !rect.width) return 0
  return round3(clipClamp((clientX - rect.left) / rect.width, 0, 1) * duration.value)
}

function setStart() {
  const end = trimEnd.value
  state.value.trim.start = round3(clipClamp(time.value, 0, Math.max(0, end - CLIP_MIN_CLIP)))
}

function setEnd() {
  const v = round3(Math.max(time.value, trimStart.value + CLIP_MIN_CLIP))
  state.value.trim.end = v >= duration.value - 0.05 ? null : v
}

function removePiece() {
  if (!markRange.value) return
  state.value.removed = clipAddRemoved(state.value.removed, markRange.value[0], markRange.value[1])
  markIn.value = null
  markOut.value = null
}

function restore(index) {
  state.value.removed = state.value.removed.filter((_, i) => i !== index)
}

function toggleSplit() {
  state.value.cuts = clipToggleCut(state.value.cuts, time.value)
}

// pointer: scrub on the bar, drag the trim handles
let mode = null

function onMove(e) {
  const v = timeAt(e.clientX)
  if (mode === 'scrub') seek(v)
  else if (mode === 'start') {
    state.value.trim.start = round3(clipClamp(v, 0, Math.max(0, trimEnd.value - CLIP_MIN_CLIP)))
    seek(state.value.trim.start)
  } else if (mode === 'end') {
    const end = round3(Math.max(v, trimStart.value + CLIP_MIN_CLIP))
    state.value.trim.end = end >= duration.value - 0.05 ? null : end
    seek(Math.min(end, duration.value))
  }
}

function stop() {
  mode = null
  window.removeEventListener('pointermove', onMove)
}

function begin(e, m) {
  if (e.button !== 0) return
  e.preventDefault()
  mode = m
  window.addEventListener('pointermove', onMove)
  window.addEventListener('pointerup', stop, { once: true })
  onMove(e)
}

const startScrub = (e) => begin(e, 'scrub')
const startTrim = (e, which) => begin(e, which)
onBeforeUnmount(stop)

// rows under the bar: captions and layers
const rows = computed(() => {
  const out = []
  const sub = state.value.subtitles
  if (sub.words.length) {
    const preset = presetsByCode.value[sub.preset_code]
    const lines = clipGroupLines(sub.words, preset?.max_words_per_line || 4)
    out.push({
      key: 'subs',
      cls: sub.enabled ? 'bg-amber-200 text-amber-900 dark:bg-amber-500/30 dark:text-amber-100' : 'bg-slate-300 text-slate-600 dark:bg-slate-700 dark:text-slate-300',
      items: lines.map((line) => ({
        start: line[0].start,
        end: line[line.length - 1].end,
        label: line.map((w) => w.text).join(' '),
        selected: false,
        onClick: () => { ed.sideTab.value = 'subtitles'; seek(line[0].start) },
      })),
    })
  }
  for (const layer of state.value.layers) {
    const end = layer.end ?? trimEnd.value
    out.push({
      key: layer.id,
      cls: layer.visible === false
        ? 'bg-slate-300 text-slate-500 dark:bg-slate-700 dark:text-slate-400'
        : layer.type === 'text' ? 'bg-violet-200 text-violet-900 dark:bg-violet-500/30 dark:text-violet-100' : 'bg-teal-200 text-teal-900 dark:bg-teal-500/30 dark:text-teal-100',
      items: [{
        start: layer.start || 0,
        end,
        label: layer.type === 'text' ? (layer.text || t('clip.layers.emptyText')) : t('clip.layers.picture'),
        selected: layer.id === selectedId.value,
        onClick: () => {
          selectedId.value = layer.id
          ed.sideTab.value = 'layers'
          if (time.value < (layer.start || 0) || time.value > end) seek(layer.start || 0)
        },
      }],
    })
  }
  return out
})
</script>

<style scoped>
.clip-removed {
  background: repeating-linear-gradient(135deg, rgb(244 63 94 / 0.55) 0 6px, rgb(244 63 94 / 0.25) 6px 12px);
}
</style>
