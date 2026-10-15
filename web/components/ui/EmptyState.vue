<template>
  <div class="flex flex-col items-center justify-center gap-3 px-6 py-12 text-center">
    <span v-if="icon" class="grid h-12 w-12 place-items-center rounded-2xl bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400">
      <AppIcon :name="icon" :size="22" />
    </span>
    <h3 v-if="title" class="text-base font-semibold">{{ title }}</h3>
    <p v-if="text" class="max-w-md text-sm muted">{{ text }}</p>
    <slot />
  </div>
</template>

<script setup>
defineProps({
  icon: { type: String, default: '' },
  title: { type: String, default: '' },
  text: { type: String, default: '' },
})
</script>
