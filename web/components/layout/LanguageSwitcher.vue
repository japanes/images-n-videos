<template>
  <select
    :value="locale"
    class="rounded-button border-0 bg-transparent py-1 pl-1.5 pr-6 text-xs text-slate-600 hover:bg-slate-100 focus:ring-0 dark:text-slate-300 dark:hover:bg-slate-800"
    :aria-label="t('common.language')"
    @change="setLocale($event.target.value)"
  >
    <option v-for="l in locales" :key="l.code" :value="l.code">{{ l.code.toUpperCase() }}</option>
  </select>
</template>

<script setup>
const { t, locale, locales, setLocale } = useI18n()
</script>
