<template>
  <div class="space-y-4">
    <div class="flex flex-wrap gap-2">
      <button type="button" class="btn-secondary btn-sm" :disabled="!canAddText" @click="addText">
        <AppIcon name="text" :size="14" />{{ t('clip.layers.addText') }}
      </button>
      <button type="button" class="btn-secondary btn-sm" :disabled="!canAddImage" @click="pickerOpen = true">
        <AppIcon name="image" :size="14" />{{ t('clip.layers.addPicture') }}
      </button>
    </div>
    <p v-if="!canAddText || !canAddImage" class="text-xs muted">
      {{ t('clip.layers.limit', { layers: CLIP_MAX_LAYERS, pictures: CLIP_MAX_IMAGE_LAYERS }) }}
    </p>

    <p v-if="!state.layers.length" class="text-sm muted">{{ t('clip.layers.empty') }}</p>
    <ul v-else class="space-y-1">
      <li
        v-for="{ layer, i } in ordered"
        :key="layer.id"
        class="flex items-center gap-1 rounded-button border px-2 py-1"
        :class="layer.id === selectedId ? 'border-primary bg-primary/5' : 'border-slate-200 dark:border-slate-700'"
      >
        <button type="button" class="flex min-w-0 flex-1 items-center gap-2 text-left" @click="select(layer)">
          <AppIcon :name="layer.type === 'text' ? 'text' : 'image'" :size="14" class="shrink-0 muted" />
          <span class="min-w-0 flex-1">
            <span class="block truncate text-sm" :class="layer.visible === false && 'line-through muted'">{{ layerName(layer) }}</span>
            <span class="block text-[11px] muted tabular-nums">{{ layerTimes(layer) }}</span>
          </span>
        </button>
        <button
          type="button"
          class="btn-ghost p-1"
          :class="layer.visible === false && 'opacity-40'"
          :title="layer.visible === false ? t('clip.layers.show') : t('clip.layers.hide')"
          @click="layer.visible = layer.visible === false"
        >
          <AppIcon name="eye" :size="14" />
        </button>
        <button type="button" class="btn-ghost p-1" :disabled="i === state.layers.length - 1" :title="t('clip.layers.up')" @click="move(i, 1)">
          <AppIcon name="chevron-down" :size="14" class="rotate-180" />
        </button>
        <button type="button" class="btn-ghost p-1" :disabled="i === 0" :title="t('clip.layers.down')" @click="move(i, -1)">
          <AppIcon name="chevron-down" :size="14" />
        </button>
        <button type="button" class="btn-ghost p-1 text-rose-600" :title="t('clip.layers.remove')" @click="removeLayer(layer)">
          <AppIcon name="trash" :size="14" />
        </button>
      </li>
    </ul>
    <p v-if="state.layers.length > 1" class="text-[11px] muted">{{ t('clip.layers.orderHint') }}</p>

    <div v-if="selected" class="space-y-3 border-t border-slate-200 pt-3 dark:border-slate-700">
      <template v-if="selected.type === 'text'">
        <label class="block">
          <span class="label">{{ t('clip.layers.text') }}</span>
          <textarea v-model="selected.text" class="input min-h-[4rem]" rows="3" maxlength="500" :placeholder="t('clip.layers.textHint')" />
        </label>
        <label class="block">
          <span class="label">{{ t('clip.layers.font') }}</span>
          <select class="input" :value="fontValue" @change="setFont($event.target.value)">
            <optgroup v-if="brandFonts.length" :label="t('clip.layers.brandFonts')">
              <option v-for="f in brandFonts" :key="`b${f.file_id}`" :value="`b:${f.file_id}`">{{ f.family }}</option>
            </optgroup>
            <optgroup :label="t('clip.layers.builtinFonts')">
              <option v-for="f in CLIP_BUILTIN_FONTS" :key="f" :value="`f:${f}`">{{ f }}</option>
            </optgroup>
            <option v-if="fontMissing" :value="fontValue">{{ selected.font }}</option>
          </select>
        </label>
        <label class="block">
          <span class="label">{{ t('clip.layers.size', { pct: Math.round(selected.size * 100) }) }}</span>
          <input v-model.number="selected.size" type="range" min="0.01" max="0.3" step="0.005" class="w-full">
        </label>
        <div class="flex flex-wrap items-center gap-3">
          <label class="flex items-center gap-2 text-sm">
            <input v-model="selected.color" type="color" class="h-7 w-10 cursor-pointer rounded border border-slate-300 dark:border-slate-600">
            {{ t('clip.layers.color') }}
          </label>
          <ToggleSwitch v-model="selected.bold" :label="t('clip.layers.bold')" />
          <ToggleSwitch v-model="selected.italic" :label="t('clip.layers.italic')" />
          <ToggleSwitch v-model="selected.outline" :label="t('clip.layers.outline')" :disabled="selected.plate" />
        </div>
        <div class="space-y-2">
          <ToggleSwitch v-model="selected.plate" :label="t('clip.layers.plate')" />
          <div v-if="selected.plate" class="flex flex-wrap items-center gap-3 pl-11">
            <label class="flex items-center gap-2 text-sm">
              <input v-model="selected.plate_color" type="color" class="h-7 w-10 cursor-pointer rounded border border-slate-300 dark:border-slate-600">
              {{ t('clip.layers.plateColor') }}
            </label>
            <label class="flex min-w-[8rem] flex-1 items-center gap-2 text-sm">
              <span class="whitespace-nowrap">{{ t('clip.layers.plateOpacity', { pct: Math.round(selected.plate_opacity * 100) }) }}</span>
              <input v-model.number="selected.plate_opacity" type="range" min="0" max="1" step="0.05" class="w-full">
            </label>
          </div>
        </div>
      </template>

      <template v-else>
        <div class="flex items-center gap-3">
          <div class="clip-checker flex h-14 w-14 shrink-0 items-center justify-center overflow-hidden rounded-button">
            <img :src="`/files/${selected.file_id}?w=240`" alt="" class="max-h-full max-w-full object-contain">
          </div>
          <button type="button" class="btn-ghost btn-sm" @click="replacing = true; pickerOpen = true">
            {{ t('clip.layers.replacePicture') }}
          </button>
        </div>
        <label class="block">
          <span class="label">{{ t('clip.layers.width', { pct: Math.round(selected.width * 100) }) }}</span>
          <input v-model.number="selected.width" type="range" min="0.02" max="1" step="0.01" class="w-full">
        </label>
        <label class="block">
          <span class="label">{{ t('clip.layers.opacity', { pct: Math.round(selected.opacity * 100) }) }}</span>
          <input v-model.number="selected.opacity" type="range" min="0" max="1" step="0.05" class="w-full">
        </label>
      </template>

      <div class="flex flex-wrap gap-2">
        <button type="button" class="btn-ghost btn-sm" @click="selected.x = 0.5">{{ t('clip.layers.centerX') }}</button>
        <button type="button" class="btn-ghost btn-sm" @click="selected.y = 0.5">{{ t('clip.layers.centerY') }}</button>
      </div>
      <p class="text-[11px] muted">{{ t('clip.layers.dragHint') }}</p>

      <div class="grid gap-2">
        <div>
          <span class="label">{{ t('clip.layers.from') }}</span>
          <ClipTimeInput v-model="layerStart" :max="duration" :label="t('clip.layers.from')" />
        </div>
        <div>
          <span class="label">{{ t('clip.layers.to') }}</span>
          <ClipTimeInput
            v-model="layerEnd"
            :max="duration"
            nullable
            :null-label="t('clip.layers.toEnd')"
            :placeholder="t('clip.layers.toEndShort')"
            :label="t('clip.layers.to')"
          />
        </div>
      </div>
    </div>
    <p v-else-if="state.layers.length" class="text-sm muted">{{ t('clip.layers.selectHint') }}</p>

    <div class="border-t border-slate-200 pt-3 dark:border-slate-700">
      <ClipBrandPicker :hint="t('clip.brand.layersHint')" />
    </div>

    <ClipMediaPicker
      :open="pickerOpen"
      kind="image"
      :title="replacing ? t('clip.layers.replacePicture') : t('clip.layers.addPicture')"
      :extra="brandPictures"
      :extra-title="t('clip.layers.brandPictures')"
      @pick="onPick"
      @close="closePicker"
    />
  </div>
