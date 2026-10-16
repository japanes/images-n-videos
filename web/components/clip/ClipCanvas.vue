<template>
  <div ref="area" class="relative flex min-h-0 flex-1 items-center justify-center overflow-hidden bg-slate-900" @pointerdown.self="selectedId = null">
    <div
      v-if="project"
      ref="frameEl"
      class="relative overflow-hidden bg-black shadow-lg"
      :style="{ width: `${box.width}px`, height: `${box.height}px` }"
      @pointerdown.self="selectedId = null"
    >
      <img
        v-if="cropMode === 'blur' && poster"
        :src="poster"
        alt=""
        class="pointer-events-none absolute inset-0 h-full w-full scale-110 object-cover opacity-70 blur-xl"
      >
      <video
        :ref="setVideo"
        :src="project.source_file?.url"
        :poster="poster || undefined"
        class="absolute inset-0 h-full w-full"
        :style="{ objectFit: fit }"
        preload="auto"
        playsinline
        :muted="!state.audio.keep_original"
        @play="onPlayState"
        @pause="onPlayState"
        @ended="onPlayState"
        @seeked="onSeeked"
        @loadedmetadata="onSeeked"
        @pointerdown="selectedId = null"
      />

      <template v-for="layer in shownLayers" :key="layer.id">
        <div
          v-if="layer.type === 'text'"
          class="absolute cursor-move select-none whitespace-pre text-center"
          :class="layer.id === selectedId ? 'outline outline-2 outline-offset-2 outline-sky-400' : 'hover:outline hover:outline-1 hover:outline-sky-300/70'"
          :style="{ ...textStyle(layer), transform: 'translate(-50%, -50%)' }"
          @pointerdown="startDrag($event, layer, 'move')"
        >{{ layer.text || ' ' }}</div>
        <div
          v-else
          class="absolute cursor-move select-none"
          :class="layer.id === selectedId ? 'outline outline-2 outline-offset-2 outline-sky-400' : 'hover:outline hover:outline-1 hover:outline-sky-300/70'"
          :style="{ ...clipImageStyle(layer), transform: 'translate(-50%, -50%)' }"
          @pointerdown="startDrag($event, layer, 'move')"
        >
          <img :src="`/files/${layer.file_id}`" alt="" class="pointer-events-none block w-full" draggable="false">
          <span
            v-if="layer.id === selectedId"
            class="absolute -bottom-2 -right-2 h-4 w-4 cursor-nwse-resize rounded-full border-2 border-white bg-sky-500"
            :title="t('clip.canvas.resize')"
            @pointerdown="startDrag($event, layer, 'resize')"
          />
        </div>
      </template>

      <div
        v-if="caption"
        class="pointer-events-none absolute text-center"
        :style="captionBoxStyle"
      >
        <span :style="captionInnerStyle">
          <template v-for="(word, i) in caption.words" :key="i">
            <span :style="i === caption.lit && litColor ? { color: litColor } : null">{{ word.text }}</span>{{ i < caption.words.length - 1 ? ' ' : '' }}
          </template>
        </span>
      </div>

      <div v-if="removedNow" class="pointer-events-none absolute inset-x-0 top-0 bg-rose-600/80 px-2 py-1 text-center text-xs text-white">
        {{ t('clip.canvas.removedHere') }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { useElementSize } from '@vueuse/core'
import {
  clipCaptionAt, clipCaptionStyle, clipClamp, clipEffectivePreset, clipFrameSize, clipImageStyle, clipLayerActive,
  clipRemovedAt, clipResolveBrand, clipTextStyle,
} from '~/utils/clipState.js'

const { t } = useI18n()
const ed = useClipContext()
const { project, state, selectedId, time, presets, presetsByCode, onPlayState } = ed

const area = ref(null)
const frameEl = ref(null)
const { width: areaW, height: areaH } = useElementSize(area)

const frame = computed(() => clipFrameSize(state.value, project.value?.source))
const box = computed(() => {
  const pad = 24
  const w = Math.max(40, areaW.value - pad)
  const h = Math.max(40, areaH.value - pad)
  const scale = Math.min(w / frame.value.width, h / frame.value.height)
  return { width: Math.round(frame.value.width * scale), height: Math.round(frame.value.height * scale) }
})
const poster = computed(() => project.value?.source_file?.thumb_url || null)
const cropMode = computed(() => (state.value.crop.aspect ? state.value.crop.mode : ''))
const fit = computed(() => (cropMode.value === 'cover' ? 'cover' : 'contain'))
const shownLayers = computed(() => state.value.layers.filter((l) => clipLayerActive(l, time.value)))
const removedNow = computed(() => clipRemovedAt(state.value.removed, time.value) >= 0)

function setVideo(el) {
  ed.attachVideo(el || null)
}

function onSeeked(e) {
  const el = e.target
  if (el.paused) time.value = el.currentTime
  applyVolume()
}

function applyVolume() {
  const el = ed.video.value
  if (el) el.volume = clipClamp(Number(state.value.audio.original_volume) || 0, 0, 1)
}
watch(() => state.value.audio.original_volume, applyVolume)

function textStyle(layer) {
  if (layer.font_file_id) clipEnsureFont(layer.font, layer.font_file_id)
  return clipTextStyle(layer, box.value.height)
}

// captions
const preset = computed(() => {
  const sub = state.value.subtitles
  const base = presetsByCode.value[sub.preset_code] || presets.value[0]
  return clipEffectivePreset(clipResolveBrand(base, project.value?.brand), sub)
})
watch(preset, (p) => { if (p?.font_file_id) clipEnsureFont(p.font_family, p.font_file_id) }, { immediate: true })
const caption = computed(() => {
  const sub = state.value.subtitles
  if (!sub.enabled || !sub.words.length || !preset.value) return null
  return clipCaptionAt(sub.words, time.value, {
    mode: preset.value.mode, maxWords: preset.value.max_words_per_line,
  })
})
const captionStyle = computed(() => clipCaptionStyle(preset.value, box.value.width, box.value.height))
const captionBoxStyle = computed(() => {
  const { boxColor: _box, ...rest } = captionStyle.value
  return rest
})
const captionInnerStyle = computed(() => {
  const box = captionStyle.value.boxColor
  if (!box) return null
  return { background: box, padding: '0 0.25em', boxDecorationBreak: 'clone', WebkitBoxDecorationBreak: 'clone' }
})
const litColor = computed(() => {
  const p = preset.value
  if (!p || p.mode === 'word') return null
  const hi = String(p.highlight_color || '').toUpperCase()
  return hi && hi !== String(p.primary_color || '').toUpperCase() ? p.highlight_color : null
})

// dragging layers
let drag = null
const round3 = (v) => Math.round(v * 1000) / 1000

function startDrag(e, layer, mode) {
  if (e.button !== 0) return
  e.preventDefault()
  e.stopPropagation()
  selectedId.value = layer.id
  const rect = frameEl.value?.getBoundingClientRect()
  if (!rect) return
  drag = { id: layer.id, mode, rect, x0: e.clientX, y0: e.clientY, x: layer.x, y: layer.y, width: layer.width }
  window.addEventListener('pointermove', onMove)
  window.addEventListener('pointerup', endDrag, { once: true })
}

function onMove(e) {
  if (!drag) return
  const layer = state.value.layers.find((l) => l.id === drag.id)
  if (!layer) return
  const dx = (e.clientX - drag.x0) / drag.rect.width
  const dy = (e.clientY - drag.y0) / drag.rect.height
  if (drag.mode === 'move') {
    layer.x = round3(clipClamp(drag.x + dx, 0, 1))
    layer.y = round3(clipClamp(drag.y + dy, 0, 1))
  } else {
    layer.width = round3(clipClamp(drag.width + dx * 2, 0.02, 1))
  }
}

function endDrag() {
  drag = null
  window.removeEventListener('pointermove', onMove)
}

onBeforeUnmount(endDrag)
</script>
