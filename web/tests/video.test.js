import { describe, expect, it } from 'vitest'
import {
  VIDEO_CAMERA_GROUPS, VIDEO_CLIP_KINDS, VIDEO_ERROR_CODES, VIDEO_PLAN_STATUSES, VIDEO_STATUSES,
  VIDEO_STEP_STATUSES, VIDEO_WARNINGS, videoAspectRatio, videoAttachWarnings, videoCameraGroups, videoClipError,
  videoCurrentVersion, videoDownloadUrl, videoDurationsFor, videoErrorText, videoEventMatches, videoFailedClip,
  videoFileUrl, videoFitSettings, videoHasText, videoModelById, videoModelChoices, videoPlanProgress,
  videoPlanTotal, videoReasonText, videoResolutionRank, videoResolutionsFor, videoRunningClip, videoRunRevision,
  videoSeconds, videoSnapDuration, videoStepsBody, videoThumbUrl,
} from '../utils/videoView.js'
import en from '../i18n/locales/en/video.json'
import ru from '../i18n/locales/ru/video.json'
import uk from '../i18n/locales/uk/video.json'
import enCommon from '../i18n/locales/en/common.json'

const flat = (obj, prefix = '') => Object.fromEntries(Object.entries(obj).flatMap(([k, v]) => (
  v && typeof v === 'object' ? Object.entries(flat(v, `${prefix}${k}.`)) : [[`${prefix}${k}`, v]]
)))

// A tiny stand-in for vue-i18n over the real English texts.
const dict = { ...flat(en), ...flat(enCommon) }
const t = (key, params = {}) => (key in dict ? dict[key].replace(/\{(\w+)\}/g, (_, k) => params[k] ?? '') : key)
const te = (key) => key in dict

// A made-up model: the helpers read only its caps, never its id.
const model = {
  id: 'some-model',
  resolutions: { '720p': [4, 6, 8], '1080p': [8] },
  aspects: ['16:9', '9:16'],
  frame_shadows_references: true,
}

describe('models and settings', () => {
  it('finds and offers models', () => {
    const list = [{ id: 'a' }, { id: 'b', available: false }, { id: 'c', available: false }]
    expect(videoModelById(list, 'a')).toEqual({ id: 'a' })
    expect(videoModelById(list, 'x')).toBeNull()
    expect(videoModelChoices(list).map((m) => m.id)).toEqual(['a'])
    expect(videoModelChoices(list, 'c').map((m) => m.id)).toEqual(['a', 'c'])
  })

  it('reads sizes and lengths from the caps', () => {
    expect(videoResolutionsFor(model)).toEqual(['720p', '1080p'])
    expect(videoDurationsFor(model, '1080p')).toEqual([8])
    expect(videoDurationsFor(model, '')).toEqual([4, 6, 8])
    expect(videoResolutionsFor(null)).toEqual([])
    expect(videoResolutionRank('1080p')).toBeGreaterThan(videoResolutionRank('720p'))
    expect(videoResolutionRank('4k')).toBeGreaterThan(videoResolutionRank('1080p'))
  })

  it('snaps a length to the allowed ones', () => {
    expect(videoSnapDuration(7, [4, 6, 8])).toBe(8)
    expect(videoSnapDuration(5, [4, 6, 8])).toBe(6)
    expect(videoSnapDuration(null, [4, 6, 8])).toBe(4)
    expect(videoSnapDuration(5, [])).toBeNull()
  })

  it('fits the settings into a model', () => {
    expect(videoFitSettings(model, { duration: 4, resolution: '1080p', aspect: '1:1' }))
      .toEqual({ resolution: '1080p', duration: 8, aspect: '16:9' })
    expect(videoFitSettings(model, { duration: 6, resolution: '4k', aspect: '9:16' }))
      .toEqual({ resolution: '720p', duration: 6, aspect: '9:16' })
  })

  it('warns when a first frame leaves the references out', () => {
    expect(videoAttachWarnings(model, { first_frame_id: 1, references: [2] })).toEqual(['frame_shadows_references'])
    expect(videoAttachWarnings(model, { first_frame_id: 1, references: [] })).toEqual([])
    expect(videoAttachWarnings({ ...model, frame_shadows_references: false }, { first_frame_id: 1, references: [2] }))
      .toEqual([])
  })
})

