<template>
  <div class="page space-y-4">
    <h1 class="page-title">{{ t('settings.title') }}</h1>
    <SettingsTabs />
    <NuxtPage />
  </div>
</template>

<script setup>
// Parent of /settings (general), /settings/spend, /settings/jobs,
// /settings/connection and /settings/models. Being a parent route keeps the
// "Settings" menu item lit on every tab.
const { t } = useI18n()
</script>
