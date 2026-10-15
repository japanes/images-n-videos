<template>
  <section class="card spend-palette p-4">
    <header class="mb-3 flex flex-wrap items-center gap-x-4 gap-y-2">
      <h2 class="text-sm font-semibold">{{ t('spend.chart.title') }}</h2>
      <!-- Legend: always there for 2+ groups; colour sits beside the text, never on it. -->
      <ul v-if="legend.length > 1" class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-600 dark:text-slate-300">
        <li v-for="k in legend" :key="k" class="inline-flex items-center gap-1.5">
          <span class="inline-block h-2.5 w-2.5 rounded-sm" :style="{ background: `var(--spend-${k})` }" />
          {{ spendLabel(t, te, 'kinds', k) }}
        </li>
      </ul>
      <button type="button" class="btn-ghost btn-sm ml-auto" :aria-pressed="asTable" @click="asTable = !asTable">
        {{ asTable ? t('spend.chart.showChart') : t('spend.chart.showTable') }}
      </button>
    </header>

    <!-- Table view: the same numbers without hovering. -->
    <div v-if="asTable" class="max-h-80 overflow-auto">
      <p v-if="!activeDays.length" class="py-8 text-center text-sm muted">{{ t('spend.chart.empty') }}</p>
      <table v-else class="w-full text-sm">
        <thead class="sticky top-0 bg-white text-left text-xs muted dark:bg-slate-800">
          <tr>
            <th class="py-1.5 pr-3 font-medium">{{ t('spend.chart.day') }}</th>
            <th class="py-1.5 pr-3 text-right font-medium">{{ t('spend.chart.total') }}</th>
            <th v-for="k in legend" :key="k" class="py-1.5 pr-3 text-right font-medium">{{ spendLabel(t, te, 'kinds', k) }}</th>
            <th class="py-1.5 text-right font-medium">{{ t('spend.chart.calls') }}</th>
          </tr>
        </thead>
        <tbody class="tabular-nums">
          <tr v-for="d in activeDays.slice().reverse()" :key="d.day" class="border-t border-slate-100 dark:border-slate-700">
            <td class="py-1.5 pr-3">{{ longDay(d.day) }}</td>
            <td class="py-1.5 pr-3 text-right font-medium">{{ formatUsd(d.usd, { approx: true }) }}</td>
            <td v-for="k in legend" :key="k" class="py-1.5 pr-3 text-right">{{ d.by_kind?.[k] ? formatUsd(d.by_kind[k]) : '—' }}</td>
            <td class="py-1.5 text-right">{{ d.calls }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="activeDays.length" class="mt-2 text-xs muted">{{ t('spend.chart.emptyDaysHidden') }}</p>
    </div>

    <div
      v-else
      ref="box"
      class="relative outline-none"
      tabindex="0"
      role="img"
      :aria-label="t('spend.chart.aria', { days: days.length })"
      @keydown="onKey"
      @focus="onFocus"
      @blur="hover = null"
    >
      <svg :width="width" :height="HEIGHT" class="block select-none" @pointerleave="hover = null">
        <!-- recessive grid: hairlines one step off the surface -->
        <g>
          <template v-for="tick in scale.ticks" :key="tick">
            <line :x1="LEFT" :x2="width" :y1="yOf(tick)" :y2="yOf(tick)" class="spend-grid" shape-rendering="crispEdges" />
            <text :x="LEFT - 8" :y="yOf(tick)" dy="0.32em" text-anchor="end" class="spend-axis">{{ tickText(tick) }}</text>
          </template>
        </g>
        <rect v-if="hover !== null" :x="LEFT + hover * slot" :y="TOP" :width="slot" :height="PLOT" class="spend-hover" />
        <g>
          <template v-for="(bar, i) in bars" :key="bar.day">
            <path v-for="seg in bar.segments" :key="seg.kind" :d="segPath(bar.x, seg)" :style="{ fill: `var(--spend-${seg.kind})` }" />
            <text v-if="i % labelEvery === 0" :x="LEFT + i * slot + slot / 2" :y="HEIGHT - 4" text-anchor="middle" class="spend-axis">{{ shortDay(bar.day) }}</text>
          </template>
        </g>
        <!-- hit targets: the whole day column, bigger than the bar -->
        <rect
          v-for="(bar, i) in bars"
          :key="`hit-${bar.day}`"
          :x="LEFT + i * slot"
          :y="TOP"
          :width="Math.max(slot, 1)"
          :height="PLOT"
          fill="transparent"
          @pointerenter="hover = i"
          @pointermove="hover = i"
        />
      </svg>
      <p v-if="!hasSpend" class="pointer-events-none absolute inset-x-0 top-1/3 text-center text-sm muted">{{ t('spend.chart.empty') }}</p>

      <div
        v-if="hovered"
        class="pointer-events-none absolute top-0 z-10 w-48 rounded-lg border border-slate-200 bg-white p-2.5 text-xs shadow-card dark:border-slate-700 dark:bg-slate-900"
        :style="{ left: `${tipLeft}px` }"
      >
        <p class="muted">{{ longDay(hovered.day) }}</p>
        <p class="mt-0.5 text-sm font-semibold tabular-nums">
          {{ formatUsd(hovered.usd, { approx: true }) }}
          <span class="ml-1 text-xs font-normal muted">{{ t('spend.chart.callsN', { n: hovered.calls }, hovered.calls) }}</span>
        </p>
        <ul v-if="hoveredKinds.length" class="mt-1.5 space-y-1">
          <li v-for="k in hoveredKinds" :key="k.kind" class="flex items-center gap-2">
            <span class="inline-block h-0.5 w-3 rounded" :style="{ background: `var(--spend-${k.kind})` }" />
            <span class="font-semibold tabular-nums">{{ formatUsd(k.usd) }}</span>
            <span class="truncate text-slate-600 dark:text-slate-300">{{ spendLabel(t, te, 'kinds', k.kind) }}</span>
          </li>
        </ul>
      </div>
    </div>
  </section>
</template>

<script setup>
import { formatUsd } from '~/utils/format.js'
import {
  SPEND_KINDS, spendLabel, spendLabelEvery, spendNiceScale, spendParseDay, spendStack,
} from '~/composables/useSpend.js'

const props = defineProps({
  days: { type: Array, default: () => [] },
})
const { t, te, locale } = useI18n()

const HEIGHT = 220
const TOP = 8
const BOTTOM = 22
const LEFT = 56
const PLOT = HEIGHT - TOP - BOTTOM

const asTable = ref(false)
const hover = ref(null)
const box = ref(null)
const width = ref(600)
let observer = null
const measure = () => { if (box.value) width.value = Math.max(240, box.value.clientWidth) }
onMounted(() => {
  measure()
  if (typeof ResizeObserver !== 'undefined') {
    observer = new ResizeObserver(measure)
    if (box.value) observer.observe(box.value)
  }
})
watch(box, (el, old) => {
  if (old && observer) observer.unobserve(old)
  if (el) { measure(); observer?.observe(el) }
})
onBeforeUnmount(() => observer?.disconnect())

const plotW = computed(() => Math.max(1, width.value - LEFT))
const slot = computed(() => plotW.value / Math.max(1, props.days.length))
// Thin columns: at most 24px, a 2px surface gap between neighbours.
const barW = computed(() => Math.max(1, Math.min(24, slot.value - 2)))
const maxUsd = computed(() => props.days.reduce((m, d) => Math.max(m, Number(d.usd) || 0), 0))
const hasSpend = computed(() => maxUsd.value > 0)
const scale = computed(() => spendNiceScale(maxUsd.value))
const yOf = (v) => TOP + PLOT - (v / scale.value.max) * PLOT
const labelEvery = computed(() => spendLabelEvery(props.days.length, plotW.value))

const bars = computed(() => props.days.map((d, i) => ({
  day: d.day,
  x: LEFT + i * slot.value + (slot.value - barW.value) / 2,
  segments: spendStack(d.by_kind, scale.value.max, PLOT),
})))

const legend = computed(() => SPEND_KINDS.filter((k) => props.days.some((d) => Number(d.by_kind?.[k]) > 0)))
const activeDays = computed(() => props.days.filter((d) => d.calls > 0))

// Rounded 4px data end on the top segment only; square at the baseline.
function segPath(x, seg) {
  const w = barW.value
  const yBottom = TOP + PLOT - seg.y0
  const yTop = TOP + PLOT - seg.y1
  const h = yBottom - yTop
  const r = seg.top ? Math.min(4, w / 2, h) : 0
  if (r <= 0) return `M${x},${yBottom}V${yTop}H${x + w}V${yBottom}Z`
  return `M${x},${yBottom}V${yTop + r}Q${x},${yTop} ${x + r},${yTop}H${x + w - r}Q${x + w},${yTop} ${x + w},${yTop + r}V${yBottom}Z`
}

function tickText(v) {
  if (v >= 1000) return `$${Number((v / 1000).toPrecision(3))}K`
  return `$${Number(v.toPrecision(3))}`
}
const shortDay = (day) => spendParseDay(day)?.toLocaleDateString(locale.value, { day: 'numeric', month: 'short' }) || day
const longDay = (day) => spendParseDay(day)?.toLocaleDateString(locale.value, { weekday: 'short', day: 'numeric', month: 'long', year: 'numeric' }) || day

const hovered = computed(() => (hover.value === null ? null : props.days[hover.value] || null))
const hoveredKinds = computed(() => SPEND_KINDS
  .map((kind) => ({ kind, usd: Number(hovered.value?.by_kind?.[kind]) || 0 }))
  .filter((k) => k.usd > 0)
  .reverse()) // top of the stack first, like the column
const tipLeft = computed(() => {
  if (hover.value === null) return 0
  const center = LEFT + hover.value * slot.value + slot.value / 2
  const tipW = 192
  const right = center + 12
  return right + tipW <= width.value ? right : Math.max(0, center - 12 - tipW)
})

function onFocus() {
  if (hover.value !== null || !props.days.length) return
  let last = props.days.length - 1
  for (let i = props.days.length - 1; i >= 0; i--) if (props.days[i].calls > 0) { last = i; break }
  hover.value = last
}
function onKey(e) {
  const n = props.days.length
  if (!n) return
  if (e.key === 'ArrowLeft') { hover.value = Math.max(0, (hover.value ?? n) - 1); e.preventDefault() }
  else if (e.key === 'ArrowRight') { hover.value = Math.min(n - 1, (hover.value ?? -1) + 1); e.preventDefault() }
  else if (e.key === 'Home') { hover.value = 0; e.preventDefault() }
  else if (e.key === 'End') { hover.value = n - 1; e.preventDefault() }
  else if (e.key === 'Escape') hover.value = null
}
watch(() => props.days.length, () => { hover.value = null })
</script>

<style scoped>
.spend-grid { stroke: #e2e8f0; stroke-width: 1; }
.spend-axis { fill: #64748b; font-size: 11px; font-variant-numeric: tabular-nums; }
.spend-hover { fill: rgba(100, 116, 139, 0.08); }
:global(.dark) .spend-grid { stroke: #30385a; }
:global(.dark) .spend-axis { fill: #94a3b8; }
:global(.dark) .spend-hover { fill: rgba(148, 163, 184, 0.10); }
</style>
