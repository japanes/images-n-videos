<template>
  <ModalShell :open="open" :title="t('jobsPage.settings.title')" @close="$emit('close')">
    <form id="jobs-settings" class="space-y-5" @submit.prevent="save">
      <fieldset>
        <legend class="text-sm font-semibold">{{ t('jobsPage.settings.limitsTitle') }}</legend>
        <p class="mt-1 text-xs muted">{{ t('jobsPage.settings.limitsHint') }}</p>
        <div class="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
          <label v-for="g in limitGroups" :key="g.setting" class="block">
            <span class="label">{{ groupLabel(g.group) }}</span>
            <input v-model.number="form[g.setting]" type="number" class="input" min="1" max="8" step="1" required>
          </label>
        </div>
      </fieldset>

      <fieldset class="space-y-3">
        <legend class="text-sm font-semibold">{{ t('jobsPage.settings.upkeepTitle') }}</legend>
        <label class="block">
          <span class="label">{{ t('jobsPage.settings.stuckMinutes') }}</span>
          <input v-model.number="form['jobs.stuck_minutes']" type="number" class="input" min="0" max="1440" step="1" required>
          <span class="mt-1 block text-xs muted">{{ t('jobsPage.settings.stuckHint') }}</span>
        </label>
        <label class="block">
          <span class="label">{{ t('jobsPage.settings.keepDays') }}</span>
          <input v-model.number="form['jobs.keep_days']" type="number" class="input" min="0" max="3650" step="1" required>
          <span class="mt-1 block text-xs muted">{{ t('jobsPage.settings.keepHint') }}</span>
        </label>
        <ToggleSwitch v-model="form['jobs.backup_daily']" :label="t('jobsPage.settings.backupDaily')" />
        <label class="block">
          <span class="label">{{ t('jobsPage.settings.backupKeep') }}</span>
          <input
            v-model.number="form['jobs.backup_keep']"
            type="number"
            class="input"
            min="1"
            max="60"
            step="1"
            required
            :disabled="!form['jobs.backup_daily']"
          >
          <span class="mt-1 block text-xs muted">{{ t('jobsPage.settings.backupHint') }}</span>
        </label>
      </fieldset>
      <p v-if="error" class="text-sm text-rose-700 dark:text-rose-300">{{ error }}</p>
    </form>
    <template #footer>
      <button type="button" class="btn-ghost" @click="$emit('close')">{{ t('common.cancel') }}</button>
      <button type="submit" form="jobs-settings" class="btn-primary" :disabled="saving || !changed">
        <Spinner v-if="saving" :size="14" />{{ t('common.save') }}
      </button>
    </template>
  </ModalShell>
</template>

<script setup>
import { apiErrorText } from '~/utils/apiErrorText.js'
import { KNOWN_GROUPS } from '~/utils/jobsView.js'

const props = defineProps({
  open: { type: Boolean, default: false },
  groups: { type: Array, default: () => [] },
  settings: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['close', 'saved'])

const { t, te } = useI18n()
const api = useApi()
const toast = useToast()

const form = ref({})
const initial = ref({})
const saving = ref(false)
const error = ref('')

// Only groups with a declared setting (the core's); "default" is a catch-all.
const limitGroups = computed(() => props.groups.filter((g) => KNOWN_GROUPS.includes(g.group) && g.group !== 'default'))
const groupLabel = (name) => t(`jobsPage.groups.${name}`)

function reset() {
  const values = { ...props.settings }
  for (const g of limitGroups.value) values[g.setting] = g.limit
  form.value = { ...values }
  initial.value = { ...values }
  error.value = ''
}
watch(() => props.open, (v) => { if (v) reset() }, { immediate: true })

const changedKeys = computed(() => Object.keys(form.value).filter((k) => form.value[k] !== initial.value[k]))
const changed = computed(() => changedKeys.value.length > 0)

async function save() {
  if (!changed.value) return
  saving.value = true
  error.value = ''
  try {
    const body = Object.fromEntries(changedKeys.value.map((k) => [k, form.value[k]]))
    await api.put('/api/settings', body)
    toast.success(t('common.saved'))
    emit('saved')
    emit('close')
  } catch (err) {
    error.value = apiErrorText(err, t, te)
  } finally {
    saving.value = false
  }
}
</script>
