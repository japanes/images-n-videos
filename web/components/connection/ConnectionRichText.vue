<template>
  <component :is="tag">
    <template v-for="(p, i) in parts" :key="i">
      <strong v-if="p.type === 'bold'" class="font-semibold text-slate-800 dark:text-slate-100">{{ p.value }}</strong>
      <code
        v-else-if="p.type === 'code'"
        class="break-all rounded bg-slate-100 px-1 py-px font-mono text-[0.85em] text-slate-800 dark:bg-slate-700 dark:text-slate-100"
      >{{ p.value }}</code>
      <template v-else>{{ p.value }}</template>
    </template>
  </component>
</template>

<script setup>
// Instruction text with **bold** button names and `code` ids, without v-html.
import { parseRich } from '~/utils/connectionView.js'

const props = defineProps({
  text: { type: String, default: '' },
  tag: { type: String, default: 'span' },
})
const parts = computed(() => parseRich(props.text))
</script>
