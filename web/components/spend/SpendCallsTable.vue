<template>
  <section class="card overflow-hidden">
    <header class="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-slate-200 px-4 py-3 dark:border-slate-700">
      <h2 class="text-sm font-semibold">{{ t('spend.table.title') }}</h2>
      <span class="text-xs muted">
        {{ t('spend.table.summary', { n: total, usd: formatUsd(sumUsd, { approx: true }) }, total) }}
      </span>
    </header>

    <p v-if="!items.length" class="px-4 py-10 text-center text-sm muted">{{ t('spend.table.empty') }}</p>

    <div v-else class="overflow-x-auto">
      <table class="w-full min-w-[720px] text-sm">
        <thead class="text-left text-xs muted">
          <tr>
            <th class="px-4 py-2 font-medium">{{ t('spend.table.time') }}</th>
            <th class="px-2 py-2 font-medium">{{ t('spend.table.what') }}</th>
            <th class="px-2 py-2 font-medium">{{ t('spend.table.model') }}</th>
            <th class="px-2 py-2 font-medium">{{ t('spend.table.units') }}</th>
            <th class="px-2 py-2 font-medium">{{ t('spend.table.status') }}</th>
            <th class="px-4 py-2 text-right font-medium">{{ t('spend.table.cost') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="call in items"
            :key="call.id"
            class="cursor-pointer border-t border-slate-100 align-top outline-none hover:bg-slate-50 focus-visible:bg-slate-50 dark:border-slate-700/70 dark:hover:bg-slate-700/40 dark:focus-visible:bg-slate-700/40"
            tabindex="0"
            :aria-label="t('spend.table.open', { id: call.id })"
            @click="$emit('open', call.id)"
            @keydown.enter.prevent="$emit('open', call.id)"
            @keydown.space.prevent="$emit('open', call.id)"
          >
            <td class="whitespace-nowrap px-4 py-2.5 tabular-nums">
              {{ formatDateTime(call.created_at, locale) }}
            </td>
            <td class="max-w-[22rem] px-2 py-2.5">
              <p class="flex items-center gap-1.5">
                <span class="truncate font-medium">{{ spendLabel(t, te, 'purposes', call.purpose) }}</span>
                <span v-if="call.attempt > 1" class="badge shrink-0 bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300">
                  {{ t('spend.table.attempt', { n: call.attempt }) }}
                </span>
                <span v-if="call.stub" class="badge shrink-0 bg-amber-100 text-amber-800 dark:bg-amber-500/20 dark:text-amber-300" :title="t('spend.table.stubHint')">
                  {{ t('spend.table.stub') }}
                </span>
              </p>
              <p class="truncate text-xs muted">{{ spendLabel(t, te, 'kinds', call.kind) }}</p>
              <p v-if="call.error_text" class="mt-0.5 line-clamp-2 break-words text-xs text-rose-600 dark:text-rose-400" :title="call.error_text">
                {{ call.error_text }}
              </p>
            </td>
            <td class="max-w-[14rem] px-2 py-2.5">
              <p class="truncate" :title="call.model_id || ''">{{ call.model_title || call.model_id || '—' }}</p>
              <p v-if="call.model_title && call.model_id" class="truncate font-mono text-[11px] muted">{{ call.model_id }}</p>
            </td>
            <td class="px-2 py-2.5 text-xs tabular-nums muted">
              <p v-for="(part, i) in spendUnitParts(call)" :key="i" class="whitespace-nowrap">{{ t(part[0], part[1]) }}</p>
              <p v-if="!spendUnitParts(call).length">—</p>
            </td>
            <td class="px-2 py-2.5">
              <span class="badge whitespace-nowrap" :class="statusTone(call.status)">
                <Spinner v-if="call.status === 'running'" :size="11" />
                {{ spendLabel(t, te, 'statuses', call.status) }}
              </span>
            </td>
            <td class="whitespace-nowrap px-4 py-2.5 text-right font-medium tabular-nums">
              {{ call.status === 'running' && !call.cost_usd ? '…' : formatUsd(call.cost_usd) }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <footer v-if="total > pageSize" class="flex items-center justify-between gap-2 border-t border-slate-200 px-4 py-2 text-xs dark:border-slate-700">
      <span class="tabular-nums muted">{{ t('spend.table.range', { from: rangeFrom, to: rangeTo, n: total }) }}</span>
      <span class="flex gap-1">
        <button type="button" class="btn-ghost btn-sm" :disabled="page <= 1" @click="$emit('page', page - 1)">
          <AppIcon name="chevron-left" :size="14" />{{ t('spend.table.prev') }}
        </button>
        <button type="button" class="btn-ghost btn-sm" :disabled="rangeTo >= total" @click="$emit('page', page + 1)">
          {{ t('spend.table.next') }}<AppIcon name="chevron-right" :size="14" />
        </button>
      </span>
    </footer>
  </section>
</template>

<script setup>
import { formatDateTime, formatUsd } from '~/utils/format.js'
import { SPEND_PAGE_SIZE, spendLabel, spendUnitParts } from '~/composables/useSpend.js'

const props = defineProps({
  items: { type: Array, default: () => [] },
  total: { type: Number, default: 0 },
  sumUsd: { type: Number, default: 0 },
  page: { type: Number, default: 1 },
  pageSize: { type: Number, default: SPEND_PAGE_SIZE },
})
defineEmits(['open', 'page'])
const { t, te, locale } = useI18n()

const rangeFrom = computed(() => (props.total ? (props.page - 1) * props.pageSize + 1 : 0))
const rangeTo = computed(() => Math.min(props.total, props.page * props.pageSize))

// Status is never colour alone: the badge always carries its word.
const statusTone = (status) => ({
  success: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-500/20 dark:text-emerald-300',
  error: 'bg-rose-100 text-rose-700 dark:bg-rose-500/20 dark:text-rose-300',
  blocked: 'bg-amber-100 text-amber-800 dark:bg-amber-500/20 dark:text-amber-300',
  running: 'bg-primary/10 text-primary-dark dark:bg-primary/20 dark:text-primary-light',
}[status] || 'bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300')
</script>