</template>

<script setup>
import {
  CLIP_BUILTIN_FONTS, CLIP_MAX_IMAGE_LAYERS, CLIP_MAX_LAYERS, clipBrandFonts, clipCanAddLayer, clipFormatTime,
  clipMove, clipNewImageLayer, clipNewTextLayer,
} from '~/utils/clipState.js'

const { t } = useI18n()
const { confirm } = useConfirm()
const ed = useClipContext()
const { state, project, selectedId, selected, time, duration, seek } = ed

const pickerOpen = ref(false)
const replacing = ref(false)

const canAddText = computed(() => clipCanAddLayer(state.value.layers, 'text'))
const canAddImage = computed(() => clipCanAddLayer(state.value.layers, 'image'))
const brandFonts = computed(() => clipBrandFonts(project.value?.brand))
const brandPictures = computed(() => {
  const brand = project.value?.brand
  if (!brand) return []
  return [...(brand.logos || []), ...(brand.elements || [])]
    .filter((x) => x.file_id)
    .map((x) => ({ id: x.file_id, title: x.name || '' }))
})

// top of the list = drawn last, over everything else
const ordered = computed(() => state.value.layers.map((layer, i) => ({ layer, i })).reverse())

const fontValue = computed(() => {
  const l = selected.value
  if (!l) return ''
  return l.font_file_id ? `b:${l.font_file_id}` : `f:${l.font}`
})
const fontMissing = computed(() => {
  const l = selected.value
  if (!l || l.type !== 'text') return false
  if (l.font_file_id) return !brandFonts.value.some((f) => f.file_id === l.font_file_id)
  return !CLIP_BUILTIN_FONTS.includes(l.font)
})

