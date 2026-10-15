<template>
  <div class="page space-y-4">
    <header>
      <h1 class="page-title">{{ t('brand.title') }}</h1>
      <p class="mt-1 text-sm muted">{{ t('brand.subtitle') }}</p>
    </header>
    <BrandTabs />
    <NuxtPage />
  </div>
</template>

<script setup>
// Parent of /brand (kits), /brand/kits/:id (one kit) and /brand/subjects.
// Being a parent route keeps the "Brand" menu item lit on every sub-page.
const { t } = useI18n()
</script>