describe('camera moves', () => {
  it('groups moves in the order of the categories', () => {
    const list = [{ code: 'a', category: 'framing' }, { code: 'b', category: 'basic' }, { code: 'c', category: 'odd' }]
    expect(videoCameraGroups(list)).toEqual([{ name: 'basic', codes: ['b'] }, { name: 'framing', codes: ['a', 'c'] }])
    expect(videoCameraGroups([])).toEqual([])
  })

  // The backend test (test_video_runs.py) checks that every move of the list has a name here.
  it('has a name for each of the 60 moves', () => {
    expect(Object.keys(en.video.cameraMove.moves)).toHaveLength(60)
  })
})

describe('runs, clips and plans', () => {
  const run = {
    id: 5, status: 'error', current_version: 1, updated_at: 'u',
    versions: [{ number: 1, file: { id: 3 } }, { number: 2, file: { id: 4 } }],
    clips: [{ id: 1, status: 'done' }, { id: 2, status: 'error', error: 'x' }],
  }

  it('picks the shown version', () => {
    expect(videoCurrentVersion(run).number).toBe(1)
    expect(videoCurrentVersion({ ...run, current_version: null }).number).toBe(2)
    expect(videoCurrentVersion({})).toBeNull()
  })

  it('finds the running and the failed clip', () => {
    expect(videoRunningClip(run)).toBeNull()
    expect(videoRunningClip({ clips: [{ id: 9, running: true }] }).id).toBe(9)
    expect(videoFailedClip(run).id).toBe(2)
    expect(videoFailedClip({ ...run, status: 'done' })).toBeNull()
  })

  it('counts a plan', () => {
    const plan = { status: 'paused', steps: [{ status: 'done' }, { status: 'error' }, { status: 'pending' }] }
    expect(videoPlanProgress(plan)).toEqual({ done: 1, total: 3, errors: 1, current: null, running: false, paused: true })
    expect(videoPlanProgress(null).total).toBe(0)
  })

  it('builds steps and the worst case price', () => {
    expect(videoStepsBody([{ text: ' a ', seconds: '6' }, {}])).toEqual([{ text: 'a', seconds: 6 }, { text: '', seconds: 0 }])
    expect(videoPlanTotal({ pieces: [{ estimate_usd: 1 }, { estimate_usd: 2 }] })).toBe(3)
    expect(videoPlanTotal({ pieces: [], total_usd: 4 })).toBe(4)
    expect(videoPlanTotal(null)).toBeNull()
  })

  it('changes the revision when the run changes', () => {
    const a = videoRunRevision(run)
    expect(videoRunRevision({ ...run, clips: [...run.clips, { id: 3, status: 'queued' }] })).not.toBe(a)
    expect(videoRunRevision(null)).toBe('')
  })

  it('matches events of its own video', () => {
    expect(videoEventMatches({ id: 5 }, 5)).toBe(true)
    expect(videoEventMatches({ id: '5' }, 5)).toBe(true)
    expect(videoEventMatches({ id: 6 }, 5)).toBe(false)
    expect(videoEventMatches(null, 5)).toBe(false)
  })
})

describe('small helpers', () => {
  it('builds links and shapes', () => {
    expect(videoAspectRatio('9:16')).toBe('9 / 16')
    expect(videoAspectRatio('bad')).toBe('16 / 9')
    expect(videoFileUrl({ id: 7 })).toBe('/files/7')
    expect(videoFileUrl({ id: 7, url: '/files/7' })).toBe('/files/7')
    expect(videoDownloadUrl({ id: 7 })).toBe('/files/7?download=1')
    expect(videoDownloadUrl(null)).toBe('')
    expect(videoThumbUrl(7, 200)).toBe('/files/7?w=200')
    expect(videoThumbUrl(null)).toBe('')
  })

  it('shows seconds shortly', () => {
    expect(videoSeconds(4)).toBe('4')
    expect(videoSeconds('7.25')).toBe('7.3')
    expect(videoSeconds(null)).toBe('0')
  })

  it('tells typed text from spaces', () => {
    expect(videoHasText('  a ')).toBe(true)
    expect(videoHasText('   ')).toBe(false)
    expect(videoHasText(null)).toBe(false)
  })
})