function setFont(value) {
  const l = selected.value
  if (!l) return
  if (value.startsWith('b:')) {
    const font = brandFonts.value.find((f) => String(f.file_id) === value.slice(2))
    if (!font) return
    l.font = font.family
    l.font_file_id = font.file_id
    clipEnsureFont(font.family, font.file_id)
  } else if (value.startsWith('f:')) {
    l.font = value.slice(2)
    l.font_file_id = null
  }
}

const layerStart = computed({
  get: () => selected.value?.start ?? 0,
  set: (v) => {
    const l = selected.value
    if (!l) return
    l.start = Math.max(0, v ?? 0)
    if (l.end !== null && l.end <= l.start) l.end = null
  },
})
const layerEnd = computed({
  get: () => selected.value?.end ?? null,
  set: (v) => {
    const l = selected.value
    if (!l) return
    l.end = v === null ? null : Math.max(v, (l.start || 0) + 0.1)
  },
})

function layerName(layer) {
  if (layer.type === 'text') return layer.text?.trim() || t('clip.layers.emptyText')
  return t('clip.layers.picture')
}

function layerTimes(layer) {
  const from = clipFormatTime(layer.start || 0)
  const to = layer.end === null || layer.end === undefined ? t('clip.layers.toEndShort') : clipFormatTime(layer.end)
  return `${from} – ${to}`
}

function select(layer) {
  selectedId.value = layer.id
  const end = layer.end ?? Infinity
  if (time.value < (layer.start || 0) || time.value > end) seek(layer.start || 0)
}

function addText() {
  if (!canAddText.value) return
  const layer = clipNewTextLayer(t('clip.layers.newText'), time.value)
  state.value.layers.push(layer)
  selectedId.value = layer.id
}

function onPick(item) {
  const fileId = item.id
  if (replacing.value && selected.value?.type === 'image') {
    selected.value.file_id = fileId
  } else if (canAddImage.value) {
    const layer = clipNewImageLayer(fileId, time.value)
    state.value.layers.push(layer)
    selectedId.value = layer.id
  }
  closePicker()
}

function closePicker() {
  pickerOpen.value = false
  replacing.value = false
}

function move(index, step) {
  state.value.layers = clipMove(state.value.layers, index, step)
}

async function removeLayer(layer) {
  const ok = await confirm({ message: t('clip.layers.removeAsk', { name: layerName(layer) }), tone: 'danger',
    confirmLabel: t('clip.layers.remove') })
  if (!ok) return
  state.value.layers = state.value.layers.filter((l) => l.id !== layer.id)
  if (selectedId.value === layer.id) selectedId.value = null
}
</script>

<style scoped>
.clip-checker {
  background-color: #e2e8f0;
  background-image: linear-gradient(45deg, #cbd5e1 25%, transparent 25%), linear-gradient(-45deg, #cbd5e1 25%, transparent 25%),
    linear-gradient(45deg, transparent 75%, #cbd5e1 75%), linear-gradient(-45deg, transparent 75%, #cbd5e1 75%);
  background-size: 12px 12px;
  background-position: 0 0, 0 6px, 6px -6px, -6px 0;
}
</style>
