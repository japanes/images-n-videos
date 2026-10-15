<template>
  <article class="card flex flex-col gap-3 p-4" :class="!model.enabled && 'opacity-80'">
    <header class="flex flex-wrap items-start gap-2">
      <div class="min-w-0 flex-1">
        <h3 class="font-semibold">{{ model.title || model.id }}</h3>
        <p class="mt-0.5 break-all font-mono text-xs muted">{{ model.id }}</p>
        <p v-if="model.region" class="mt-0.5 text-xs muted">{{ t('models.region', { region: model.region }) }}</p>
      </div>
      <div class="flex flex-wrap justify-end gap-1">
        <span v-if="model.is_default" class="badge bg-primary/10 text-primary">{{ t('models.badge.default') }}</span>
        <span v-if="inUse" class="badge bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300">
          <AppIcon name="check" :size="12" />{{ t('models.badge.inUse') }}
        </span>
        <span
          v-if="model.preview"
          class="badge bg-amber-50 text-amber-800 dark:bg-amber-500/10 dark:text-amber-200"
          :title="t('models.badgeHint.preview')"
        >{{ t('models.badge.preview') }}</span>
        <span class="badge" :class="availabilityClass" :title="availability === 'unchecked' ? t('models.badgeHint.unchecked') : ''">
          {{ t(`models.badge.${availability}`) }}
        </span>
        <span v-if="!model.enabled" class="badge bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300">
          {{ t('models.badge.off') }}
        </span>
        <span v-if="model.user_price" class="badge bg-sky-50 text-sky-700 dark:bg-sky-500/10 dark:text-sky-300">
          {{ t('models.badge.userPrice') }}
        </span>
      </div>
    </header>

    <section>
      <h4 class="label">{{ t('models.price.title') }}</h4>
      <ul v-if="priceLines.length" class="space-y-0.5 text-sm">
        <li v-for="(line, i) in priceLines" :key="i" class="tabular-nums">{{ line }}</li>
      </ul>
      <p v-else class="text-sm muted">{{ t('models.price.none') }}</p>
    </section>

    <ul v-if="chips.length" class="flex flex-wrap gap-1">
      <li
        v-for="(chip, i) in chips"
        :key="i"
        class="rounded-badge bg-slate-100 px-2 py-0.5 text-xs text-slate-700 dark:bg-slate-700 dark:text-slate-200"
      >
        {{ chip.raw ?? t(`models.caps.${chip.key}`, chip.params) }}
      </li>
    </ul>

    <footer class="mt-auto flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3 dark:border-slate-700">
      <span :title="model.is_default ? t('models.actions.showDefaultHint') : ''">
        <ToggleSwitch
          :model-value="model.enabled"
          :label="t('models.actions.show')"
          :disabled="model.is_default || busy"
          @update:model-value="$emit('toggle', $event)"
        />
      </span>
      <span class="flex-1" />
      <button
        v-if="!model.is_default"
        type="button"
        class="btn-secondary btn-sm"
        :disabled="busy || model.available === false"
        :title="model.available === false ? t('models.actions.makeDefaultUnavailable') : ''"
        @click="$emit('make-default')"
      >
        {{ t('models.actions.makeDefault') }}
      </button>
      <button type="button" class="btn-ghost btn-sm" :disabled="busy" @click="$emit('edit-price')">
        <AppIcon name="edit" :size="14" />{{ t('models.actions.editPrice') }}
      </button>
    </footer>
  </article>
</template>

<script setup>
import { modelAvailability, modelCapChips, modelPriceLines, priceText } from '~/utils/modelsView.js'

const props = defineProps({
  model: { type: Object, required: true },
  inUse: { type: Boolean, default: false },
  busy: { type: Boolean, default: false },
})
defineEmits(['toggle', 'make-default', 'edit-price'])

const { t } = useI18n()

const availability = computed(() => modelAvailability(props.model))
const availabilityClass = computed(() => ({
  available: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300',
  unavailable: 'bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300',
  unchecked: 'bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300',
}[availability.value]))

const priceLines = computed(() => modelPriceLines(props.model).map((line) => {
  const params = { ...line }
  for (const name of ['input', 'output', 'usd']) {
    if (name in params) params[name] = priceText(params[name])
  }
  return t(`models.price.${line.key}`, params)
}))

const chips = computed(() => modelCapChips(props.model))
</script>