describe('error texts', () => {
  it('uses the video texts with the details', () => {
    const err = { code: 'video_too_many_references', details: { max: 3, count: 5 }, message: 'x' }
    expect(videoErrorText(err, t, te)).toBe(t('video.errors.video_too_many_references', { max: 3, count: 5 }))
    expect(videoErrorText(err, t, te)).toContain('5')
  })

  it('joins list details', () => {
    const text = videoReasonText('video_extend_format', t, te, { mimes: ['video/mp4', 'video/webm'] })
    expect(text).toContain('video/mp4, video/webm')
  })

  it('falls back to the raw code', () => {
    expect(videoReasonText('nobody_knows', t, te)).toBe('nobody_knows')
    expect(videoReasonText('', t, te)).toBe('')
  })

  it('keeps Google words of a failed clip apart', () => {
    expect(videoClipError({ error_code: 'video_interrupted', error: 'The app stopped' }, t, te))
      .toEqual({ text: t('video.errors.video_interrupted'), detail: '' })
    expect(videoClipError({ error: 'Google said no' }, t, te)).toEqual({ text: 'Google said no', detail: '' })
    expect(videoClipError(null, t, te)).toEqual({ text: '', detail: '' })
  })
})

describe('video locales', () => {
  const all = { en: flat(en), ru: flat(ru), uk: flat(uk) }
  const placeholders = (text) => [...String(text).matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort()

  it('have the same keys and placeholders', () => {
    for (const lang of ['ru', 'uk']) {
      expect(Object.keys(all[lang]).sort()).toEqual(Object.keys(all.en).sort())
      for (const [key, text] of Object.entries(all.en)) {
        expect(placeholders(all[lang][key]), `${lang} ${key}`).toEqual(placeholders(text))
      }
    }
  })

  it('names every code the API can send', () => {
    const needed = [
      ...VIDEO_ERROR_CODES.map((c) => `video.errors.${c}`),
      ...VIDEO_STATUSES.map((s) => `video.statuses.${s}`),
      ...VIDEO_STEP_STATUSES.map((s) => `video.stepStatuses.${s}`),
      ...VIDEO_PLAN_STATUSES.map((s) => `video.extend.plan.${s}`),
      ...VIDEO_CLIP_KINDS.flatMap((k) => [`video.player.kinds.${k}`, `video.player.making.${k}`, `video.jobs.${k}`]),
      ...VIDEO_WARNINGS.map((w) => `video.warnings.${w}`),
      ...VIDEO_CAMERA_GROUPS.map((g) => `video.cameraMove.groups.${g}`),
      ...Object.keys(en.video.cameraMove.moves).map((c) => `video.cameraMove.moves.${c}`),
      ...['tailSeconds', 'align', 'crossfade', 'researchDays']
        .flatMap((s) => [`video.settings.${s}.label`, `video.settings.${s}.help`]),
      ...['first', 'last'].flatMap((s) => ['title', 'hint', 'unsupported'].map((k) => `video.attach.${s}.${k}`)),
    ]
    for (const lang of Object.keys(all)) {
      const missing = needed.filter((k) => !all[lang][k])
      expect(missing, lang).toEqual([])
    }
  })
})

describe('video components', () => {
  const files = import.meta.glob('../components/video/*.vue')

  it('all compile', async () => {
    expect(Object.keys(files).length).toBeGreaterThanOrEqual(10)
    for (const [path, load] of Object.entries(files)) {
      const mod = await load()
      expect(mod.default, path).toBeTruthy()
    }
  })
})
