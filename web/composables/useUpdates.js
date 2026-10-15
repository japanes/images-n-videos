/**
 * Updates state shared by the updates page and the header notice: one copy of
 * `/api/updates/status`, so whoever asked last refreshes both.
 *
 *   const u = useUpdates()
 *   await u.refresh()
 *   await u.install('1.5.0', { t, te })   // asks first, then starts the update
 */
import { ref } from 'vue'
import { updatesErrorText, isConnectionLost } from '~/utils/updatesView.js'

const overview = ref(null)
const loaded = ref(false)
const loading = ref(false)
const error = ref(null)
const lost = ref(false)
let inflight = null

async function refresh() {
  if (inflight) return inflight
  loading.value = true
  inflight = (async () => {
    try {
      overview.value = await useApi().get('/api/updates/status')
      error.value = null
      lost.value = false
      loaded.value = true
    } catch (err) {
      error.value = err
      lost.value = isConnectionLost(err)
    } finally {
      loading.value = false
      inflight = null
    }
  })()
  return inflight
}

/** Take an answer that already carries the whole status (check, settings). */
function accept(next) {
  if (next && typeof next === 'object' && 'reachable' in next) {
    overview.value = next
    error.value = null
    lost.value = false
    loaded.value = true
  }
}

/**
 * Ask, then start installing `version`. Running jobs are mentioned: the
 * update waits for them. Returns true when the updater took the request.
 */
async function install(version, { t, te }) {
  const { confirm } = useConfirm()
  const toast = useToast()
  const running = overview.value?.running_jobs || []
  const parts = [t('updates.install.confirmText')]
  if (running.length) parts.push(t('updates.install.confirmBusy', { n: running.length }, running.length))
  const ok = await confirm({
    title: t('updates.install.confirmTitle', { version }),
    message: parts.join('\n\n'),
    confirmLabel: t('updates.install.confirmButton'),
  })
  if (!ok) return false
  try {
    await useApi().post('/api/updates/install', { version })
    toast.info(t('updates.install.started', { version }))
    await refresh()
    return true
  } catch (err) {
    toast.error(updatesErrorText(err, t, te))
    await refresh()
    return false
  }
}

/** "Install anyway": stop waiting for running jobs; they get interrupted. */
async function force(version, { t, te }) {
  const { confirm } = useConfirm()
  const ok = await confirm({
    title: t('updates.force.confirmTitle'),
    message: t('updates.force.confirmText'),
    confirmLabel: t('updates.force.button'),
    tone: 'danger',
  })
  if (!ok) return false
  try {
    await useApi().post('/api/updates/install', { version, force: true })
    await refresh()
    return true
  } catch (err) {
    useToast().error(updatesErrorText(err, t, te))
    await refresh()
    return false
  }
}

export const useUpdates = () => ({ overview, loaded, loading, error, lost, refresh, accept, install, force })
