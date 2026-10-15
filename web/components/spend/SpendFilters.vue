<template>
  <!-- One row above everything it scopes: chart, breakdowns and table follow the same slice. -->
  <div class="flex flex-wrap items-end gap-2">
    <div class="w-full sm:w-auto">
      <label class="label" for="spend-period">{{ t('spend.filters.period') }}</label>
      <select id="spend-period" class="input sm:w-44" :value="modelValue.period" @change="setPeriod($event.target.value)">
        <option v-for="p in SPEND_PERIODS" :key="p" :value="p">{{ t(`spend.periods.${p}`) }}</option>
      </select>
    </div>
    <template v-if="modelValue.period === 'custom'">
      <div class="w-[calc(50%-0.25rem)] sm:w-auto">
        <label class="label" for="spend-from">{{ t('spend.filters.from') }}</label>
        <input id="spend-from" type="date" class="input sm:w-40" :value="modelValue.from" :max="modelValue.to || undefined" @change="set('from', $event.target.value)">
      </div>
      <div class="w-[calc(50%-0.25rem)] sm:w-auto">
        <label class="label" for="spend-to">{{ t('spend.filters.to') }}</label>
        <input id="spend-to" type="date" class="input sm:w-40" :value="modelValue.to" :min="modelValue.from || undefined" @change="set('to', $event.target.value)">
      </div>
    </template>

    <div class="w-[calc(50%-0.25rem)] sm:w-auto">
      <label class="label" for="spend-kind">{{ t('spend.filters.kind') }}</label>
      <select id="spend-kind" class="input sm:w-36" :value="modelValue.kind" @change="set('kind', $event.target.value)">
        <option value="">{{ t('spend.filters.any') }}</option>
        <option v-for="k in kindOptions" :key="k" :value="k">{{ spendLabel(t, te, 'kinds', k) }}</option>
      </select>
    </div>
    <div class="w-[calc(50%-0.25rem)] sm:w-auto">
      <label class="label" for="spend-status">{{ t('spend.filters.status') }}</label>
      <select id="spend-status" class="input sm:w-40" :value="modelValue.status" @change="set('status', $event.target.value)">
        <option value="">{{ t('spend.filters.any') }}</option>
        <option v-for="s in statusOptions" :key="s" :value="s">{{ spendLabel(t, te, 'statuses', s) }}</option>
      </select>
    </div>
    <div class="w-full sm:w-auto">
      <label class="label" for="spend-model">{{ t('spend.filters.model') }}</label>
      <select id="spend-model" class="input sm:w-56" :value="modelValue.model" @change="set('model', $event.target.value)">
        <option value="">{{ t('spend.filters.anyModel') }}</option>
        <option v-for="m in modelOptions" :key="m.id" :value="m.id">{{ m.title || m.id }}</option>
      </select>
    </div>
    <div class="w-full sm:w-auto">
      <label class="label" for="spend-purpose">{{ t('spend.filters.purpose') }}</label>
      <select id="spend-purpose" class="input sm:w-48" :value="modelValue.purpose" @change="set('purpose', $event.target.value)">
        <option value="">{{ t('spend.filters.any') }}</option>
        <option v-for="p in purposeOptions" :key="p" :value="p">{{ spendLabel(t, te, 'purposes', p) }}</option>
      </select>
    </div>

    <div class="flex items-center gap-3 pb-2 sm:ml-1">
      <ToggleSwitch
        v-if="showStub"
        :model-value="modelValue.stub"
        :label="t('spend.filters.stub')"
        @update:model-value="set('stub', $event)"
      />
      <button v-if="dirty" type="button" class="btn-ghost btn-sm" @click="reset">{{ t('spend.filters.reset') }}</button>
    </div>

    <!-- Narrowed to one object (from a link on another screen or in a call card). -->
    <div v-if="modelValue.refType" class="w-full">
      <span class="badge bg-primary/10 text-primary-dark dark:bg-primary/20 dark:text-primary-light">
        {{ t('spend.filters.refChip', { what: refName }) }}
        <button type="button" class="-mr-1 rounded-full p-0.5 hover:bg-primary/20" :aria-label="t('spend.filters.refClear')" @click="clearRef">
          <AppIcon name="close" :size="12" />
        </button>
      </span>
    </div>
  </div>
</template>

<script setup>
import {
  SPEND_KINDS, SPEND_PERIODS, SPEND_STATUSES, spendDefaultFilters, spendLabel, spendPeriodRange,
} from '~/composables/useSpend.js'

const props = defineProps({
  modelValue: { type: Object, required: true },
  choices: { type: Object, default: () => ({}) },
  showStub: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue'])
const { t, te } = useI18n()

const update = (patch) => emit('update:modelValue', { ...props.modelValue, ...patch, page: 1 })
const set = (key, value) => update({ [key]: value })
const setPeriod = (period) => {
  const patch = { period }
  // Switching to "custom" starts from the range that was on screen.
  if (period === 'custom' && !props.modelValue.from && !props.modelValue.to) {
    const range = spendPeriodRange(props.modelValue.period)
    patch.from = range.from || ''
    patch.to = range.to || ''
  }
  update(patch)
}
const clearRef = () => update({ refType: '', refId: null })
const reset = () => emit('update:modelValue', { ...spendDefaultFilters(), stub: props.modelValue.stub })

const withCurrent = (list, current) => (current && !list.includes(current) ? [...list, current] : list)
// Kinds are the chart groups; "other" covers token / model-list calls.
const kindOptions = computed(() => withCurrent(SPEND_KINDS, props.modelValue.kind))
const statusOptions = computed(() => {
  const seen = props.choices.statuses || []
  return withCurrent([...SPEND_STATUSES.filter((s) => seen.includes(s)), ...seen.filter((s) => !SPEND_STATUSES.includes(s))], props.modelValue.status)
})
const modelOptions = computed(() => {
  const list = props.choices.models || []
  const cur = props.modelValue.model
  return cur && !list.some((m) => m.id === cur) ? [...list, { id: cur, title: null }] : list
})
const purposeOptions = computed(() => withCurrent(props.choices.purposes || [], props.modelValue.purpose))

const dirty = computed(() => {
  const f = props.modelValue
  const d = spendDefaultFilters()
  return f.period !== d.period || Boolean(f.kind || f.status || f.model || f.purpose || f.refType)
})
const refName = computed(() => {
  const f = props.modelValue
  const type = spendLabel(t, te, 'refTypes', f.refType)
  return f.refId === null || f.refId === undefined ? type : `${type} #${f.refId}`
})
</script>
