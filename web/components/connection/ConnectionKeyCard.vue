<template>
  <section class="card p-4">
    <div class="flex items-center gap-2">
      <AppIcon name="key" :size="18" class="text-primary" />
      <h2 class="flex-1 text-sm font-semibold">{{ t('connection.key.title') }}</h2>
    </div>

    <p v-if="!keyInfo.readable" class="mt-3 rounded-input bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:bg-rose-500/10 dark:text-rose-300">
      {{ t('connection.key.unreadable') }}
    </p>

    <dl class="mt-3 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1.5 text-sm">
      <dt class="muted">{{ t('connection.key.projectId') }}</dt>
      <dd class="truncate font-mono text-xs leading-5">{{ keyInfo.project_id || '—' }}</dd>
      <dt class="muted">{{ t('connection.key.account') }}</dt>
      <dd class="truncate font-mono text-xs leading-5" :title="keyInfo.client_email">{{ keyInfo.client_email || '—' }}</dd>
      <dt class="muted">{{ t('connection.key.keyId') }}</dt>
      <dd class="font-mono text-xs leading-5">{{ keyInfo.key_id_tail ? `…${keyInfo.key_id_tail}` : '—' }}</dd>
      <dt class="muted">{{ t('connection.key.uploaded') }}</dt>
      <dd>{{ formatDateTime(keyInfo.uploaded_at, locale) }}</dd>
      <dt class="muted">{{ t('connection.key.lastCheck') }}</dt>
      <dd>{{ lastCheckAt ? formatDateTime(lastCheckAt, locale) : t('connection.key.never') }}</dd>
    </dl>

    <div class="mt-4 flex flex-wrap gap-2">
      <button type="button" class="btn-secondary btn-sm" :disabled="!!busy" @click="$emit('replace')">
        <Spinner v-if="busy === 'upload'" :size="14" />
        <AppIcon v-else name="upload" :size="14" />
        {{ t('connection.key.replace') }}
      </button>
      <button type="button" class="btn-ghost btn-sm text-rose-600 dark:text-rose-400" :disabled="!!busy" @click="$emit('delete')">
        <Spinner v-if="busy === 'delete'" :size="14" />
        <AppIcon v-else name="trash" :size="14" />
        {{ t('connection.key.delete') }}
      </button>
    </div>

    <p class="mt-4 flex gap-2 rounded-input bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:bg-amber-500/10 dark:text-amber-200">
      <AppIcon name="alert" :size="14" class="mt-0.5 shrink-0" />
      <span>{{ t('connection.key.password') }}</span>
    </p>
  </section>
</template>

<script setup>
// Safe facts about the uploaded key (never the key itself) and its actions.
import { formatDateTime } from '~/utils/format.js'

defineProps({
  keyInfo: { type: Object, required: true },
  lastCheckAt: { type: String, default: null },
  busy: { type: String, default: '' },
})
defineEmits(['replace', 'delete'])

const { t, locale } = useI18n()
</script>
