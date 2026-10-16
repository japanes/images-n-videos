<template>
  <!--
    The picture with the found objects drawn over it. Click an object to pick
    it, or drag a rectangle by hand. v-model: null | { id } | { label, box }.
  -->
  <div
    ref="area"
    class="relative inline-block max-w-full touch-none select-none"
    :class="disabled ? 'cursor-default' : 'cursor-crosshair'"
    @pointerdown="start"
    @pointermove="move"
    @pointerup="end"
    @pointercancel="drag = null"
  >
    <img ref="img" :src="src" alt="" draggable="false" class="block max-h-[68vh] max-w-full rounded-button">
    <button
      v-for="o in objects"
      :key="o.id"
      type="button"
      class="absolute rounded-sm border-2 transition-colors"
      :class="selectedId === o.id
        ? 'border-fuchsia-500 bg-fuchsia-500/20'
        : 'border-white/80 shadow-[0_0_0_1px_rgba(0,0,0,.4)] hover:border-fuchsia-400 hover:bg-fuchsia-400/10'"
      :style="studioBoxStyle(o.box)"
      :title="o.label"
      :aria-label="o.label"
      :aria-pressed="selectedId === o.id"
      :disabled="disabled"
      @pointerdown.stop
      @click.stop="pick(o)"
    >
      <span
        class="absolute left-0 top-0 max-w-full truncate rounded-br bg-slate-900/75 px-1 text-left text-[10px] leading-4 text-white"
      >{{ o.label }}</span>
    </button>
    <div
      v-if="drawnBox"
      class="pointer-events-none absolute rounded-sm border-2 border-dashed border-fuchsia-500 bg-fuchsia-500/15"
      :style="studioBoxStyle(drawnBox)"
    />
  </div>
</template>

<script setup>
import { studioBoxFromPoints, studioBoxStyle } from '~/utils/studioView.js'

const props = defineProps({
  src: { type: String, default: '' },
  objects: { type: Array, default: () => [] },
  modelValue: { type: Object, default: null },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue'])

const img = ref(null)
const drag = ref(null) // { a: {x, y}, b: {x, y} } while drawing

const selectedId = computed(() => props.modelValue?.id || null)
const drawnBox = computed(() => {
  if (drag.value) return studioBoxFromPoints(drag.value.a, drag.value.b)
  return !props.modelValue?.id && props.modelValue?.box ? props.modelValue.box : null
})

function point(e) {
  const r = img.value?.getBoundingClientRect()
  if (!r || !r.width || !r.height) return null
  return { x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height }
}

function start(e) {
  if (props.disabled || e.button > 0) return
  const p = point(e)
  if (!p) return
  drag.value = { a: p, b: p }
  e.currentTarget.setPointerCapture?.(e.pointerId)
}

function move(e) {
  if (!drag.value) return
  const p = point(e)
  if (p) drag.value = { ...drag.value, b: p }
}

function end() {
  if (!drag.value) return
  const box = studioBoxFromPoints(drag.value.a, drag.value.b)
  drag.value = null
  emit('update:modelValue', box ? { label: '', box } : null)
}

function pick(o) {
  emit('update:modelValue', selectedId.value === o.id ? null : { id: o.id })
}
</script>
