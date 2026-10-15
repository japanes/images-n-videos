<template>
  <template v-for="(p, i) in parts" :key="i">
    <a
      v-if="p.type === 'link'"
      :href="p.href"
      target="_blank"
      rel="noopener noreferrer nofollow"
      class="break-words text-primary hover:underline"
    >{{ p.text }}</a>
    <strong v-else-if="p.type === 'strong'" class="font-semibold">{{ p.text }}</strong>
    <em v-else-if="p.type === 'em'">{{ p.text }}</em>
    <code v-else-if="p.type === 'code'" class="rounded bg-slate-100 px-1 py-0.5 font-mono text-[0.85em] dark:bg-slate-900">{{ p.text }}</code>
    <template v-else>{{ p.text }}</template>
  </template>
</template>

<script setup>
// One line of release notes, already split by utils/updatesView.js parseInline().
defineProps({ parts: { type: Array, default: () => [] } })
</script>
