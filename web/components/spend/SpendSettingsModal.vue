<template>
  <ModalShell :open="open" size="md" :title="t('spend.settings.title')" @close="$emit('close')">
    <div v-if="loading" class="flex justify-center py-10"><Spinner :size="22" /></div>
    <p v-else-if="loadError" class="text-sm text-rose-600 dark:text-rose-400">{{ loadError }}</p>

    <form v-else id="spend-settings" class="space-y-5" @submit.prevent="save">
      <div v-for="f in FIELDS" :key="f.key">
        <label class="label" :for="`spend-set-${f.key}`">{{ t(f.label) }}</label>
        <div class="flex items-center gap-2">
          <span v-if="f.unit === 'usd'" class="text-sm muted">$</span>
          <input
            :id="`spend-set-${f.key}`"
            v-model="form[f.key]"
            type="number"
            inputmode="decimal"
            class="input w-36 tabular-nums"
            :min="meta[f.key]?.min ?? 0"
            :max="meta[f.key]?.max ?? undefined"
            :step="f.unit === 'usd' ? '0.01' : '1'"
            required
          >
          <span v-if="f.unit === 'days'" class="text-sm muted">{{ t('spend.settings.daysUnit') }}</span>
          <button
            v-if="meta[f.key] && String(form[f.key]) !== String(meta[f.key].default)"
            type="button"
            class="btn-ghost btn-sm"
            @click="form[f.key] = meta[f.key].default"
          >
            {{ t('spend.settings.useDefault', { value: f.unit === 'usd' ? formatUsd(meta[f.key].default) : meta[f.key].default }) }}
          </button>
        </div>
        <p class="mt-1 text-xs muted">{{ t(f.hint, { time: resetTime }) }}</p>
      </div>

      <p class="rounded-button bg-slate-50 px-3 py-2 text-xs muted dark:bg-slate-900">
        {{ t('spend.settings.trialDateHint') }}
        <NuxtLink to="/settings/connection" class="text-primary hover:underline" @click="$emit('close')">{{ t('spend.summary.setTrialDate') }}</NuxtLink>
      </p>
      <p v-if="saveError" class="text-sm text-rose-600 dark:text-rose-400">{{ saveError }}</p>
    </form>

    <template #footer>
      <button type="button" class="btn-secondary" @click="$emit('close')">{{ t('common.cancel') }}</button>
      <button type="submit" form="spend-settings" class="btn-primary" :disabled="saving || loading || !!loadError">
        <Spinner v-if="saving" :size="14" />{{ t('common.save') }}
      </button>
    </template>
  </ModalShell>
</template>

<script setup>
import { formatUsd, parseTs } from '~/utils/format.js'
import { apiErrorText } from '~/utils/apiErrorText.js'

const props = defineProps({
  open: { type: Boolean, default: false },
  /** summary.cap_resets_at: when the daily limit starts over (UTC midnight) */
  capResetsAt: { type: String, default: '' },
})
const emit = defineEmits(['close', 'saved'])

const FIELDS = [
  { key: 'spend.credit_usd', unit: 'usd', label: 'spend.settings.credit', hint: 'spend.settings.creditHint' },
  { key: 'spend.credit_days', unit: 'days', label: 'spend.settings.creditDays', hint: 'spend.settings.creditDaysHint' },
  { key: 'google.daily_cap_usd', unit: 'usd', label: 'spend.settings.dailyCap', hint: 'spend.settings.dailyCapHint' },
]

const { t, te, locale } = useI18n()
const api = useApi()
const toast = useToast()

const loading = ref(false)
const saving = ref(false)
const loadError = ref('')
const saveError = ref('')
const meta = ref({})
const form = reactive({})

async function load() {
  loading.value = true
  loadError.value = ''
  saveError.value = ''
  try {
    const res = await api.get('/api/settings')
    const items = Object.fromEntries((res.items || []).map((i) => [i.key, i]))
    meta.value = items
    for (const f of FIELDS) form[f.key] = items[f.key]?.value ?? items[f.key]?.default ?? 0
  } catch (err) {
    loadError.value = apiErrorText(err, t, te)
  } finally {
    loading.value = false
  }
}
watch(() => props.open, (v) => { if (v) load() }, { immediate: true })

async function save() {
  saving.value = true
  saveError.value = ''
  const body = {}
  for (const f of FIELDS) {
    const v = Number(form[f.key])
    if (!Number.isFinite(v)) { saving.value = false; return }
    const before = meta.value[f.key]?.value
    if (v !== Number(before)) body[f.key] = f.unit === 'days' ? Math.round(v) : v
  }
  try {
    if (Object.keys(body).length) await api.put('/api/settings', body)
    toast.success(t('common.saved'))
    emit('saved')
    emit('close')
  } catch (err) {
    saveError.value = apiErrorText(err, t, te)
  } finally {
    saving.value = false
  }
}

const resetTime = computed(() => {
  const d = parseTs(props.capResetsAt)
  return d ? d.toLocaleTimeString(locale.value, { hour: '2-digit', minute: '2-digit' }) : '—'
})
</script>
