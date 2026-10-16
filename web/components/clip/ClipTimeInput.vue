<template>
  <div class="flex items-center gap-1">
    <input
      type="text"
      inputmode="decimal"
      class="input w-24 tabular-nums"
      :value="text"
      :placeholder="placeholder"
      :aria-label="label"
      @change="onChange"
    >
    <button type="button" class="btn-ghost btn-sm whitespace-nowrap" :title="t('clip.time.nowHint')" @click="$emit('update:modelValue', round3(time))">
      {{ t('clip.time.now') }}
    </button>
    <button v-if="nullable && modelValue !== null" type="button" class="btn-ghost btn-sm whitespace-nowrap" @click="$emit('update:modelValue', null)">
      {{ nullLabel }}
    </button>
  </div>
</template>

<script setup>
import { clipFormatTime, clipParseTime } from '~/utils/clipState.js'

const props = defineProps({
  modelValue: { type: Number, default: null },
  nullable: { type: Boolean, default: false },
  nullLabel: { type: String, default: '' },
  placeholder: { type: String, default: '' },
  label: { type: String, default: '' },
  max: { type: Number, default: null },
})
const emit = defineEmits(['update:modelValue'])
const { t } = useI18n()
const { time } = useClipContext()
const round3 = (v) => Math.round(v * 1000) / 1000

const text = computed(() => (props.modelValue === null ? '' : clipFormatTime(props.modelValue)))

function onChange(e) {
  const raw = e.target.value
  if (!raw.trim() && props.nullable) {
    emit('update:modelValue', null)
    return
  }
  let v = clipParseTime(raw)
  if (v === null) {
    e.target.value = text.value
    return
  }
  if (props.max !== null) v = Math.min(v, props.max)
  emit('update:modelValue', v)
  e.target.value = clipFormatTime(v)
}
</script>
