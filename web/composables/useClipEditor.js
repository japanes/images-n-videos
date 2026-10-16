/**
 * State of one open clip project: the edit list with autosave and undo, the
 * player position, background jobs (export, preview, speech recognition) and
 * live updates from the server.
 *
 * The page creates it once; it is handed down with provide/inject:
 *
 *   const editor = useClipEditor()             // pages/clip/[id].vue
 *   const { state, time } = useClipContext()   // any component inside
 *
 * Saving is quiet while it works and loud when it fails (`saveStatus`).
 */
import { computed, inject, provide, ref, shallowRef, watch } from 'vue'
import {
  CLIP_HISTORY_LIMIT, CLIP_SAVE_DELAY_MS, clipCreateHistory, clipErrorText, clipNextKept, clipOutputDuration,
  clipSegments,
} from '~/utils/clipState.js'

const CONTEXT = Symbol('clipEditor')
const CHECKPOINT_MS = 500
const JOB_KINDS = { export: 'clip.export', preview: 'clip.preview', transcribe: 'clip.transcribe' }

const loadedFonts = new Map()

/** Make an uploaded font file usable by the browser preview under `family`. */
export function clipEnsureFont(family, fileId) {
  if (!family || !fileId || typeof FontFace === 'undefined' || typeof document === 'undefined') return
  const key = `${family}|${fileId}`
  if (loadedFonts.has(key)) return
  const face = new FontFace(family, `url(/files/${fileId})`)
  loadedFonts.set(key, face.load().then((f) => { document.fonts.add(f); return true }).catch(() => false))
}

function plain(value) {
  return JSON.parse(JSON.stringify(value))
}

