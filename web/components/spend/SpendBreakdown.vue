<template>
  <div class="grid gap-3 md:grid-cols-2">
    <!-- What the money went on: pictures, video, text. -->
    <section class="card spend-palette p-4">
      <h2 class="mb-3 text-sm font-semibold">{{ t('spend.breakdown.byKind') }}</h2>
      <p v-if="!kinds.length" class="py-4 text-sm muted">{{ t('spend.breakdown.empty') }}</p>
      <ul v-else class="space-y-2.5">
        <li v-for="row in kinds" :key="row.key">
          <button type="button" class="group w-full text-left" :title="t('spend.breakdown.pick')" @click="$emit('pick', { field: 'kind', value: row.key })">
            <span class="flex items-baseline gap-2 text-sm">
              <span class="inline-block h-2.5 w-2.5 shrink-0 rounded-sm" :style="{ background: `var(--spend-${row.key})` }" />
              <span class="min-w-0 flex-1 truncate group-hover:underline">{{ spendLabel(t, te, 'kinds', row.key) }}</span>
              <span class="font-semibold tabular-nums">{{ formatUsd(row.usd, { approx: true }) }}</span>
            </span>
            <span class="mt-1 flex items-center gap-2">
              <span class="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-700">
                <span class="block h-full rounded-full" :style="{ width: share(row.usd, kindMax), background: `var(--spend-${row.key})` }" />
              </span>
              <span class="w-36 shrink-0 text-right text-xs tabular-nums muted">{{ countText(row) }}</span>
            </span>
          </button>
        </li>
      </ul>
    </section>

    <!-- Which models / which actions cost the most. -->
    <section class="card p-4">
      <header class="mb-3 flex items-center gap-2">
        <h2 class="text-sm font-semibold">{{ tab === 'model' ? t('spend.breakdown.byModel') : t('spend.breakdown.byPurpose') }}</h2>
        <div class="ml-auto inline-flex rounded-button border border-slate-200 p-0.5 dark:border-slate-700" role="tablist">
          <button
            v-for="v in ['model', 'purpose']"
            :key="v"
            type="button"
            role="tab"
            :aria-selected="tab === v"
            class="rounded-[6px] px-2 py-0.5 text-xs"
            :class="tab === v ? 'bg-slate-100 font-medium dark:bg-slate-700' : 'muted hover:text-slate-700 dark:hover:text-slate-200'"
            @click="tab = v"
          >
            {{ v === 'model' ? t('spend.breakdown.models') : t('spend.breakdown.purposes') }}
          </button>
        </div>
      </header>
      <p v-if="!rows.length" class="py-4 text-sm muted">{{ t('spend.breakdown.empty') }}</p>
      <ul v-else class="space-y-2.5">
        <li v-for="row in visibleRows" :key="row.key ?? 'none'">
          <button
            type="button"
            class="group w-full text-left disabled:cursor-default"
            :disabled="!row.key"
            :title="row.key ? t('spend.breakdown.pick') : undefined"
            @click="row.key && $emit('pick', { field: tab, value: row.key })"
          >
            <span class="flex items-baseline gap-2 text-sm">
              <span class="min-w-0 flex-1 truncate" :class="row.key && 'group-hover:underline'">{{ rowName(row) }}</span>
              <span class="font-semibold tabular-nums">{{ formatUsd(row.usd, { approx: true }) }}</span>
            </span>
            <span class="mt-1 flex items-center gap-2">
              <span class="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-700">
                <span class="block h-full rounded-full bg-slate-400 dark:bg-slate-400" :style="{ width: share(row.usd, rowMax) }" />
              </span>
              <span class="w-36 shrink-0 text-right text-xs tabular-nums muted">{{ countText(row) }}</span>
            </span>
          </button>
        </li>
      </ul>
      <button v-if="rows.length > LIMIT" type="button" class="btn-ghost btn-sm mt-2" @click="expanded = !expanded">
        {{ expanded ? t('spend.breakdown.less') : t('spend.breakdown.more', { n: rows.length - LIMIT }) }}
      </button>
    </section>
  </div>
</template>

<script setup>
import { formatUsd } from '~/utils/format.js'
import { spendLabel } from '~/composables/useSpend.js'

const props = defineProps({
  stats: { type: Object, required: true },
})
defineEmits(['pick'])
const { t, te } = useI18n()

const LIMIT = 8
const tab = ref('model')
const expanded = ref(false)

const kinds = computed(() => props.stats.by_kind || [])
const rows = computed(() => (tab.value === 'model' ? props.stats.by_model : props.stats.by_purpose) || [])
const visibleRows = computed(() => (expanded.value ? rows.value : rows.value.slice(0, LIMIT)))
const kindMax = computed(() => Math.max(0, ...kinds.value.map((r) => r.usd)))
const rowMax = computed(() => Math.max(0, ...rows.value.map((r) => r.usd)))

const share = (usd, max) => `${max > 0 ? Math.max(usd > 0 ? 1 : 0, (usd / max) * 100) : 0}%`
const rowName = (row) => {
  if (tab.value === 'purpose') return spendLabel(t, te, 'purposes', row.key)
  if (!row.key) return t('spend.breakdown.noModel')
  return row.title || row.key
}
const countText = (row) => {
  const calls = t('spend.breakdown.calls', { n: row.calls }, row.calls)
  return row.failed ? `${calls} · ${t('spend.breakdown.failed', { n: row.failed }, row.failed)}` : calls
}
</script>
