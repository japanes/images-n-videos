<template>
  <!--
    The canvas of the text tool. The picture is the server's drawing — the same
    one «Save» makes — and the layers' boxes lie over it: click to pick, drag to
    move, the eight handles to change the size. The drawing catches up after the
    change is kept (a short pause).
  -->
  <div class="flex min-h-0 flex-1 flex-col">
    <div ref="stage" class="relative flex min-h-[240px] flex-1 items-center justify-center overflow-hidden bg-slate-100 p-3 dark:bg-slate-900">
      <div
        v-if="fit"
        ref="sheet"
        class="relative select-none shadow-card"
        :style="{ width: `${fit.width}px`, height: `${fit.height}px` }"
        @pointerdown.self="tool.state.selectedId = ''"
      >
        <img
          v-if="picture"
          :src="picture"
          alt=""
          draggable="false"
          class="pointer-events-none absolute inset-0 h-full w-full object-fill"
        >
        <div
          v-for="layer in shown"
          :key="layer.id"
          class="absolute cursor-move touch-none outline-none"
          :class="boxClass(layer)"
          :style="textBoxStyle(boxOf(layer))"
          tabindex="0"
          :aria-label="textLayerLabel(layer, t)"
          @pointerdown.stop="startMove($event, layer)"
          @keydown="nudge($event, layer)"
        >
          <template v-if="layer.id === tool.state.selectedId">
            <span
              v-for="h in TEXT_HANDLES"
              :key="h"
              class="absolute h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-sm border border-white bg-primary shadow"
              :class="handleCursor[h]"
              :style="handleStyle[h]"
              @pointerdown.stop="startResize($event, layer, h)"
            />
          </template>
        </div>
        <div v-if="tool.state.preview.loading" class="pointer-events-none absolute right-2 top-2 rounded-full bg-black/50 p-1.5 text-white">
          <Spinner :size="14" />
        </div>
      </div>
      <Spinner v-else :size="24" />
    </div>

    <div v-if="notes.length || tool.state.preview.error" class="space-y-1 border-t border-slate-200 px-4 py-2 text-xs dark:border-slate-700">
      <p v-if="tool.state.preview.error" class="text-rose-700 dark:text-rose-300">{{ tool.state.preview.error }}</p>
      <p v-for="note in notes" :key="note.key" class="flex items-start gap-1.5 text-amber-800 dark:text-amber-200">
        <AppIcon name="alert" :size="14" class="mt-px shrink-0" />
        <span>{{ note.plural !== undefined ? t(note.key, note.params, note.plural) : t(note.key, note.params) }}</span>
      </p>
    </div>
  </div>
</template>

<script setup>
import { useResizeObserver } from '@vueuse/core'
import {
  TEXT_HANDLES, textBoxStyle, textLayerLabel, textMoveBox, textPatchLayer, textReportNotes, textResizeBox,
} from '~/utils/textView.js'

const tool = inject('textTool')
const { t } = useI18n()

const stage = ref(null)
const sheet = ref(null)
const area = ref({ width: 0, height: 0 })
useResizeObserver(stage, (entries) => {
  const box = entries[0]?.contentRect
  if (box) area.value = { width: box.width, height: box.height }
})

const size = computed(() => {
  const bg = tool.state.design?.background
  return bg?.width && bg?.height ? { width: bg.width, height: bg.height } : null
})

/** The picture's place on the stage: as large as fits, the sides kept. */
const fit = computed(() => {
  if (!size.value || !area.value.width || !area.value.height) return null
  const scale = Math.min(area.value.width / size.value.width, area.value.height / size.value.height)
  return { width: Math.max(1, Math.floor(size.value.width * scale)), height: Math.max(1, Math.floor(size.value.height * scale)) }
})

const picture = computed(() => tool.state.preview.url || tool.state.design?.background?.url || '')
const shown = computed(() => tool.state.layers.filter((l) => l.visible !== false))
const notes = computed(() => textReportNotes(tool.state.preview.report))

function boxClass(layer) {
  if (layer.id === tool.state.selectedId) return 'ring-2 ring-primary'
  return 'ring-1 ring-white/0 hover:ring-white/80 hover:shadow-[0_0_0_1px_rgba(0,0,0,0.4)] focus-visible:ring-white/80'
}

const handleStyle = {
  nw: { left: '0%', top: '0%' }, n: { left: '50%', top: '0%' }, ne: { left: '100%', top: '0%' },
  e: { left: '100%', top: '50%' }, se: { left: '100%', top: '100%' }, s: { left: '50%', top: '100%' },
  sw: { left: '0%', top: '100%' }, w: { left: '0%', top: '50%' },
}
const handleCursor = {
  nw: 'cursor-nwse-resize', se: 'cursor-nwse-resize', ne: 'cursor-nesw-resize', sw: 'cursor-nesw-resize',
  n: 'cursor-ns-resize', s: 'cursor-ns-resize', e: 'cursor-ew-resize', w: 'cursor-ew-resize',
}

// ── dragging: the box follows the pointer, the change is kept on release ──

const drag = ref(null) // { id, mode, handle, startX, startY, start, box }

function boxOf(layer) {
  return drag.value?.id === layer.id ? drag.value.box : layer
}

function begin(event, layer, mode, handle = '') {
  if (event.button !== undefined && event.button !== 0) return
  tool.state.selectedId = layer.id
  const start = { x: layer.x, y: layer.y, w: layer.w, h: layer.h }
  drag.value = { id: layer.id, mode, handle, startX: event.clientX, startY: event.clientY, start, box: start, moved: false }
  event.currentTarget.setPointerCapture?.(event.pointerId)
  window.addEventListener('pointermove', move)
  window.addEventListener('pointerup', end, { once: true })
  window.addEventListener('pointercancel', end, { once: true })
}

const startMove = (event, layer) => begin(event, layer, 'move')
const startResize = (event, layer, handle) => begin(event, layer, 'resize', handle)

function move(event) {
  const d = drag.value
  const rect = sheet.value?.getBoundingClientRect()
  if (!d || !rect?.width || !rect?.height) return
  const dx = (event.clientX - d.startX) / rect.width
  const dy = (event.clientY - d.startY) / rect.height
  if (Math.abs(event.clientX - d.startX) + Math.abs(event.clientY - d.startY) > 2) d.moved = true
  d.box = d.mode === 'move' ? textMoveBox(d.start, dx, dy) : textResizeBox(d.start, d.handle, dx, dy)
}

function end() {
  window.removeEventListener('pointermove', move)
  window.removeEventListener('pointerup', end)
  window.removeEventListener('pointercancel', end)
  const d = drag.value
  drag.value = null
  if (d?.moved) tool.edit({ layers: textPatchLayer(tool.state.layers, d.id, d.box) })
}

/** Arrow keys move the picked box a little (with Shift — more). */
function nudge(event, layer) {
  const steps = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }
  const dir = steps[event.key]
  if (!dir) return
  event.preventDefault()
  tool.state.selectedId = layer.id
  const k = event.shiftKey ? 0.02 : 0.005
  tool.edit({ layers: textPatchLayer(tool.state.layers, layer.id, textMoveBox(layer, dir[0] * k, dir[1] * k)) })
}

onBeforeUnmount(() => {
  window.removeEventListener('pointermove', move)
  window.removeEventListener('pointerup', end)
  window.removeEventListener('pointercancel', end)
})
</script>
