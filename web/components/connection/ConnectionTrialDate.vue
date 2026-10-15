<template>
  <div>
    <p v-if="showText" class="text-sm muted">{{ t('connection.trial.text') }}</p>
    <form class="mt-3 flex flex-wrap items-end gap-2" @submit.prevent="save">
      <label class="min-w-[10rem] flex-1">
        <span class="label">{{ t('connection.trial.label') }}</span>
        <input v-model="day" type="date" class="input" :max="today" :aria-invalid="invalid ? 'true' : undefined">
      </label>
      <button type="submit" class="btn-primary btn-sm h-9" :disabled="busy || !changed">
        <Spinner v-if="busy" :size="14" />
        {{ t('connection.trial.save') }}
      </button>
      <button v-if="trial?.started_on" type="button" class="btn-ghost btn-sm h-9" :disabled="busy" @click="clear">
        {{ t('connection.trial.clear') }}
      </button>
    </form>
    <p v-if="invalid" class="mt-1 text-xs text-rose-600 dark:text-rose-400">{{ t('connection.trial.invalid') }}</p>

    <div v-if="trial?.started_on" class="mt-3 text-sm">
      <template v-if="trial.days_left > 0">
        <p class="font-medium">{{ t('connection.trial.daysLeft', { n: trial.days_left }, trial.days_left) }}</p>
        <p class="text-xs muted">{{ t('connection.trial.ends', { date: dayText(trial.ends_on) }) }}</p>
      </template>
      <p v-else class="font-medium text-amber-700 dark:text-amber-300">{{ t('connection.trial.over') }}</p>
    </div>
  </div>
</template>

<script setup>
// The trial start date: the app counts the days of credit left from it.
import { isValidDay, localDay } from '~/utils/connectionView.js'

const props = defineProps({
  trial: { type: Object, default: null },
  busy: { type: Boolean, default: false },
  showText: { type: Boolean, default: true },
})
const emit = defineEmits(['save'])

const { t, locale } = useI18n()

const today = localDay()
const day = ref(props.trial?.started_on || '')
const invalid = ref(false)

watch(() => props.trial?.started_on, (v) => { day.value = v || ''; invalid.value = false })
watch(day, () => { invalid.value = false })

const changed = computed(() => (day.value || '') !== (props.trial?.started_on || ''))

function save() {
  if (!day.value) return clear()
  if (!isValidDay(day.value, today)) { invalid.value = true; return }
  emit('save', day.value)
}

function clear() {
  emit('save', null)
}

function dayText(value) {
  const [y, m, d] = String(value || '').split('-').map(Number)
  if (!y || !m || !d) return value || ''
  return new Date(y, m - 1, d).toLocaleDateString(locale.value, { dateStyle: 'medium' })
}
</script>