export function useClipEditor() {
  const api = useApi()
  const { t, te } = useI18n()
  const toast = useToast()
  const jobsStore = useJobsStore()

  const project = ref(null)
  const state = ref(null)
  const presets = ref([])
  const exports = ref([])
  const loading = ref(false)
  const loadError = ref(null)
  const saveStatus = ref('saved') // saved | unsaved | saving | failed
  const saveError = ref('')
  const selectedId = ref(null)
  const exportParts = ref(false)
  const sideTab = ref('layers')
  const jobErrors = ref({}) // kind -> text of the last failure
  const lastExport = ref(null) // {job_id, files, warnings}

  // player
  const video = shallowRef(null)
  const time = ref(0)
  const playing = ref(false)
  const asResult = ref(true) // play as the export will be: skip removed pieces

  const history = clipCreateHistory(CLIP_HISTORY_LIMIT)
  const historyTick = ref(0)
  const pendingCheckpoint = ref(false)
  let saveTimer = null
  let checkpointTimer = null
  let saving = null
  let quiet = false
  let version = 0
  let savedVersion = 0
  let replaceWanted = false

  const projectId = computed(() => project.value?.id ?? null)
  const duration = computed(() => Number(project.value?.source?.duration) || 0)
  const segments = computed(() => (state.value ? clipSegments(state.value, duration.value) : []))
  const outputDuration = computed(() => clipOutputDuration(segments.value))
  const selected = computed(() => state.value?.layers?.find((l) => l.id === selectedId.value) || null)
  const presetsByCode = computed(() => Object.fromEntries(presets.value.map((p) => [p.code, p])))
  const canUndo = computed(() => {
    void historyTick.value
    return pendingCheckpoint.value || history.canUndo()
  })
  const canRedo = computed(() => {
    void historyTick.value
    return !pendingCheckpoint.value && history.canRedo()
  })
  const jobs = computed(() => jobsStore.active.filter((j) => j.ref_type === 'clip' && j.ref_id === projectId.value))
  const jobOf = (what) => jobs.value.find((j) => j.kind === JOB_KINDS[what]) || null

  // ── state, autosave, undo ────────────────────────────────────────────────

  function setQuiet(next) {
    quiet = true
    try { state.value = next } finally { quiet = false }
  }

  watch(state, () => {
    if (quiet || !state.value) return
    version += 1
    if (saveStatus.value !== 'saving') saveStatus.value = 'unsaved'
    scheduleSave()
    scheduleCheckpoint()
  }, { deep: true, flush: 'sync' })

  function scheduleSave() {
    clearTimeout(saveTimer)
    saveTimer = setTimeout(() => { save() }, CLIP_SAVE_DELAY_MS)
  }

  function scheduleCheckpoint() {
    pendingCheckpoint.value = true
    clearTimeout(checkpointTimer)
    checkpointTimer = setTimeout(checkpoint, CHECKPOINT_MS)
  }

  function checkpoint() {
    clearTimeout(checkpointTimer)
    checkpointTimer = null
    pendingCheckpoint.value = false
    if (state.value) history.push(state.value)
    historyTick.value += 1
  }

  function restore(snapshot) {
    setQuiet(snapshot)
    if (selectedId.value && !snapshot.layers.some((l) => l.id === selectedId.value)) selectedId.value = null
    version += 1
    saveStatus.value = 'unsaved'
    scheduleSave()
    historyTick.value += 1
  }

  function undo() {
    if (pendingCheckpoint.value) checkpoint()
    const prev = history.undo()
    if (prev) restore(prev)
  }

  function redo() {
    if (pendingCheckpoint.value) return
    const next = history.redo()
    if (next) restore(next)
  }

  /** Save now. Resolves true when the server has the latest edits. */
  async function save() {
    clearTimeout(saveTimer)
    saveTimer = null
    while (saving) await saving.catch(() => {})
    if (!project.value || !state.value) return true
    if (version === savedVersion && saveStatus.value !== 'failed') return true
    const v = version
    saveStatus.value = 'saving'
    saving = api.patch(`/api/clip/projects/${project.value.id}`, { state: plain(state.value) })
    try {
      const res = await saving
      savedVersion = v
      mergeMeta(res)
      saveError.value = ''
      saveStatus.value = version === v ? 'saved' : 'unsaved'
      if (version !== v) scheduleSave()
      return version === v
    } catch (err) {
      saveStatus.value = 'failed'
      saveError.value = clipErrorText(err, t, te)
      return false
    } finally {
      saving = null
    }
  }

  async function flush() {
    const ok = await save()
    if (!ok && saveStatus.value === 'failed') throw new Error(saveError.value || 'save failed')
    return ok
  }

  // ── loading ──────────────────────────────────────────────────────────────

  function mergeMeta(res) {
    if (!res) return
    const { state: _state, ...rest } = res
    project.value = { ...(project.value || {}), ...rest }
  }

  async function load(id) {
    loading.value = true
    loadError.value = null
    try {
      const res = await api.get(`/api/clip/projects/${id}`)
      clearTimeout(saveTimer)
      clearTimeout(checkpointTimer)
      pendingCheckpoint.value = false
      project.value = null
      mergeMeta(res)
      setQuiet(res.state)
      version = 0
      savedVersion = 0
      saveStatus.value = 'saved'
      saveError.value = ''
      selectedId.value = null
      time.value = Number(res.state?.trim?.start) || 0
      history.reset(res.state)
      historyTick.value += 1
      await Promise.all([loadPresets(), loadExports()])
      return res
    } catch (err) {
      loadError.value = err
      throw err
    } finally {
      loading.value = false
    }
  }

  async function loadPresets() {
    if (presets.value.length) return
    try {
      presets.value = (await api.get('/api/clip/presets')).items || []
    } catch {
      presets.value = []
    }
  }

  async function loadExports() {
    if (!projectId.value) return
    try {
      exports.value = (await api.get(`/api/clip/projects/${projectId.value}/exports`)).items || []
    } catch {
      // keep what is shown; the next event or reload tries again
    }
  }

  /** Fresh project data from the server without touching the edits on screen. */
  async function refreshMeta() {
    if (!projectId.value) return null
    try {
      const res = await api.get(`/api/clip/projects/${projectId.value}`)
      mergeMeta(res)
      return res
    } catch {
      return null
    }
  }

  async function rename(title) {
    const res = await api.patch(`/api/clip/projects/${projectId.value}`, { title })
    mergeMeta(res)
  }

  async function setBrand(body) {
    const res = await api.put(`/api/clip/projects/${projectId.value}/brand`, body)
    mergeMeta(res)
  }

  async function remove() {
    clearTimeout(saveTimer)
    await api.del(`/api/clip/projects/${projectId.value}`)
    version = savedVersion
    saveStatus.value = 'saved'
  }

  // ── subtitles from speech ────────────────────────────────────────────────

  function applyWords(transcript, { force = false } = {}) {
    if (!state.value || !transcript) return false
    const sub = state.value.subtitles
    if (sub.words.length && !force) return false
    sub.words = transcript.words || []
    sub.transcript_id = transcript.id
    sub.language = transcript.language || null
    sub.enabled = true
    return true
  }

  async function onTranscript(transcriptId) {
    if (!transcriptId) return
    try {
      const tr = await api.get(`/api/clip/transcripts/${transcriptId}`)
      const force = replaceWanted
      replaceWanted = false
      if (applyWords(tr, { force })) toast.success(t('clip.subtitles.recognized', { n: tr.words?.length || 0 }, tr.words?.length || 0))
    } catch (err) {
      toast.error(clipErrorText(err, t, te))
    }
  }

  async function transcribe({ model, language, force = false, replace = false } = {}) {
    await flush()
    replaceWanted = replace
    jobErrors.value = { ...jobErrors.value, transcribe: '' }
    const res = await api.post(`/api/clip/projects/${projectId.value}/transcribe`,
      { model, language, force, replace })
    if (res.transcript) {
      replaceWanted = false
      applyWords(res.transcript, { force: replace })
      toast.success(t('clip.subtitles.reused', { n: res.transcript.words?.length || 0 }, res.transcript.words?.length || 0))
    } else if (res.job_id) {
      trackJob(res.job_id, JOB_KINDS.transcribe)
    }
    return res
  }

  // ── export and preview ───────────────────────────────────────────────────

  function trackJob(jobId, kind) {
    jobsStore.upsert({ id: jobId, kind, status: 'queued', progress: null, progress_note: null,
      ref_type: 'clip', ref_id: projectId.value })
  }

  async function startPreview() {
    await flush()
    jobErrors.value = { ...jobErrors.value, preview: '' }
    const res = await api.post(`/api/clip/projects/${projectId.value}/preview`)
    trackJob(res.job_id, JOB_KINDS.preview)
    return res
  }

  async function startExport() {
    await flush()
    jobErrors.value = { ...jobErrors.value, export: '' }
    const res = await api.post(`/api/clip/projects/${projectId.value}/export`, { parts: exportParts.value })
    lastExport.value = res
    trackJob(res.job_id, JOB_KINDS.export)
    return res
  }

  async function cancelJob(job) {
    if (!job) return
    try {
      await jobsStore.cancel(job.id)
    } catch (err) {
      toast.error(clipErrorText(err, t, te))
    }
  }

  // ── player ───────────────────────────────────────────────────────────────

  let frame = 0
  function tick() {
    frame = 0
    const el = video.value
    if (!el) return
    let t0 = el.currentTime
    if (asResult.value && !el.paused) {
      const next = clipNextKept(t0, segments.value)
      if (next === null) {
        el.pause()
        t0 = Math.min(t0, duration.value)
      } else if (next > t0 + 0.02) {
        el.currentTime = next
        t0 = next
      }
    }
    time.value = t0
    if (!el.paused) frame = requestAnimationFrame(tick)
  }

  function onPlayState() {
    const el = video.value
    playing.value = !!el && !el.paused
    if (playing.value && !frame) frame = requestAnimationFrame(tick)
    if (!playing.value && el) time.value = el.currentTime
  }

  function seek(t) {
    const v = Math.max(0, Math.min(duration.value || Infinity, Number(t) || 0))
    time.value = v
    if (video.value) video.value.currentTime = v
  }

  function togglePlay() {
    const el = video.value
    if (!el) return
    if (!el.paused) {
      el.pause()
      return
    }
    if (asResult.value) {
      const next = clipNextKept(el.currentTime, segments.value)
      el.currentTime = next === null ? (segments.value[0]?.[0] ?? 0) : next
    }
    el.play().catch(() => {})
  }

  function attachVideo(el) {
    if (video.value === el) return
    video.value = el
    if (el) {
      el.currentTime = time.value || 0
      onPlayState()
    }
  }

  // ── live updates ─────────────────────────────────────────────────────────

  const { on } = useEvents()
  on('clip.updated', (data) => {
    if (!projectId.value || Number(data?.project_id) !== projectId.value) return
    if (data.what === 'transcript') onTranscript(data.transcript_id)
    else if (data.what === 'exported') {
      loadExports()
      refreshMeta()
    } else refreshMeta()
  })
  on('job.updated', (job) => {
    if (!job || job.ref_type !== 'clip' || job.ref_id !== projectId.value) return
    const what = Object.keys(JOB_KINDS).find((k) => JOB_KINDS[k] === job.kind)
    if (!what) return
    if (job.status === 'failed') {
      const text = clipErrorText(job, t, te)
      jobErrors.value = { ...jobErrors.value, [what]: text }
      toast.error(text)
    } else if (job.status === 'done' && what === 'export') {
      toast.success(t('clip.export.done'))
      loadExports()
    }
  })
  on('reconnect', async () => {
    const res = await refreshMeta()
    loadExports()
    const words = res?.state?.subtitles?.words || []
    if (state.value && words.length && !state.value.subtitles.words.length) {
      applyWords({ id: res.state.subtitles.transcript_id, language: res.state.subtitles.language, words })
    }
  })

  const editor = {
    project, state, presets, presetsByCode, exports, loading, loadError, saveStatus, saveError, selectedId,
    selected, exportParts, sideTab, jobErrors, lastExport, video, time, playing, asResult, projectId, duration,
    segments, outputDuration, canUndo, canRedo, jobs, jobOf,
    load, save, flush, undo, redo, checkpoint, rename, setBrand, remove, loadExports, refreshMeta,
    transcribe, applyWords, startPreview, startExport, cancelJob, seek, togglePlay, attachVideo, onPlayState,
    hasUnsaved: () => saveStatus.value !== 'saved' || saveTimer !== null,
    stop: () => {
      clearTimeout(saveTimer)
      clearTimeout(checkpointTimer)
      if (frame) cancelAnimationFrame(frame)
    },
  }
  provide(CONTEXT, editor)
  return editor
}

/** The editor of the page this component sits on. */
export function useClipContext() {
  const editor = inject(CONTEXT, null)
  if (!editor) throw new Error('useClipContext() outside the clip editor page')
  return editor
}
