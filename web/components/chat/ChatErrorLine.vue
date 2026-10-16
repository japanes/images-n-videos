<template>
  <!-- Why something failed: our text, Google's own words folded, a link to the spend log, and buttons from the slot. -->
  <div
    class="rounded-card bg-rose-50 text-rose-800 dark:bg-rose-500/10 dark:text-rose-200"
    :class="compact ? 'px-2 py-1.5 text-xs' : 'px-3 py-2 text-sm'"
    role="alert"
  >
    <div class="flex items-start gap-2">
      <AppIcon name="alert" :size="compact ? 14 : 16" class="mt-0.5 shrink-0" />
      <div class="min-w-0 flex-1 space-y-1">
        <p class="break-words">{{ err.text }}</p>
        <details v-if="err.detail" class="text-xs">
          <summary class="cursor-pointer select-none opacity-80">{{ t('chat.error.google') }}</summary>
          <p class="mt-1 whitespace-pre-wrap break-words font-mono">{{ err.detail }}</p>
        </details>
        <div v-if="spendLink || $slots.default" class="flex flex-wrap items-center gap-2 pt-0.5">
          <slot />
          <NuxtLink v-if="spendLink" :to="spendLink" class="text-xs underline underline-offset-2">{{ t('chat.error.spend') }}</NuxtLink>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { chatItemError } from '~/utils/chatView.js'

const props = defineProps({
  item: { type: Object, required: true }, // anything with error_code / error
  spendLink: { type: String, default: '' },
  compact: { type: Boolean, default: false },
})
const { t, te } = useI18n()
const err = computed(() => chatItemError(props.item, t, te))
</script>
