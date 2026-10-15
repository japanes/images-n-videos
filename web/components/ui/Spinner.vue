<template>
  <svg :width="size" :height="size" viewBox="0 0 24 24" class="animate-spin" aria-hidden="true">
    <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="3" opacity="0.25" />
    <path d="M21 12a9 9 0 0 0-9-9" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" />
  </svg>
</template>

<script setup>
defineProps({ size: { type: [Number, String], default: 18 } })
</script>
