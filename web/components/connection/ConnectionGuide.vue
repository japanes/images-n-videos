<template>
  <div class="space-y-3">
    <p class="text-sm muted">{{ t('connection.guide.intro') }}</p>
    <ol class="space-y-3">
      <li
        v-for="step in GUIDE_STEPS"
        :id="`connection-step-${step.id}`"
        :key="step.id"
        class="flex gap-3 rounded-card border p-3 transition-colors"
        :class="step.id === highlight
          ? 'border-primary bg-primary/5'
          : 'border-slate-200 dark:border-slate-700'"
      >
        <span
          class="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-slate-100 text-sm font-semibold tabular-nums dark:bg-slate-700"
          :aria-label="t('connection.guide.stepLabel', { n: step.number })"
        >{{ step.number }}</span>
        <div class="min-w-0 flex-1 space-y-1.5">
          <h3 class="text-sm font-semibold">
            {{ t(`connection.guide.steps.${step.id}.title`) }}
            <span v-if="step.optional" class="badge ml-1 bg-slate-100 font-normal muted dark:bg-slate-700">{{ t('connection.guide.optional') }}</span>
          </h3>
          <ConnectionRichText tag="p" class="text-sm text-slate-600 dark:text-slate-300" :text="t(`connection.guide.steps.${step.id}.text`)" />
          <div v-if="step.links.length" class="flex flex-wrap gap-x-4 gap-y-1">
            <ConnectionLink v-for="l in step.links" :id="l" :key="l" :project-id="projectId" />
          </div>
          <template v-if="step.policy">
            <button type="button" class="btn-secondary btn-sm" :aria-expanded="policyOpen" @click="policyOpen = !policyOpen">
              <AppIcon :name="policyOpen ? 'chevron-down' : 'chevron-right'" :size="14" />
              {{ policyOpen ? t('connection.guide.hidePolicy') : t('connection.guide.showPolicy') }}
            </button>
            <div v-if="policyOpen" class="pt-2">
              <ConnectionKeyPolicy part="lift" :project-id="projectId" />
            </div>
          </template>
        </div>
      </li>
    </ol>
  </div>
</template>

<script setup>
// The setup instruction: eight steps from signing up to downloading the key.
import { GUIDE_STEPS } from '~/utils/connectionView.js'

const props = defineProps({
  projectId: { type: String, default: '' },
  highlight: { type: String, default: '' },
})

const { t } = useI18n()
const policyOpen = ref(props.highlight === 'ban')

watch(() => props.highlight, (id) => {
  if (id === 'ban') policyOpen.value = true
  if (!id) return
  nextTick(() => document.getElementById(`connection-step-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
}, { immediate: true })
</script>
