<template>
  <div class="page space-y-4">
    <header class="flex flex-wrap items-start gap-3">
      <div class="min-w-0 flex-1">
        <h1 class="page-title">{{ t('updates.title') }}</h1>
        <p class="mt-1 text-sm muted">{{ t('updates.subtitle') }}</p>
      </div>
      <button
        v-if="ov && ov.reachable"
        type="button"
        class="btn-secondary"
        :disabled="checking || u.lost.value"
        @click="check"
      >
        <Spinner v-if="checking" :size="16" /><AppIcon v-else name="refresh" :size="16" />
        {{ t('updates.check.button') }}
      </button>
    </header>

    <p
      v-if="u.lost.value"
      class="flex items-center gap-2 rounded-card bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:bg-amber-500/10 dark:text-amber-100"
    >
      <Spinner v-if="!stopped" :size="16" class="shrink-0" />{{ stopped ? t('updates.stop.started') : t('updates.restarting') }}
    </p>

    <div v-if="!ov && !u.error.value" class="flex justify-center py-12"><Spinner :size="24" /></div>

    <EmptyState
      v-else-if="!ov && u.error.value && !u.lost.value"
      icon="alert"
      :title="t('updates.loadFailed')"
      :text="updatesErrorText(u.error.value, t, te)"
    >
      <button type="button" class="btn-secondary" @click="u.refresh()">{{ t('common.retry') }}</button>
    </EmptyState>

    <template v-else-if="ov">
      <!-- The updater is not there: the rest of the app works, only updates are off. -->
      <section v-if="!ov.reachable" class="card space-y-3 p-5">
        <div class="flex items-start gap-3">
          <span class="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-slate-100 text-slate-500 dark:bg-slate-700 dark:text-slate-300">
            <AppIcon name="update" :size="20" />
          </span>
          <div class="min-w-0 space-y-1">
            <h2 class="text-base font-semibold">{{ t('updates.unreachable.title') }}</h2>
            <p class="text-sm muted">{{ t('updates.unreachable.text') }}</p>
            <p v-if="ov.message" class="break-words font-mono text-xs muted">{{ ov.message }}</p>
          </div>
        </div>
        <div class="flex flex-wrap items-center gap-3">
          <span class="text-sm">{{ t('updates.current.version', { version: ov.app_version || '—' }) }}</span>
          <button type="button" class="btn-secondary btn-sm ml-auto" :disabled="u.loading.value" @click="u.refresh()">
            {{ t('common.retry') }}
          </button>
        </div>
      </section>

      <template v-else>
        <p
          v-if="status.dev"
          class="flex gap-2 rounded-card bg-primary/10 px-4 py-3 text-sm text-slate-800 dark:text-slate-100"
        >
          <AppIcon name="info" :size="16" class="mt-0.5 shrink-0" />{{ t('updates.dev') }}
        </p>

        <UpdatesProgress
          v-if="showProgress"
          :operation="status.operation"
          :step-log="status.step_log"
          :forcing="forcing"
          @force="force"
        />

        <!-- What is installed and when the updater last looked. -->
        <section class="card space-y-2 p-5">
          <div class="flex flex-wrap items-baseline gap-x-4 gap-y-1">
            <h2 class="text-base font-semibold">{{ t('updates.current.version', { version: ov.app_version || '—' }) }}</h2>
            <span class="text-sm muted">{{ t('updates.current.channel', { channel: t(`updates.channel.${status.channel}`) }) }}</span>
          </div>
          <p class="text-sm muted">
            {{ status.last_check_at
              ? t('updates.current.checkedAt', { at: formatDateTime(status.last_check_at, locale) })
              : t('updates.current.neverChecked') }}
          </p>
          <p
            v-if="status.last_check_error"
            class="flex gap-2 rounded-card bg-rose-50 px-3 py-2 text-sm text-rose-800 dark:bg-rose-500/10 dark:text-rose-200"
          >
            <AppIcon name="alert" :size="16" class="mt-0.5 shrink-0" />
            <span class="min-w-0 break-words">{{ t('updates.current.checkFailed', { message: status.last_check_error }) }}</span>
          </p>
          <p v-else-if="!status.available.length" class="flex items-center gap-2 text-sm text-emerald-700 dark:text-emerald-300">
            <AppIcon name="check" :size="16" />{{ t('updates.current.upToDate') }}
          </p>
        </section>

        <UpdatesVersions
          v-if="status.available.length"
          :releases="status.available"
          :current="ov.app_version"
          :can-install="!status.dev && !opActive"
          :installing="installing"
          @install="install"
        />

        <UpdatesSettings :status="status" :disabled="status.dev" @saved="u.accept" />
      </template>

      <UpdatesHistory v-if="ov.reachable" ref="historyRef" />

      <!-- Stopping the whole app from the browser. -->
      <section v-if="ov.reachable && !status?.dev" class="card space-y-3 p-5">
        <h2 class="text-base font-semibold">{{ t('updates.stop.title') }}</h2>
        <p class="text-sm muted">{{ t('updates.stop.text') }}</p>
        <button type="button" class="btn-secondary" :disabled="stopping || opActive" @click="stopApp">
          <AppIcon name="stop" :size="16" />{{ t('updates.stop.button') }}
        </button>
      </section>
    </template>
  </div>
