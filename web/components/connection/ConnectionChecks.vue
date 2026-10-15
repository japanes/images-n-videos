<template>
  <section class="card p-4">
    <div class="flex flex-wrap items-center gap-2">
      <h2 class="flex-1 text-sm font-semibold">{{ t('connection.checks.title') }}</h2>
      <PriceButton
        :label="ran ? t('connection.checks.rerun') : t('connection.checks.run')"
        icon="refresh"
        :variant="ran ? 'secondary' : 'primary'"
        :estimate="estimate"
        :busy="busy === 'check'"
        :disabled="!!busy || !state?.key"
        @click="$emit('check')"
      />
    </div>
    <p class="mt-1 text-xs muted">{{ t('connection.checks.hint') }}</p>
    <p v-if="state?.stub" class="mt-1 text-xs text-primary">{{ t('connection.stubNote') }}</p>

    <ul class="mt-3 divide-y divide-slate-100 dark:divide-slate-700/60">
      <li v-for="row in rows" :key="row.name" class="py-2">
        <div class="flex items-center gap-2 text-sm">
          <span class="flex h-5 w-5 shrink-0 items-center justify-center rounded-full" :class="DOT[row.status]">
            <AppIcon v-if="row.status === 'ok'" name="check" :size="12" />
            <AppIcon v-else-if="row.status === 'error'" name="close" :size="12" />
          </span>
          <span class="min-w-0 flex-1">{{ t(`connection.checks.names.${row.name}`) }}</span>
          <span v-if="row.result?.cost_usd" class="text-xs tabular-nums muted">{{ formatUsd(row.result.cost_usd) }}</span>
          <span class="text-xs muted" :title="row.result?.at ? formatDateTime(row.result.at, locale) : undefined">
            {{ t(`connection.checks.status.${row.status}`) }}
          </span>
        </div>
        <p v-if="row.name === 'models' && row.status === 'ok'" class="mt-1 pl-7 text-xs muted">
          {{ t('connection.checks.listed', { count: row.result.count ?? 0, region: row.result.region || state.list_region }) }}
        </p>
        <p v-if="row.status === 'skipped'" class="mt-1 pl-7 text-xs muted">{{ t('connection.checks.skippedHint') }}</p>
        <ConnectionErrorHelp
          v-if="row.status === 'error'"
          class="ml-7 mt-1.5"
          :error="row.result.error"
          :project-id="state?.key?.project_id || ''"
          @step="$emit('step', $event)"
        />
      </li>
    </ul>
  </section>
</template>

<script setup>
// The check list: token, list of models, test text (+ picture and Omni once tried).
import { formatDateTime, formatUsd } from '~/utils/format.js'
import { CHECK_NAMES, checkStatus } from '~/utils/connectionView.js'

const props = defineProps({
  state: { type: Object, default: null },
  busy: { type: String, default: '' },
})
defineEmits(['check', 'step'])

const { t, locale } = useI18n()

const DOT = {
  ok: 'bg-emerald-500 text-white',
  error: 'bg-rose-500 text-white',
  skipped: 'bg-slate-200 dark:bg-slate-600',
  none: 'border border-slate-300 dark:border-slate-600',
}

const ran = computed(() => !!props.state?.last_check_at)
const textModel = computed(() => (props.state?.capabilities || []).find((c) => c.id === 'text')?.model_id || undefined)
const estimate = computed(() => ({ kind: 'text', model_id: textModel.value, purpose: 'connection_check' }))

// Picture and Omni rows appear once they were tried: they have their own buttons.
const rows = computed(() => CHECK_NAMES
  .map((name) => ({ name, result: props.state?.checks?.[name] || null }))
  .filter((r) => ['token', 'models', 'text'].includes(r.name) || r.result)
  .map((r) => ({ ...r, status: checkStatus(r.result) })))
</script>
