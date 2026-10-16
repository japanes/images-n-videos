<template>
  <!--
    The paid «Make video» button with everything known before pressing: the
    price, what the model gets word for word, what is left out and why it
    cannot be pressed. A new take over an existing video asks first.
  -->
  <div class="space-y-2 text-sm">
    <p v-if="take && !take.ready && take.refusal" class="text-xs text-amber-700 dark:text-amber-300">
      {{ videoReasonText(take.refusal, t, te, take.refusal_details || {}) }}
    </p>
    <div
      v-for="w in hideWarnings ? [] : (take && take.warnings) || []"
      :key="w"
      class="rounded-card bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:bg-amber-500/10 dark:text-amber-100"
    >
      {{ te(`video.warnings.${w}`) ? t(`video.warnings.${w}`) : w }}
    </div>

    <details v-if="take && take.prompt" class="rounded-card border border-slate-200 p-3 dark:border-slate-600">
      <summary class="cursor-pointer text-xs font-medium">{{ t('video.take.sent') }}</summary>
      <pre class="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words text-xs">{{ take.prompt }}</pre>
      <p class="muted mt-2 text-xs">{{ about }}</p>
    </details>

    <div class="flex flex-wrap items-center gap-2">
      <PriceButton
        icon="video"
        :label="hasVideo ? t('video.take.reshoot') : t('video.take.make')"
        :usd="usd"
        :disabled="disabled || !canShoot"
        :busy="video.isPending('start')"
        @click="shoot"
      />
      <span v-if="video.saving.value || dirty" class="muted text-xs">{{ t('video.take.saving') }}</span>
    </div>
  </div>
</template>

<script setup>
import { videoReasonText } from '~/utils/videoView.js'

const props = defineProps({
  // The controller from useVideoRun().
  video: { type: Object, required: true },
  disabled: { type: Boolean, default: false },
  // When the attachments are shown next to it, they already say the warnings.
  hideWarnings: { type: Boolean, default: false },
})
const { t, te } = useI18n()
const { confirm } = useConfirm()

const run = computed(() => props.video.run.value || {})
const take = computed(() => run.value.take || null)
const hasVideo = computed(() => (run.value.versions || []).length > 0)
// The price is the server's answer for what is saved: wait until the form is saved.
const dirty = computed(() => Object.keys(props.video.draft.value || {}).length > 0)
const usd = computed(() => {
  const v = take.value?.estimate_usd
  return v === null || v === undefined ? null : v
})
const canShoot = computed(() => Boolean(take.value?.ready) && usd.value !== null && !run.value.busy && !dirty.value
  && !props.video.saving.value)
const about = computed(() => {
  const tk = take.value || {}
  return t('video.take.about', {
    seconds: tk.seconds ?? '', resolution: tk.resolution || '', aspect: tk.aspect || '',
    pictures: Number(tk.references_sent) || 0,
  })
})

/** Start the take; over an existing video ask first (it replaces the result here). */
async function shoot() {
  if (hasVideo.value) {
    const ok = await confirm({ message: t('video.take.reshootAsk'), confirmLabel: t('video.take.reshoot') })
    if (!ok) return null
  }
  return props.video.start()
}

defineExpose({ shoot })
</script>
