<template>
  <section class="card p-5">
    <div class="mb-3 flex items-center gap-3">
      <h2 class="min-w-0 flex-1 text-base font-semibold">{{ t('updates.history.title') }}</h2>
      <Spinner v-if="loading" :size="16" />
    </div>

    <p
      v-if="error"
      class="flex flex-wrap items-center gap-2 rounded-card bg-rose-50 px-3 py-2 text-sm text-rose-800 dark:bg-rose-500/10 dark:text-rose-200"
    >
      <AppIcon name="alert" :size="16" class="shrink-0" />
      <span class="min-w-0 flex-1 break-words">{{ error }}</span>
      <button type="button" class="btn-secondary btn-sm" :disabled="loading" @click="load">{{ t('common.retry') }}</button>
    </p>
    <p v-else-if="loaded && !items.length" class="text-sm muted">{{ t('updates.history.empty') }}</p>

    <ul v-if="items.length" class="divide-y divide-slate-200 dark:divide-slate-700">
      <li v-for="(h, i) in items" :key="h.op_id || i" class="space-y-1 py-3 first:pt-0 last:pb-0">
        <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span class="text-sm font-medium">{{ t('updates.history.versions', { from: h.version_from || '—', to: h.version_to || '—' }) }}</span>
          <span class="badge" :class="resultTone(h.result)">{{ t(resultKey(h.result)) }}</span>
          <span class="text-xs muted">{{ t(sourceKey(h.source)) }}</span>
          <span class="ml-auto text-xs muted">{{ formatDateTime(h.finished_at || h.started_at, locale) }}</span>
        </div>
        <p v-if="h.error" class="break-words text-sm text-rose-700 dark:text-rose-300">{{ h.error }}</p>
        <p v-if="h.backup_file" class="text-xs muted">{{ t('updates.backupFile', { file: h.backup_file }) }}</p>
      </li>
    </ul>
  </section>
</template>

<script setup>
import { formatDateTime } from '~/utils/format.js'
import { resultKey, resultTone, sourceKey, updatesErrorText } from '~/utils/updatesView.js'

const { t, te, locale } = useI18n()

const items = ref([])
const loaded = ref(false)
const loading = ref(false)
const error = ref('')

async function load() {
  loading.value = true
  try {
    const res = await useApi().get('/api/updates/history')
    items.value = res.items || [] // newest first, as the updater gives them
    error.value = ''
    loaded.value = true
  } catch (err) {
    error.value = updatesErrorText(err, t, te)
  } finally {
    loading.value = false
  }
}

onMounted(load)
defineExpose({ load })
</script>
