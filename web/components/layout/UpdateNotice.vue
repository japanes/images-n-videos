<template>
  <div v-if="view" class="flex flex-wrap items-center gap-x-3 gap-y-1 bg-primary/10 px-4 py-2 text-sm text-slate-800 dark:text-slate-100">
    <Spinner v-if="view.kind === 'running'" :size="16" />
    <AppIcon v-else name="update" :size="16" />
    <span class="min-w-0 flex-1">{{ view.text }}</span>

    <template v-if="view.kind === 'reload'">
      <button type="button" class="btn-primary btn-sm" @click="reloadPage">{{ t('updates.notice.reload') }}</button>
    </template>
    <template v-else-if="view.kind === 'available'">
      <button type="button" class="font-medium text-primary hover:underline" @click="notesOpen = true">{{ t('updates.notice.whatsNew') }}</button>
      <button type="button" class="btn-primary btn-sm" :disabled="busy" @click="installNow">{{ t('updates.notice.updateNow') }}</button>
      <button type="button" class="btn-ghost -my-1 p-1" :aria-label="t('updates.notice.later')" :title="t('updates.notice.later')" @click="dismiss">
        <AppIcon name="close" :size="14" />
      </button>
    </template>
    <NuxtLink v-else-if="view.kind === 'running' && route.path !== '/updates'" to="/updates" class="font-medium text-primary hover:underline">
      {{ t('updates.notice.details') }}
    </NuxtLink>

    <ModalShell :open="notesOpen && view.kind === 'available'" :title="t('updates.notice.notesTitle', { version: view.version })" size="lg" @close="notesOpen = false">
      <UpdatesNotes :markdown="view.release?.notes_md || ''" />
      <template #footer>
        <NuxtLink to="/updates" class="btn-ghost mr-auto" @click="notesOpen = false">{{ t('updates.notice.allVersions') }}</NuxtLink>
        <button type="button" class="btn-secondary" @click="notesOpen = false">{{ t('common.close') }}</button>
        <button type="button" class="btn-primary" :disabled="busy" @click="installNow">{{ t('updates.notice.updateNow') }}</button>
      </template>
    </ModalShell>
  </div>
</template>

<script setup>
// Header strip: "Version X is available" → what's new → update now; "Updating
// to X…" while it runs; "reload the page" once the app came back newer.
import { useIntervalFn } from '@vueuse/core'
import { NOTICE_POLL_MS, POLL_ACTIVE_MS, isUpdateRunning, noticeFor } from '~/utils/updatesView.js'

const DISMISS_KEY = 'vf_update_dismissed'

const { t, te } = useI18n()
const u = useUpdates()
const meta = useMetaStore()
const route = useRoute()

const notesOpen = ref(false)
const busy = ref(false)
const dismissed = ref(readDismissed())
const firstVersion = ref('')

function readDismissed() {
  try { return localStorage.getItem(DISMISS_KEY) || null } catch { return null }
}

function dismiss() {
  const version = view.value?.version
  dismissed.value = version || null
  try { if (version) localStorage.setItem(DISMISS_KEY, version) } catch { /* private window: forget on reload */ }
}

// The version this tab was loaded with; a different one later means the app was updated.
watch(() => meta.version, (v) => { if (v && !firstVersion.value) firstVersion.value = v }, { immediate: true })

const view = computed(() => {
  const newer = firstVersion.value
    && [meta.version, u.overview.value?.app_version].find((v) => v && v !== firstVersion.value)
  if (newer) return { kind: 'reload', version: newer, text: t('updates.notice.updated', { version: newer }) }
  const n = noticeFor(u.overview.value, { dismissed: dismissed.value })
  if (!n) return null
  if (n.kind === 'running') return { ...n, text: t('updates.notice.running', { version: n.version || '—' }) }
  // The updates page shows the same offer in full.
  if (route.path === '/updates') return null
  return { ...n, text: t('updates.notice.available', { version: n.version }) }
})

async function installNow() {
  const version = view.value?.version
  if (!version) return
  busy.value = true
  try {
    if (await u.install(version, { t, te })) notesOpen.value = false
  } finally {
    busy.value = false
  }
}

function reloadPage() {
  window.location.reload()
}

// Rarely when idle; every few seconds while an update runs. The updates page polls too.
const running = computed(() => isUpdateRunning(u.overview.value?.updater?.operation) || u.lost.value)
let lastAsk = 0
function ask() {
  lastAsk = Date.now()
  u.refresh()
}
useIntervalFn(() => {
  if (route.path === '/updates') return
  const every = running.value ? POLL_ACTIVE_MS * 2 : NOTICE_POLL_MS
  if (Date.now() - lastAsk >= every) ask()
}, POLL_ACTIVE_MS)

const { on } = useEvents()
on('reconnect', () => ask()) // the meta store reloads itself on reconnect
on('jobs.paused', () => ask())
onMounted(ask)
</script>
