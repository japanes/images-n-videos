<template>
  <ol class="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
    <li v-for="(step, i) in WIZARD_STEPS" :key="step" class="flex items-center gap-2">
      <span
        class="flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-semibold"
        :class="i < current
          ? 'bg-emerald-500 text-white'
          : i === current ? 'bg-primary text-white' : 'bg-slate-200 text-slate-500 dark:bg-slate-700 dark:text-slate-400'"
      >
        <AppIcon v-if="i < current" name="check" :size="11" />
        <template v-else>{{ i + 1 }}</template>
      </span>
      <span :class="i === current ? 'font-medium' : 'muted'" :aria-current="i === current ? 'step' : undefined">
        {{ t(`connection.wizard.steps.${step}`) }}
      </span>
      <AppIcon v-if="i < WIZARD_STEPS.length - 1" name="chevron-right" :size="12" class="text-slate-300 dark:text-slate-600" />
    </li>
  </ol>
</template>

<script setup>
// Where the user is in the first-run wizard.
import { WIZARD_STEPS, wizardIndex } from '~/utils/connectionView.js'

const props = defineProps({
  step: { type: String, required: true },
})

const { t } = useI18n()
const current = computed(() => wizardIndex(props.step))
</script>
