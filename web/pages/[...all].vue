<template>
  <div class="page">
    <EmptyState icon="search" :title="t('common.notFoundTitle')" :text="t('common.notFoundText')">
      <NuxtLink to="/" class="btn-secondary">{{ t('common.home') }}</NuxtLink>
    </EmptyState>
  </div>
</template>

<script setup>
definePageMeta({ name: 'all' })
const { t } = useI18n()
</script>
