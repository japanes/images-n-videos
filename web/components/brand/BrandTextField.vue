<template>
  <textarea
    v-if="multiline"
    ref="el"
    v-model="draft"
    :rows="rows"
    :maxlength="maxlength || undefined"
    :placeholder="placeholder"
    :disabled="disabled"
    :aria-label="ariaLabel || placeholder || undefined"
    :class="inputClass"
    @focus="editing = true"
    @blur="finish"
  />
  <input
    v-else
    ref="el"
    v-model="draft"
    type="text"
    :maxlength="maxlength || undefined"
    :placeholder="placeholder"
    :disabled="disabled"
    :aria-label="ariaLabel || placeholder || undefined"
    :class="inputClass"
    @focus="editing = true"
    @blur="finish"
    @keydown.enter.prevent="el?.blur()"
    @keydown.escape="cancel"
  >
</template>

<script setup>
/**
 * A text field that saves itself: emits `save` with the new text on blur
 * (and on Enter for a one-line field) when the text changed. While the field
 * has focus, outside updates of `modelValue` (live events, reloads) do not
 * overwrite what the user is typing.
 */
const props = defineProps({
  modelValue: { type: String, default: '' },
  multiline: { type: Boolean, default: false },
  rows: { type: Number, default: 4 },
  maxlength: { type: Number, default: 0 },
  placeholder: { type: String, default: '' },
  ariaLabel: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
  inputClass: { type: [String, Array, Object], default: 'input' },
})
const emit = defineEmits(['save'])

const el = ref(null)
const draft = ref(props.modelValue || '')
const editing = ref(false)

watch(() => props.modelValue, (value) => {
  if (!editing.value) draft.value = value || ''
})

function finish() {
  editing.value = false
  if ((draft.value || '') !== (props.modelValue || '')) emit('save', draft.value || '')
}

function cancel() {
  draft.value = props.modelValue || ''
  el.value?.blur()
}
</script>
