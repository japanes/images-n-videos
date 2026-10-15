<template>
  <div class="overflow-x-auto">
    <table class="text-sm">
      <thead>
        <tr class="text-left">
          <th class="label pr-3 font-medium">{{ t('settings.aspect.shape') }}</th>
          <th class="label pr-3 font-medium">{{ t('settings.aspect.width') }}</th>
          <th class="label font-medium">{{ t('settings.aspect.height') }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(row, i) in modelValue" :key="row.aspect">
          <td class="py-1 pr-3 font-mono tabular-nums">{{ row.aspect }}</td>
          <td class="py-1 pr-3">
            <input
              :value="row.w"
              type="number"
              class="input w-28 tabular-nums"
              :min="ASPECT_SIDE_MIN"
              :max="ASPECT_SIDE_MAX"
              step="1"
              :placeholder="placeholder(row.aspect, 0)"
              :aria-label="`${row.aspect} ${t('settings.aspect.width')}`"
              @input="update(i, 'w', $event.target.value)"
            >
          </td>
          <td class="py-1">
            <input
              :value="row.h"
              type="number"
              class="input w-28 tabular-nums"
              :min="ASPECT_SIDE_MIN"
              :max="ASPECT_SIDE_MAX"
              step="1"
              :placeholder="placeholder(row.aspect, 1)"
              :aria-label="`${row.aspect} ${t('settings.aspect.height')}`"
              @input="update(i, 'h', $event.target.value)"
            >
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup>
import { ASPECT_SIDE_MAX, ASPECT_SIDE_MIN } from '~/utils/modelsView.js'

// Rows `[{ aspect, w, h }]` as the user types them; the page turns them back
// into the stored value (and checks them) on save.
const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  defaults: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['update:modelValue'])

const { t } = useI18n()

function placeholder(aspect, side) {
  const pair = props.defaults?.[aspect]
  return Array.isArray(pair) && pair[side] !== undefined ? String(pair[side]) : ''
}

function update(index, side, value) {
  emit('update:modelValue', props.modelValue.map((row, i) => (i === index ? { ...row, [side]: value } : row)))
}
</script>
