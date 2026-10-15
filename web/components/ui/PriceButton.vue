<template>
  <!--
    A paid action always shows its approximate price before the click (project
    rule). Give either `usd` (already known) or `estimate` (a request for
    POST /api/estimate, or a list of them for the batch endpoint).
  -->
  <button
    type="button"
    :class="[variantClass, 'whitespace-nowrap']"
    :disabled="disabled || busy"
    :title="priceTitle"
    @click="$emit('click', $event)"
  >
    <Spinner v-if="busy" :size="14" />
    <AppIcon v-else-if="icon" :name="icon" :size="16" />
    <span v-if="label || $slots.default"><slot>{{ label }}</slot></span>
    <span v-if="showPrice" class="rounded-badge bg-black/10 px-1.5 py-0.5 text-xs font-semibold tabular-nums dark:bg-white/10">
      {{ priceText }}
    </span>
  </button>
</template>

<script setup>
import { formatUsd } from '~/utils/format.js'

const props = defineProps({
  label: { type: String, default: '' },
  icon: { type: String, default: '' },
  usd: { type: Number, default: null },
  estimate: { type: [Object, Array], default: null },
  disabled: { type: Boolean, default: false },
  busy: { type: Boolean, default: false },
  variant: { type: String, default: 'primary' },
})
defineEmits(['click'])

const { t } = useI18n()
const est = useEstimate(() => (props.usd === null ? props.estimate : null))
const value = computed(() => (props.usd !== null ? props.usd : est.usd.value))
const showPrice = computed(() => props.usd !== null || props.estimate !== null)
const priceText = computed(() => {
  if (value.value === null) return est.loading.value ? '…' : '$?'
  return value.value === 0 ? t('common.free') : formatUsd(value.value, { approx: true })
})
const priceTitle = computed(() => (showPrice.value ? t('common.priceHint') : undefined))
const variantClass = computed(() => ({
  primary: 'btn-primary',
  secondary: 'btn-secondary',
  ghost: 'btn-ghost',
  danger: 'btn-danger',
}[props.variant] || 'btn-primary'))
</script>
