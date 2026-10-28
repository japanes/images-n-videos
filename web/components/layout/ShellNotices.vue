<template>
  <div v-if="notices.length" class="space-y-px">
    <div
      v-for="n in notices"
      :key="n.key"
      class="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-sm"
      :class="n.tone === 'warn'
        ? 'bg-amber-50 text-amber-900 dark:bg-amber-500/10 dark:text-amber-100'
        : 'bg-primary/10 text-slate-800 dark:text-slate-100'"
    >
      <AppIcon :name="n.tone === 'warn' ? 'alert' : 'info'" :size="16" />
      <span class="min-w-0 flex-1">{{ n.text }}</span>
      <NuxtLink v-if="n.to" :to="n.to" class="font-medium text-primary hover:underline">{{ n.action }}</NuxtLink>
    </div>
  </div>
</template>

<script setup>
const { t } = useI18n()
const meta = useMetaStore()
const route = useRoute()
const router = useRouter()

const hasPage = (p) => router.resolve(p).matched.length > 0 && router.resolve(p).name !== 'all'

const notices = computed(() => {
  const list = []
  if (!meta.loaded) return list
  if (meta.offline) {
    list.push({ key: 'offline', tone: 'warn', text: t('shell.offline') })
    return list
  }
  if (meta.stub) list.push({ key: 'stub', tone: 'info', text: t('shell.stubMode') })
  if (!meta.hasKey && !meta.stub && route.path !== '/connection') {
    list.push({ key: 'nokey', tone: 'warn', text: t('shell.noKey'), to: hasPage('/connection') ? '/connection' : null, action: t('shell.connect') })
  }
  return list
})
</script>
