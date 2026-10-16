<template>
  <!-- What a paid step would send to Google, word for word; nothing is sent from here. -->
  <ModalShell open :title="t('text.preview.title')" size="lg" @close="$emit('close')">
    <div class="space-y-3 text-sm">
      <p class="text-xs muted">{{ t(`text.preview.steps.${step}`) }} · {{ t('text.preview.hint') }}</p>
      <div v-if="loading" class="flex justify-center py-6"><Spinner :size="20" /></div>
      <p v-else-if="error" class="rounded-card bg-rose-50 px-3 py-2 text-rose-800 dark:bg-rose-500/10 dark:text-rose-200">{{ error }}</p>
      <template v-else-if="data">
        <p v-if="!String(data.text || '').trim()" class="rounded-card bg-slate-100 px-3 py-2 dark:bg-slate-900">{{ t('text.preview.nothing') }}</p>
        <template v-else>
          <ul v-if="facts.length" class="flex flex-wrap gap-2 text-xs">
            <li v-for="fact in facts" :key="fact" class="badge bg-slate-100 text-slate-700 dark:bg-slate-700 dark:text-slate-200">{{ fact }}</li>
          </ul>
          <div v-if="String(data.system || '').trim()" class="space-y-1">
            <h3 class="text-xs font-semibold uppercase tracking-wide muted">{{ t('text.preview.system') }}</h3>
            <pre class="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-card bg-slate-100 p-3 font-mono text-xs dark:bg-slate-900">{{ data.system }}</pre>
          </div>
          <div class="space-y-1">
            <h3 class="text-xs font-semibold uppercase tracking-wide muted">{{ t('text.preview.text') }}</h3>
            <pre class="max-h-[50vh] overflow-auto whitespace-pre-wrap break-words rounded-card bg-slate-100 p-3 font-mono text-xs dark:bg-slate-900">{{ data.text }}</pre>
          </div>
        </template>
      </template>
    </div>
    <template #footer>
      <button type="button" class="btn-secondary" @click="$emit('close')">{{ t('common.close') }}</button>
    </template>
  </ModalShell>
</template>

<script setup>
import { textErrorText } from '~/utils/textView.js'

const props = defineProps({
  step: { type: String, required: true }, // place | write | variants | humanize | backgrounds
})
defineEmits(['close'])
const tool = inject('textTool')
const { t, te } = useI18n()

const data = ref(null)
const loading = ref(true)
const error = ref('')

/** Short facts next to the text: how many answers, blocks, pictures. */
const facts = computed(() => {
  const d = data.value || {}
  const out = []
  if (props.step === 'variants' && d.count) out.push(t('text.preview.calls', { n: d.count }, d.count))
  if (props.step === 'backgrounds' && d.count) out.push(t('text.preview.pictures', { n: d.count }, d.count))
  if (d.blocks) out.push(t('text.preview.blocks', { n: d.blocks }, d.blocks))
  if (props.step === 'place') out.push(t('text.preview.withPicture'))
  if (props.step === 'backgrounds' && d.images) out.push(t('text.preview.withPicture'))
  if (d.model_id) out.push(d.model_id)
  return out
})

onMounted(async () => {
  try {
    data.value = await tool.promptPreview(props.step)
  } catch (err) {
    error.value = textErrorText(err, t, te)
  } finally {
    loading.value = false
  }
})
</script>
