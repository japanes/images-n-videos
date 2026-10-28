<template>
  <div class="page">
    <EmptyState icon="sparkles" :title="t('home.title')" :text="t('home.text')">
      <div class="flex flex-wrap justify-center gap-2">
        <NuxtLink v-if="hasPage('/settings/connection')" to="/settings/connection" class="btn-primary">{{ t('settings.tabs.connection') }}</NuxtLink>
      </div>
    </EmptyState>
  </div>
</template>

<script setup>
// Start screen: chats when they exist and Google is connected, otherwise the
// connection screen. Until those modules land, a short welcome.
const { t } = useI18n()
const router = useRouter()
const meta = useMetaStore()

const hasPage = (p) => router.resolve(p).matched.length > 0 && router.resolve(p).name !== 'all'

watchEffect(() => {
  if (!meta.loaded || meta.offline) return
  const ready = meta.hasKey || meta.stub
  if (ready && hasPage('/chat')) router.replace('/chat')
  else if (!ready && hasPage('/settings/connection')) router.replace('/settings/connection')
})
</script>
