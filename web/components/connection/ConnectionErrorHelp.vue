<template>
  <div class="space-y-1.5 rounded-card bg-rose-50 px-3 py-2 text-sm text-rose-900 dark:bg-rose-500/10 dark:text-rose-100">
    <ConnectionRichText tag="p" :text="text" />
    <div v-if="help?.step || help?.links.length" class="flex flex-wrap items-center gap-x-4 gap-y-1">
      <button
        v-if="help?.step"
        type="button"
        class="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
        @click="$emit('step', help.stepId)"
      >
        <AppIcon name="info" :size="14" />{{ t('connection.help.step', { n: help.step }) }}
      </button>
      <ConnectionLink v-for="l in help?.links || []" :id="l.id" :key="l.id" :project-id="projectId" />
    </div>
    <details v-if="error?.google_message" class="text-xs">
      <summary class="cursor-pointer select-none opacity-80">{{ t('connection.help.googleAnswer') }}</summary>
      <pre class="mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded bg-white/60 p-2 font-mono text-slate-800 dark:bg-black/30 dark:text-slate-200">{{ error.google_message }}</pre>
    </details>
  </div>
</template>

<script setup>
// A failed check in plain words, the instruction step that fixes it,
// console links, and Google's own answer word for word.
import { errorHelp } from '~/utils/connectionView.js'

const props = defineProps({
  error: { type: Object, default: null },
  projectId: { type: String, default: '' },
})
defineEmits(['step'])

const { t, te } = useI18n()
const help = computed(() => errorHelp(props.error?.code, props.projectId))
const text = computed(() => {
  const code = props.error?.code || 'unknown'
  if (help.value) return t(help.value.key)
  if (te(`errors.${code}`)) return t(`errors.${code}`, { code })
  return t('errors.generic', { code })
})
</script>
