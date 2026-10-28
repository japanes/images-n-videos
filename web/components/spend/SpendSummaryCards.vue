<template>
  <div class="grid gap-3 md:grid-cols-3">
    <!-- Spent of the trial credit: the one big number of the screen. -->
    <section class="card p-4 md:col-span-2">
      <h2 class="text-sm font-medium muted">{{ t('spend.summary.spentLabel') }}</h2>
      <p class="mt-1 flex flex-wrap items-baseline gap-x-2">
        <span class="text-4xl font-semibold text-slate-900 dark:text-white">{{ formatUsd(s.spent_usd, { approx: true }) }}</span>
        <span class="text-base muted">{{ t('spend.summary.ofCredit', { credit: formatUsd(s.credit_usd, { digits: 0 }) }) }}</span>
      </p>
      <div
        class="mt-3 h-2 overflow-hidden rounded-full"
        :class="trackClass"
        role="meter"
        :aria-valuenow="Math.round(s.spent_pct || 0)"
        aria-valuemin="0"
        aria-valuemax="100"
        :aria-label="t('spend.summary.spentLabel')"
      >
        <div class="h-full rounded-full transition-[width]" :class="fillClass" :style="{ width: `${barPct}%` }" />
      </div>
      <p class="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
        <span v-if="s.over_usd > 0" class="inline-flex items-center gap-1 font-medium text-rose-600 dark:text-rose-400">
          <AppIcon name="alert" :size="16" />
          {{ t('spend.summary.over', { usd: formatUsd(s.over_usd, { approx: true }) }) }}
        </span>
        <span v-else class="font-medium">{{ t('spend.summary.remaining', { usd: formatUsd(s.remaining_usd, { approx: true }) }) }}</span>
        <span v-if="s.spent_pct !== null && s.spent_pct !== undefined" class="muted">
          {{ t('spend.summary.pct', { pct: pctText }) }}
        </span>
      </p>
      <p v-if="s.spent_before_trial_usd > 0" class="mt-1 text-xs muted">
        {{ t('spend.summary.beforeTrial', { usd: formatUsd(s.spent_before_trial_usd, { approx: true }), date: formatDay(s.trial_started_on) }) }}
      </p>
    </section>

    <div class="grid gap-3">
      <!-- Days until the credit expires. -->
      <section class="card p-4">
        <h2 class="text-sm font-medium muted">{{ t('spend.summary.daysLabel') }}</h2>
        <template v-if="s.trial_started_on">
          <p v-if="s.expired" class="mt-1 text-2xl font-semibold text-rose-600 dark:text-rose-400">{{ t('spend.summary.expired') }}</p>
          <p v-else class="mt-1 text-2xl font-semibold">{{ t('spend.summary.days', { n: s.days_left }, s.days_left) }}</p>
          <p class="mt-1 text-xs muted">
            {{ t(s.expired ? 'spend.summary.expiredOn' : 'spend.summary.until', { date: formatDay(s.trial_ends_on) }) }}
          </p>
        </template>
        <template v-else>
          <p class="mt-1 text-2xl font-semibold muted">—</p>
          <p class="mt-1 text-xs muted">
            {{ t('spend.summary.noTrialDate') }}
            <NuxtLink to="/settings/connection" class="text-primary hover:underline">{{ t('spend.summary.setTrialDate') }}</NuxtLink>
          </p>
        </template>
      </section>

      <!-- Today and the daily limit. -->
      <section class="card p-4">
        <h2 class="text-sm font-medium muted">{{ t('spend.summary.todayLabel') }}</h2>
        <p class="mt-1 text-2xl font-semibold">{{ formatUsd(s.spent_today_usd, { approx: true }) }}</p>
        <p v-if="s.daily_cap_usd > 0" class="mt-1 text-xs" :class="capReached ? 'font-medium text-rose-600 dark:text-rose-400' : 'muted'">
          <AppIcon v-if="capReached" name="alert" :size="14" class="mr-0.5 inline align-[-2px]" />
          {{ t(capReached ? 'spend.summary.capReached' : 'spend.summary.cap', { usd: formatUsd(s.daily_cap_usd), time: resetTime }) }}
        </p>
        <p v-else class="mt-1 text-xs muted">
          {{ t('spend.summary.noCap') }}
          <button type="button" class="text-primary hover:underline" @click="$emit('settings')">{{ t('spend.summary.setCap') }}</button>
        </p>
      </section>
    </div>
  </div>
</template>

<script setup>
import { formatUsd, parseTs } from '~/utils/format.js'
import { spendMeterTone, spendParseDay } from '~/composables/useSpend.js'

const props = defineProps({
  summary: { type: Object, required: true },
})
defineEmits(['settings'])

const { t, locale } = useI18n()
const s = computed(() => props.summary)

const barPct = computed(() => Math.min(100, Math.max(0, Number(s.value.spent_pct) || 0)))
const pctText = computed(() => {
  const p = Number(s.value.spent_pct) || 0
  return p > 0 && p < 1 ? '<1' : String(Math.round(p))
})
const tone = computed(() => spendMeterTone(s.value.spent_pct))
// The unfilled track is a lighter step of the fill's own hue.
const fillClass = computed(() => ({ ok: 'bg-primary', warn: 'bg-amber-500', over: 'bg-rose-600' }[tone.value]))
const trackClass = computed(() => ({
  ok: 'bg-primary/15',
  warn: 'bg-amber-500/20',
  over: 'bg-rose-600/20',
}[tone.value]))
const capReached = computed(() => s.value.daily_cap_usd > 0 && s.value.spent_today_usd >= s.value.daily_cap_usd)

const formatDay = (day) => {
  const d = spendParseDay(day)
  return d ? d.toLocaleDateString(locale.value, { dateStyle: 'medium' }) : '—'
}
// The daily limit counts a UTC day; show when it resets in the user's time.
const resetTime = computed(() => {
  const d = parseTs(s.value.cap_resets_at)
  return d ? d.toLocaleTimeString(locale.value, { hour: '2-digit', minute: '2-digit' }) : '—'
})
</script>
