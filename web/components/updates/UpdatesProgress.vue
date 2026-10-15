<template>
  <section class="card space-y-3 p-5" aria-live="polite">
    <div class="flex items-start gap-3">
      <span class="grid h-10 w-10 shrink-0 place-items-center rounded-xl" :class="iconTone">
        <Spinner v-if="operation.active" :size="20" />
        <AppIcon v-else :name="operation.result === 'success' ? 'check' : 'alert'" :size="20" />
      </span>
      <div class="min-w-0 flex-1 space-y-1">
        <h2 class="text-base font-semibold">{{ heading }}</h2>
        <p class="text-sm muted">
          {{ t(stateKey(operation.state)) }}
          <template v-if="operation.started_at"> · {{ t('updates.progress.startedAt', { at: formatDateTime(operation.started_at, locale) }) }}</template>
          <template v-if="operation.source"> · {{ t(sourceKey(operation.source)) }}</template>
        </p>
      </div>
      <span v-if="!operation.active && operation.result" class="badge" :class="resultTone(operation.result)">
        {{ t(resultKey(operation.result)) }}
      </span>
    </div>

    <p v-if="operation.active" class="text-sm muted">{{ t('updates.progress.restartNote') }}</p>

    <!-- Waiting for running jobs: the human can stop waiting. -->
    <div
      v-if="waiting"
      class="space-y-2 rounded-card bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:bg-amber-500/10 dark:text-amber-100"
    >
      <p>{{ t('updates.progress.waiting', { n: operation.busy.length }, operation.busy.length) }}</p>
      <ul class="list-disc space-y-0.5 pl-5">
        <li v-for="(b, i) in operation.busy" :key="i" class="break-words">{{ b.title || b.kind }}</li>
      </ul>
      <div class="flex flex-wrap items-center gap-3 pt-1">
        <button type="button" class="btn-danger btn-sm" :disabled="forcing" @click="$emit('force')">
          {{ t('updates.force.button') }}
        </button>
        <span class="text-xs">{{ t('updates.force.hint') }}</span>
      </div>
    </div>
    <p v-else-if="operation.active && operation.force && operation.state === 'preparing'" class="text-sm muted">
      {{ t('updates.force.requested') }}
    </p>

    <p
      v-if="operation.error"
      class="flex gap-2 rounded-card bg-rose-50 px-3 py-2 text-sm text-rose-800 dark:bg-rose-500/10 dark:text-rose-200"
    >
      <AppIcon name="alert" :size="16" class="mt-0.5 shrink-0" />
      <span class="min-w-0 break-words">{{ operation.error }}</span>
    </p>

    <p v-if="operation.backup_file" class="text-xs muted">{{ t('updates.backupFile', { file: operation.backup_file }) }}</p>

    <details v-if="stepLog.length" :open="operation.active">
      <summary class="cursor-pointer text-sm text-primary">{{ t('updates.progress.steps') }}</summary>
      <ol class="mt-2 space-y-1 font-mono text-xs">
        <li v-for="(s, i) in stepLog" :key="i" class="flex gap-3">
          <span class="shrink-0 muted">{{ shortTime(s.at) }}</span>
          <span class="min-w-0 break-words">{{ s.message }}</span>
        </li>
      </ol>
    </details>
  </section>
</template>

<script setup>
import { formatDateTime, parseTs } from '~/utils/format.js'
import { canForce, resultKey, resultTone, sourceKey, stateKey } from '~/utils/updatesView.js'

const props = defineProps({
  operation: { type: Object, required: true },
  stepLog: { type: Array, default: () => [] },
  forcing: { type: Boolean, default: false },
})
defineEmits(['force'])
const { t, locale } = useI18n()

const waiting = computed(() => canForce(props.operation))

const heading = computed(() => {
  const op = props.operation
  if (op.active) return t('updates.progress.updating', { version: op.to || '—' })
  if (op.result === 'success') return t('updates.progress.updated', { version: op.to || '—' })
  if (op.result === 'rolled_back') return t('updates.progress.rolledBack', { version: op.to || '—', from: op.from || '—' })
  return t('updates.progress.failed', { version: op.to || '—' })
})

const iconTone = computed(() => {
  const op = props.operation
  if (op.active) return 'bg-primary/10 text-primary'
  if (op.result === 'success') return 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300'
  return 'bg-rose-100 text-rose-600 dark:bg-rose-500/15 dark:text-rose-400'
})

function shortTime(ts) {
  const d = parseTs(ts)
  return d ? d.toLocaleTimeString(locale.value, { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : ''
}
</script>
