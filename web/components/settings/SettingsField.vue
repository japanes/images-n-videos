<template>
  <div class="grid gap-2 py-4 md:grid-cols-[minmax(0,1fr)_minmax(14rem,20rem)] md:gap-6">
    <div class="min-w-0">
      <div class="flex flex-wrap items-center gap-2">
        <label v-if="item.kind !== 'bool'" :for="inputId" class="text-sm font-medium">{{ label }}</label>
        <span v-else class="text-sm font-medium">{{ label }}</span>
        <span v-if="dirty" class="badge bg-sky-50 text-sky-700 dark:bg-sky-500/10 dark:text-sky-300">{{ t('settings.changed') }}</span>
      </div>
      <p v-if="help" class="mt-0.5 text-sm muted">{{ help }}</p>
      <p v-if="label !== item.key" class="mt-0.5 font-mono text-[11px] text-slate-400 dark:text-slate-500">{{ item.key }}</p>
    </div>

    <div class="min-w-0 space-y-1">
      <ToggleSwitch
        v-if="item.kind === 'bool'"
        :model-value="!!modelValue"
        :label="modelValue ? t('common.on') : t('common.off')"
        @update:model-value="$emit('update:modelValue', $event)"
      />
      <select
        v-else-if="item.kind === 'enum'"
        :id="inputId"
        class="input"
        :value="modelValue"
        @change="$emit('update:modelValue', $event.target.value)"
      >
        <option v-for="c in item.choices || []" :key="String(c)" :value="String(c)">{{ choiceText(c) }}</option>
      </select>
      <input
        v-else-if="item.kind === 'int' || item.kind === 'float'"
        :id="inputId"
        :value="modelValue"
        type="text"
        :inputmode="item.kind === 'int' ? 'numeric' : 'decimal'"
        class="input tabular-nums"
        :class="error && 'border-rose-500'"
        :aria-invalid="!!error"
        @input="$emit('update:modelValue', $event.target.value)"
      >
      <SettingsAspectSizes
        v-else-if="item.meta?.widget === 'aspect_sizes'"
        :model-value="modelValue"
        :defaults="item.default || {}"
        @update:model-value="$emit('update:modelValue', $event)"
      />
      <textarea
        v-else-if="item.kind === 'json' || item.kind === 'any'"
        :id="inputId"
        :value="modelValue"
        rows="4"
        class="input font-mono text-xs"
        :class="error && 'border-rose-500'"
        :aria-invalid="!!error"
        spellcheck="false"
        @input="$emit('update:modelValue', $event.target.value)"
      />
      <input
        v-else
        :id="inputId"
        :value="modelValue"
        type="text"
        class="input"
        :class="error && 'border-rose-500'"
        :aria-invalid="!!error"
        @input="$emit('update:modelValue', $event.target.value)"
      >

      <p v-if="error" class="text-xs text-rose-700 dark:text-rose-300">{{ error }}</p>
      <div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs muted">
        <span v-if="defaultText !== null">{{ t('settings.default', { value: defaultText }) }}</span>
        <button v-if="!atDefault" type="button" class="text-primary hover:underline" @click="$emit('reset')">
          {{ t('settings.reset') }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { settingMessageKeys } from '~/utils/modelsView.js'

const props = defineProps({
  item: { type: Object, required: true },
  // What the user is editing: text for numbers and plain text, true/false,
  // the choice, rows for the sizes table, JSON text for anything else.
  modelValue: { type: [String, Number, Boolean, Array, Object], default: '' },
  error: { type: String, default: '' },
  dirty: { type: Boolean, default: false },
  atDefault: { type: Boolean, default: true },
})
defineEmits(['update:modelValue', 'reset'])

const { t, te } = useI18n()

const keys = computed(() => settingMessageKeys(props.item))
const firstKnown = (list) => list.find((k) => te(k)) || ''

// A setting another module added without strings of its own shows its key.
const label = computed(() => {
  const k = firstKnown(keys.value.label)
  return k ? t(k) : props.item.key
})
const help = computed(() => {
  const k = firstKnown(keys.value.help)
  return k ? t(k) : ''
})
const inputId = computed(() => `setting-${props.item.key.replace(/[^\w-]/g, '-')}`)

function choiceText(value) {
  const k = keys.value.choice(value)
  return te(k) ? t(k) : String(value)
}

const defaultText = computed(() => {
  const { kind, meta } = props.item
  const d = props.item.default
  if (meta?.widget === 'aspect_sizes') return null
  if (kind === 'bool') return d ? t('common.on') : t('common.off')
  if (kind === 'enum') return choiceText(d)
  if (d === null || d === undefined || d === '') return t('settings.notSet')
  if (typeof d === 'object') return JSON.stringify(d)
  return String(d)
})
</script>
