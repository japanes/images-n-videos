<template>
  <!-- Why a step of the text tool failed: our text, Google's own words folded. -->
  <div
    class="rounded-card bg-rose-50 text-rose-800 dark:bg-rose-500/10 dark:text-rose-200"
    :class="compact ? 'px-2 py-1.5 text-xs' : 'px-3 py-2 text-sm'"
    role="alert"
  >
    <div class="flex items-start gap-2">
      <AppIcon name="alert" :size="compact ? 14 : 16" class="mt-0.5 shrink-0" />
      <div class="min-w-0 flex-1 space-y-1">
        <p v-if="lead" class="font-medium">{{ lead }}</p>
        <p class="break-words">{{ err.text }}</p>
        <details v-if="err.detail" class="text-xs">
          <summary class="cursor-pointer select-none opacity-80">{{ t('chat.error.google') }}</summary>
          <p class="mt-1 whitespace-pre-wrap break-words font-mono">{{ err.detail }}</p>
        </details>
      </div>
    </div>
  </div>
</template>

<script setup>
import { textBackgroundError } from '~/utils/textView.js'

const props = defineProps({
  item: { type: Object, required: true }, // `{error_code, error}` of a row or `{code, message}` of a step
  lead: { type: String, default: '' },
  compact: { type: Boolean, default: false },
})
const { t, te } = useI18n()
const err = computed(() => textBackgroundError({
  error_code: props.item?.error_code || props.item?.code || '',
  error: props.item?.error || props.item?.message || '',
}, t, te))
</script>
