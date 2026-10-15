<template>
  <label class="inline-flex cursor-pointer select-none items-center gap-2" :class="disabled && 'cursor-not-allowed opacity-50'">
    <button
      type="button"
      role="switch"
      :aria-checked="modelValue"
      :disabled="disabled"
      class="relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors"
      :class="modelValue ? 'bg-primary' : 'bg-slate-300 dark:bg-slate-600'"
      @click="$emit('update:modelValue', !modelValue)"
    >
      <span class="inline-block h-4 w-4 rounded-full bg-white shadow transition-transform" :class="modelValue ? 'translate-x-[18px]' : 'translate-x-0.5'" />
    </button>
    <span v-if="label || $slots.default" class="text-sm"><slot>{{ label }}</slot></span>
  </label>
</template>

<script setup>
defineProps({
  modelValue: { type: Boolean, default: false },
  label: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
})
defineEmits(['update:modelValue'])
</script>
