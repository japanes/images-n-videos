<template>
  <!--
    Parts of the prompt, one switch each. A part that does not fit this work
    (no brand, no subjects…) is greyed out with the reason and sends nothing.
  -->
  <div class="space-y-0.5">
    <div
      v-for="b in blocks"
      :key="b.code"
      class="flex items-start gap-3 rounded-button px-1 py-1.5"
      :class="!b.applies && 'opacity-60'"
    >
      <ToggleSwitch
        class="mt-0.5"
        :model-value="b.on"
        :disabled="disabled"
        :aria-label="t(`studio.blocks.${b.code}.name`)"
        @update:model-value="(v) => toggle(b.code, v)"
      />
      <div class="min-w-0 flex-1">
        <div class="text-sm">
          {{ t(`studio.blocks.${b.code}.name`) }}
          <span v-if="b.on !== b.default" class="badge ml-1 bg-primary/10 text-primary">{{ t('studio.blocksPanel.changed') }}</span>
        </div>
        <div class="muted text-xs">
          {{ b.applies ? t(`studio.blocks.${b.code}.hint`) : t(`studio.reasons.${b.reason}`) }}
        </div>
      </div>
    </div>
    <button v-if="changed" type="button" class="btn-ghost btn-sm" :disabled="disabled" @click="reset">
      <AppIcon name="refresh" :size="14" />{{ t('studio.blocksPanel.reset') }}
    </button>
  </div>
</template>

<script setup>
import { studioBlocksMap } from '~/utils/studioView.js'

const props = defineProps({
  blocks: { type: Array, default: () => [] },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['change'])
const { t } = useI18n()

const changed = computed(() => props.blocks.some((b) => b.on !== b.default))

function toggle(code, on) {
  emit('change', { ...studioBlocksMap(props.blocks), [code]: on })
}

function reset() {
  const out = {}
  for (const b of props.blocks) out[b.code] = Boolean(b.default)
  emit('change', out)
}
</script>
