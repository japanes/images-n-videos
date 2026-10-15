<template>
  <div ref="root" class="relative">
    <button
      type="button"
      class="btn-ghost px-2 py-1.5"
      :class="jobs.count && 'text-primary'"
      :title="t('jobs.indicator', { n: jobs.count }, jobs.count)"
      @click="open = !open"
    >
      <Spinner v-if="jobs.running.length" :size="16" />
      <AppIcon v-else name="jobs" :size="16" />
      <span class="tabular-nums text-xs">{{ jobs.count }}</span>
    </button>
    <div
      v-if="open"
      class="absolute bottom-full left-0 z-50 mb-2 w-80 rounded-card border border-slate-200 bg-white p-2 shadow-modal dark:border-slate-700 dark:bg-slate-800"
    >
      <p class="px-2 pb-1 text-xs font-semibold muted">{{ t('jobs.activeTitle') }}</p>
      <p v-if="jobs.paused" class="mx-2 mb-2 rounded-button bg-amber-50 px-2 py-1.5 text-xs text-amber-800 dark:bg-amber-500/10 dark:text-amber-200">
        {{ t('shell.jobsPaused') }}
      </p>
      <p v-if="!jobs.count" class="px-2 py-3 text-sm muted">{{ t('jobs.none') }}</p>
      <ul v-else class="max-h-72 space-y-1 overflow-y-auto">
        <li v-for="job in jobs.active" :key="job.id" class="rounded-button px-2 py-1.5 hover:bg-slate-50 dark:hover:bg-slate-700/50">
          <div class="flex items-center gap-2">
            <span class="min-w-0 flex-1 truncate text-sm">{{ job.title || job.kind }}</span>
            <button type="button" class="btn-ghost btn-sm px-1.5" :title="t('jobs.cancel')" @click="cancel(job)">
              <AppIcon name="stop" :size="12" />
            </button>
          </div>
          <div class="mt-1 flex items-center gap-2">
            <div class="h-1 flex-1 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
              <div class="h-full bg-primary transition-all" :style="{ width: `${Math.round((job.progress || 0) * 100)}%` }" />
            </div>
            <span class="text-[11px] muted">{{ job.status === 'queued' ? t('jobs.queued') : `${Math.round((job.progress || 0) * 100)}%` }}</span>
          </div>
          <p v-if="job.progress_note" class="mt-0.5 truncate text-[11px] muted">{{ job.progress_note }}</p>
        </li>
      </ul>
      <NuxtLink v-if="hasJobsPage" to="/jobs" class="mt-1 block rounded-button px-2 py-1.5 text-xs text-primary hover:bg-slate-50 dark:hover:bg-slate-700/50" @click="open = false">
        {{ t('jobs.all') }}
      </NuxtLink>
    </div>
  </div>
</template>

<script setup>
import { onClickOutside } from '@vueuse/core'
import { apiErrorText } from '~/utils/apiErrorText.js'

const { t, te } = useI18n()
const jobs = useJobsStore()
const { confirm } = useConfirm()
const toast = useToast()
const router = useRouter()

const open = ref(false)
const root = ref(null)
onClickOutside(root, () => { open.value = false })
const hasJobsPage = computed(() => router.resolve('/jobs').name !== 'all' && router.resolve('/jobs').matched.length > 0)

async function cancel(job) {
  if (!await confirm({ message: t('jobs.cancelAsk', { title: job.title || job.kind }), tone: 'danger', confirmLabel: t('jobs.cancel') })) return
  try {
    await jobs.cancel(job.id)
  } catch (err) {
    toast.error(apiErrorText(err, t, te))
  }
}
</script>
