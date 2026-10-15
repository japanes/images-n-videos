/**
 * The Google connection (module 01): state from GET /api/connection and the
 * actions of the screen and the first-run wizard.
 *
 *   const conn = useConnection()
 *   await conn.load()
 *   await conn.upload(file)        // throws ApiError (code key_invalid + details.reason)
 *   await conn.check()             // token, list of models, test text
 *
 * The browser never gets the key itself: only project id, account e-mail,
 * the last characters of the key id and dates.
 */
import { ref } from 'vue'
import { connectionErrorText } from '~/utils/connectionView.js'

export const useConnection = () => {
  const api = useApi()
  const meta = useMetaStore()
  const { t, te } = useI18n()

  const state = ref(null)
  const loading = ref(false)
  const loadError = ref('')
  const busy = ref('') // '' | upload | delete | check | image | omni | marks
  let seq = 0

  const apply = (s) => {
    seq++ // an answer to an action beats any GET still on its way
    state.value = s
    return s
  }

  const load = async () => {
    const mine = ++seq
    loading.value = true
    try {
      const s = await api.get('/api/connection')
      if (mine === seq) { state.value = s; loadError.value = '' }
    } catch (err) {
      if (mine === seq) loadError.value = connectionErrorText(err, t, te)
    } finally {
      if (mine === seq) loading.value = false
    }
  }

  const run = async (name, fn) => {
    busy.value = name
    try {
      return apply(await fn())
    } finally {
      busy.value = ''
    }
  }

  const keyChanged = async (s) => {
    await meta.load() // the shell banners and the start page read has_key from there
    return s
  }

  const upload = (file) => run('upload', async () => keyChanged(await api.upload('/api/connection/key', file)))
  const removeKey = () => run('delete', async () => keyChanged(await api.del('/api/connection/key')))
  const check = () => run('check', () => api.post('/api/connection/check'))
  const checkImage = () => run('image', () => api.post('/api/connection/check/image'))
  const checkOmni = () => run('omni', () => api.post('/api/connection/check/omni'))
  const saveMarks = (marks) => run('marks', () => api.put('/api/connection', marks))

  /** Reload when the key or the results change elsewhere (another tab, the CLI). */
  const listen = () => {
    const { on } = useEvents()
    on('connection.updated', () => { if (!busy.value) load() })
    on('settings.changed', (e) => {
      // the trial length lives in the spend settings; our own marks are settings too
      const key = e?.key || ''
      if (!busy.value && (key.startsWith('connection.') || key === 'spend.credit_days')) load()
    })
    on('reconnect', load)
  }

  const errorText = (err) => connectionErrorText(err, t, te)

  return {
    state, loading, loadError, busy,
    load, listen, upload, removeKey, check, checkImage, checkOmni, saveMarks, errorText,
  }
}
