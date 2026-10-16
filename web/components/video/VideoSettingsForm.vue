<template>
  <!--
    How the video is made: model, size, length, shape, camera move and sound.
    v-model is { model_id, resolution, duration, aspect, camera_move, sound };
    a model switch brings the other fields inside what that model allows.
  -->
  <div class="space-y-3 text-sm">
    <label class="block space-y-1">
      <span class="label">{{ t('video.form.model') }}</span>
      <select class="input" :value="value.model_id || ''" :disabled="disabled" @change="setModel($event.target.value)">
        <option v-for="m in choices" :key="m.id" :value="m.id" :disabled="m.available === false">
          {{ modelLabel(m) }}
        </option>
      </select>
    </label>
    <p v-if="model && model.available === false" class="text-xs text-amber-700 dark:text-amber-300">
      {{ t('video.form.modelUnavailable') }}
    </p>

    <div class="grid grid-cols-3 gap-2">
      <label class="block space-y-1">
        <span class="label">{{ t('video.form.resolution') }}</span>
        <select class="input" :value="value.resolution" :disabled="disabled" @change="setField('resolution', $event.target.value)">
          <option v-for="r in resolutions" :key="r" :value="r">{{ r }}</option>
        </select>
      </label>
      <label class="block space-y-1">
        <span class="label">{{ t('video.form.duration') }}</span>
        <select class="input" :value="value.duration" :disabled="disabled" @change="setField('duration', Number($event.target.value))">
          <option v-for="d in durations" :key="d" :value="d">{{ t('video.form.seconds', { n: d }) }}</option>
        </select>
      </label>
      <label class="block space-y-1">
        <span class="label">{{ t('video.form.aspect') }}</span>
        <select class="input" :value="value.aspect" :disabled="disabled" @change="setField('aspect', $event.target.value)">
          <option v-for="a in aspects" :key="a" :value="a">{{ a }}</option>
        </select>
      </label>
    </div>

    <div class="space-y-1">
      <span class="label">{{ t('video.form.cameraMove') }}</span>
      <VideoCameraMovePicker
        :model-value="value.camera_move || ''"
        :moves="moves"
        :categories="categories"
        :disabled="disabled"
        @update:model-value="setField('camera_move', $event)"
      />
    </div>

    <div class="space-y-1">
      <ToggleSwitch
        :model-value="soundOn"
        :label="t('video.form.sound')"
        :disabled="disabled || !soundSwitch"
        @update:model-value="setField('sound', $event)"
      />
      <p v-if="!soundSwitch" class="muted text-xs">{{ t('video.form.soundAlways') }}</p>
    </div>
  </div>
</template>

<script setup>
import { videoDurationsFor, videoFitSettings, videoModelById, videoModelChoices, videoResolutionsFor } from '~/utils/videoView.js'

const props = defineProps({
  modelValue: { type: Object, required: true },
  models: { type: Array, default: () => [] },
  moves: { type: Array, default: () => [] },
  categories: { type: Array, default: () => [] },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue'])
const { t } = useI18n()

const value = computed(() => props.modelValue || {})
const model = computed(() => videoModelById(props.models, value.value.model_id))
const choices = computed(() => videoModelChoices(props.models, value.value.model_id))
const resolutions = computed(() => videoResolutionsFor(model.value))
const durations = computed(() => videoDurationsFor(model.value, value.value.resolution))
const aspects = computed(() => model.value?.aspects || [])
const soundSwitch = computed(() => Boolean(model.value?.sound_switch))
const soundOn = computed(() => (soundSwitch.value ? Boolean(value.value.sound) : true))

function modelLabel(m) {
  const parts = [m.title || m.id]
  if (m.preview) parts.push(t('video.form.preview'))
  if (m.available === false) parts.push(t('video.form.unavailable'))
  return parts.join(' · ')
}

function setField(key, v) {
  const next = { ...value.value, [key]: v }
  if (key === 'resolution') Object.assign(next, videoFitSettings(model.value, next))
  emit('update:modelValue', next)
}

function setModel(id) {
  const m = videoModelById(props.models, id)
  if (!m) return
  emit('update:modelValue', { ...value.value, model_id: id, ...videoFitSettings(m, value.value) })
}
</script>