</template>

<script setup>
import { useIntervalFn } from '@vueuse/core'
import { formatDateTime, parseTs } from '~/utils/format.js'
import { POLL_ACTIVE_MS, POLL_IDLE_MS, isUpdateRunning, updatesErrorText } from '~/utils/updatesView.js'

const { t, te, locale } = useI18n()
const u = useUpdates()
const toast = useToast()
const { confirm } = useConfirm()

const ov = computed(() => u.overview.value)
const status = computed(() => ov.value?.updater || null)
const opActive = computed(() => isUpdateRunning(status.value?.operation))

// The last operation stays on screen for a day after it ended, so a failure is seen.
const showProgress = computed(() => {
  const op = status.value?.operation
  if (!op) return false
  if (op.active) return true
  const ended = parseTs(op.finished_at)
  return !!ended && Date.now() - ended.getTime() < 24 * 3600 * 1000
})

const checking = ref(false)
const installing = ref('')
const forcing = ref(false)
const stopping = ref(false)
const stopped = ref(false) // the human stopped the app: a lost connection is not a restart
const historyRef = ref(null)

async function check() {
  checking.value = true
  try {
    u.accept(await useApi().post('/api/updates/check'))
  } catch (err) {
    toast.error(updatesErrorText(err, t, te))
  } finally {
    checking.value = false
  }
}

async function install(version) {
  installing.value = version
  try {
    await u.install(version, { t, te })
  } finally {
    installing.value = ''
  }
}

async function force() {
  const op = status.value?.operation
  if (!op?.to) return
  forcing.value = true
  try {
    await u.force(op.to, { t, te })
  } finally {
    forcing.value = false
  }
}

async function stopApp() {
  const ok = await confirm({
    title: t('updates.stop.confirmTitle'),
    message: t('updates.stop.confirmText'),
    confirmLabel: t('updates.stop.button'),
    tone: 'danger',
  })
  if (!ok) return
  stopping.value = true
  try {
    await useApi().post('/api/updates/stop')
    stopped.value = true
    toast.info(t('updates.stop.started'), { timeout: 0 })
  } catch (err) {
    toast.error(updatesErrorText(err, t, te))
  } finally {
    stopping.value = false
  }
}

// Ask often while something is going on (or the app restarts), rarely otherwise.
const fast = computed(() => opActive.value || u.lost.value)
let lastPoll = 0
async function poll() {
  lastPoll = Date.now()
  await u.refresh()
}
useIntervalFn(() => {
  if (fast.value || Date.now() - lastPoll >= POLL_IDLE_MS) poll()
}, POLL_ACTIVE_MS)

// When an operation ends, the history has a new line.
watch(opActive, (now, before) => {
  if (before && !now) historyRef.value?.load()
})

const { on } = useEvents()
on('reconnect', () => { poll(); historyRef.value?.load() })
on('jobs.paused', () => poll())

onMounted(poll)
</script>
