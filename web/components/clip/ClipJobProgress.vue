<template>
  <div class="space-y-1">
    <div class="h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
      <div class="h-full bg-primary transition-[width]" :style="{ width: `${percent}%` }" />
    </div>
    <div class="flex items-center gap-2 text-xs">
      <Spinner :size="12" />
      <span class="flex-1">{{ job.status === 'queued' ? t('clip.jobs.queued') : label }}</span>
      <span v-if="job.progress" class="tabular-nums muted">{{ percent }}%</span>
      <button type="button" class="btn-ghost btn-sm" @click="$emit('cancel')">{{ t('clip.jobs.cancel') }}</button>
    </div>
  </div>
</template>

<script setup>
const props = defineProps({
  job: { type: Object, required: true },
  label: { type: String, default: '' },
})
defineEmits(['cancel'])
const { t } = useI18n()

const percent = computed(() => Math.round(Math.min(1, Math.max(0, Number(props.job.progress) || 0)) * 100))
</script>
