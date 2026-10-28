<template>
  <!--
    The cost of one object from the spend journal, for other screens:
      <SpendCost ref-type="clip" :ref-id="clip.id" />
    Click → the spend log filtered to this object.
  -->
  <span v-if="visible" class="inline-flex items-center gap-1 whitespace-nowrap text-xs tabular-nums muted" :title="title">
    <AppIcon name="spend" :size="14" />
    <NuxtLink v-if="linked" :to="link" class="hover:underline">{{ text }}</NuxtLink>
    <span v-else>{{ text }}</span>
    <Spinner v-if="cost && cost.running > 0" :size="12" />
  </span>
</template>

<script setup>
import { formatUsd } from '~/utils/format.js'

const props = defineProps({
  refType: { type: String, required: true },
  refId: { type: [Number, String], default: null },
  /** show "$0.00" even when nothing was called yet */
  showZero: { type: Boolean, default: false },
  linked: { type: Boolean, default: true },
})

const { t } = useI18n()
const { cost } = useSpendCost(() => [props.refType, props.refId])

const visible = computed(() => cost.value && (cost.value.calls > 0 || props.showZero))
const text = computed(() => {
  const c = cost.value
  if (!c) return ''
  if (c.usd > 0) return formatUsd(c.usd, { approx: true })
  if (c.stub_calls > 0) return t('spend.cost.stubOnly')
  return formatUsd(0)
})
const title = computed(() => t('spend.cost.title', { n: cost.value?.calls || 0 }))
const link = computed(() => ({
  path: '/settings/spend',
  query: { period: 'all', ref_type: props.refType, ref_id: String(props.refId), stub: cost.value?.stub_calls ? '1' : undefined },
}))
</script>
