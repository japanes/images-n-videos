<template>
  <section class="card p-4">
    <div class="flex items-center gap-2">
      <span
        class="flex h-6 w-6 shrink-0 items-center justify-center rounded-full"
        :class="restored ? 'bg-emerald-500 text-white' : 'bg-amber-100 text-amber-700 dark:bg-amber-500/20 dark:text-amber-300'"
      >
        <AppIcon :name="restored ? 'check' : 'info'" :size="14" />
      </span>
      <h2 class="flex-1 text-sm font-semibold">{{ t('connection.ban.title') }}</h2>
    </div>
    <p class="mt-2 text-sm">{{ restored ? t('connection.ban.restored') : t('connection.ban.notRestored') }}</p>
    <p v-if="!restored" class="mt-1 text-xs muted">{{ t('connection.ban.nothing') }}</p>

    <details class="mt-3 group">
      <summary class="cursor-pointer text-sm font-medium text-primary">{{ t('connection.ban.how') }}</summary>
      <div class="mt-3">
        <ConnectionKeyPolicy part="restore" :project-id="projectId" />
      </div>
    </details>

    <div class="mt-3">
      <button
        type="button"
        class="btn-sm"
        :class="restored ? 'btn-ghost' : 'btn-secondary'"
        :disabled="busy"
        @click="$emit('mark', !restored)"
      >
        <Spinner v-if="busy" :size="14" />
        {{ restored ? t('connection.ban.unmark') : t('connection.ban.mark') }}
      </button>
    </div>
  </section>
</template>

<script setup>
// Reminder to turn the ban on key files back on, with the how-to and a mark.
defineProps({
  restored: { type: Boolean, default: false },
  projectId: { type: String, default: '' },
  busy: { type: Boolean, default: false },
})
defineEmits(['mark'])

const { t } = useI18n()
</script>
