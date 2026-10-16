import { describe, expect, it } from 'vitest'
import {
  STUDIO_BLOCK_REASONS, STUDIO_BLOCKS, STUDIO_ERROR_CODES, STUDIO_SKIP_REASONS, STUDIO_SOURCES, STUDIO_STATUSES,
  STUDIO_TEXT_MODES, STUDIO_TEXT_ROLES, studioAspectRatio, studioBlocksMap, studioBoxFromPoints, studioBoxStyle,
  studioErrorText, studioEstimateRequest, studioEventMatches, studioFileThumb, studioFileUrl, studioFrameBusy,
  studioFrameError, studioFrameState, studioModelChoices, studioMoveIds, studioOverridesWith, studioReasonText,
  studioSizesFor, studioStyleSetting, studioStyleValue, studioTogglePicked, studioWorkProgress, studioWorkRevision,
} from '../utils/studioView.js'
import en from '../i18n/locales/en/studio.json'
import ru from '../i18n/locales/ru/studio.json'
import uk from '../i18n/locales/uk/studio.json'
import enCommon from '../i18n/locales/en/common.json'

const flat = (obj, prefix = '') => Object.fromEntries(Object.entries(obj).flatMap(([k, v]) => (
  v && typeof v === 'object' ? Object.entries(flat(v, `${prefix}${k}.`)) : [[`${prefix}${k}`, v]]
)))

// A tiny stand-in for vue-i18n over the real English texts.
const dict = { ...flat(en), ...flat(enCommon) }
const t = (key, params = {}) => (key in dict ? dict[key].replace(/\{(\w+)\}/g, (_, k) => params[k] ?? '') : key)
const te = (key) => key in dict

describe('frame state and progress', () => {
  it('tells waiting apart from drawing', () => {
    expect(studioFrameState({ status: 'drawing', waiting: true })).toBe('waiting')
    expect(studioFrameState({ status: 'drawing' })).toBe('drawing')
    expect(studioFrameState({ status: 'odd' })).toBe('empty')
    expect(studioFrameState(null)).toBe('empty')
  })

  it('knows busy frames', () => {
    expect(studioFrameBusy({ status: 'queued' })).toBe(true)
    expect(studioFrameBusy({ status: 'drawing' })).toBe(true)
    expect(studioFrameBusy({ status: 'done' })).toBe(false)
  })

  it('counts pictures, busy frames and errors', () => {
    const work = {
      frames: [
        { status: 'done', file_id: 1 }, { status: 'drawing', file_id: 2 }, { status: 'error' }, { status: 'empty' },
      ],
    }
    expect(studioWorkProgress(work)).toEqual({ done: 2, total: 4, busy: 1, errors: 1 })
    expect(studioWorkProgress(null)).toEqual({ done: 0, total: 0, busy: 0, errors: 0 })
  })
})

describe('models and sizes', () => {
  it('takes sizes from the model caps', () => {
    expect(studioSizesFor({ caps: { allowed_resolutions: ['4K', '1K', '8K'] } })).toEqual(['1K', '4K'])
    expect(studioSizesFor({ caps: {} })).toEqual(['1K'])
    expect(studioSizesFor(null)).toEqual(['1K'])
  })

  it('offers only enabled image models', () => {
    const list = [
      { id: 'a', kind: 'image' }, { id: 'b', kind: 'video' }, { id: 'c', kind: 'image', enabled: false },
      { id: 'd', kind: 'image', removed: true },
    ]
    expect(studioModelChoices(list).map((m) => m.id)).toEqual(['a'])
  })

  it('turns an aspect into CSS', () => {
    expect(studioAspectRatio('4:5')).toBe('4 / 5')
    expect(studioAspectRatio('bad')).toBe('1 / 1')
  })

  it('builds file links', () => {
    expect(studioFileUrl(7)).toBe('/files/7')
    expect(studioFileThumb(7, 200)).toBe('/files/7?w=200')
    expect(studioFileUrl(null)).toBe('')
  })
})

describe('lists and boxes', () => {
  it('moves ids without touching the input', () => {
    const ids = [1, 2, 3]
    expect(studioMoveIds(ids, 0, 2)).toEqual([2, 3, 1])
    expect(studioMoveIds(ids, 0, 5)).toEqual([1, 2, 3])
    expect(ids).toEqual([1, 2, 3])
  })

  it('toggles picked ids up to a limit', () => {
    expect(studioTogglePicked([1, 2], 2)).toEqual([1])
    expect(studioTogglePicked([1], 2, 2)).toEqual([1, 2])
    expect(studioTogglePicked([1, 2], 3, 2)).toEqual([1, 2])
  })

  it('makes a box from two points in any order', () => {
    expect(studioBoxFromPoints({ x: 0.8, y: 0.6 }, { x: 0.2, y: 0.1 })).toEqual({ x: 0.2, y: 0.1, w: 0.6, h: 0.5 })
    expect(studioBoxFromPoints({ x: -1, y: 0 }, { x: 2, y: 0.5 })).toEqual({ x: 0, y: 0, w: 1, h: 0.5 })
    expect(studioBoxFromPoints({ x: 0.5, y: 0.5 }, { x: 0.501, y: 0.9 })).toBeNull()
  })

  it('places a box with percents', () => {
    expect(studioBoxStyle({ x: 0.1, y: 0.2, w: 0.3, h: 0.4 })).toEqual({
      left: '10%', top: '20%', width: '30%', height: '40%',
    })
    expect(studioBoxStyle(null)).toEqual({ display: 'none' })
  })
})

describe('settings helpers', () => {
  it('reads and writes the style setting', () => {
    expect(studioStyleValue({ preset: 5, title: 'Film' })).toEqual({ kind: 'library', id: 5, title: 'Film' })
    expect(studioStyleValue('soft pastel')).toEqual({ kind: 'words', text: 'soft pastel' })
    expect(studioStyleValue('')).toBeNull()
    expect(studioStyleSetting({ kind: 'library', id: 5, title: 'Film' })).toEqual({ preset: 5, title: 'Film' })
    expect(studioStyleSetting({ kind: 'words', text: '  ' })).toBeNull()
    expect(studioStyleSetting(null)).toBeNull()
  })

  it('sets and drops frame overrides', () => {
    const base = { model_id: 'm', image_size: '2K' }
    expect(studioOverridesWith(base, 'image_size', undefined)).toEqual({ model_id: 'm' })
    expect(studioOverridesWith(base, 'feedback', 'x')).toEqual({ ...base, feedback: 'x' })
    expect(base).toEqual({ model_id: 'm', image_size: '2K' })
  })

  it('sends the full blocks map', () => {
    expect(studioBlocksMap([{ code: 'logo', on: false }, { code: 'quality', on: 1 }])).toEqual({ logo: false, quality: true })
  })

  it('puts revisions into price requests', () => {
    const frame = { id: 3, updated_at: 't2', status: 'done' }
    const work = { id: 1, updated_at: 't1', frames: [frame] }
    const req = studioEstimateRequest('frame', { work, frame, extra: 1 })
    expect(req).toMatchObject({ action: 'frame', work_id: 1, frame_id: 3, extra: 1, frame_rev: 't2:done' })
    expect(req.rev).toBe(studioWorkRevision(work))
    expect(studioWorkRevision({ ...work, frames: [{ ...frame, status: 'queued' }] })).not.toBe(req.rev)
  })

  it('matches events of its own work', () => {
    expect(studioEventMatches({ work_id: '4' }, 4)).toBe(true)
    expect(studioEventMatches({ work_id: 5 }, 4)).toBe(false)
    expect(studioEventMatches(null, 4)).toBe(false)
  })
})

describe('error texts', () => {
  it('uses the studio texts with details', () => {
    expect(studioErrorText({ code: 'too_many_frames', details: { max: 10 } }, t, te)).toBe('A work has from 1 to 10 frames.')
  })

  it('falls back to the app-wide texts', () => {
    expect(studioErrorText({ code: 'bad_request' }, t, te)).toBe(dict['errors.bad_request'])
  })

  it('explains skip reasons and frame codes', () => {
    expect(studioReasonText('pilot_not_ready', t, te)).toBe(dict['studio.skip.pilot_not_ready'])
    expect(studioReasonText('brief_required', t, te)).toBe(dict['studio.errors.brief_required'])
    expect(studioReasonText('who_knows', t, te)).toBe('who_knows')
  })

  it('keeps Google words as a detail and hides our English copies', () => {
    expect(studioFrameError({ error_code: 'safety_blocked', error_text: 'Blocked: SAFETY' }, t, te))
      .toEqual({ text: dict['errors.safety_blocked'], detail: 'Blocked: SAFETY' })
    expect(studioFrameError({ error_code: 'brief_required', error_text: 'Write what the picture should show' }, t, te))
      .toEqual({ text: dict['studio.errors.brief_required'], detail: '' })
    expect(studioFrameError({ error_code: 'google_new_code', error_text: 'Raw text' }, t, te))
      .toEqual({ text: 'Raw text', detail: '' })
  })
})

describe('studio locales', () => {
  const all = { en: flat(en), ru: flat(ru), uk: flat(uk) }
  const placeholders = (s) => [...String(s).matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort()

  it('has the same keys and placeholders in every language', () => {
    for (const lang of ['ru', 'uk']) {
      expect(Object.keys(all[lang]).sort()).toEqual(Object.keys(all.en).sort())
      for (const [key, text] of Object.entries(all.en)) {
        expect(placeholders(all[lang][key]), `${lang} ${key}`).toEqual(placeholders(text))
      }
    }
  })

  it('names every code the API can send', () => {
    const needed = [
      ...STUDIO_ERROR_CODES.map((c) => `studio.errors.${c}`),
      ...STUDIO_BLOCK_REASONS.map((r) => `studio.reasons.${r}`),
      ...STUDIO_SKIP_REASONS.map((r) => `studio.skip.${r}`),
      ...STUDIO_BLOCKS.flatMap((b) => [`studio.blocks.${b}.name`, `studio.blocks.${b}.hint`]),
      ...STUDIO_STATUSES.map((s) => `studio.statuses.${s}`),
      ...STUDIO_TEXT_MODES.flatMap((m) => [`studio.textModes.${m}.name`, `studio.textModes.${m}.hint`]),
      ...STUDIO_TEXT_ROLES.map((r) => `studio.textRoles.${r}`),
      ...STUDIO_SOURCES.map((s) => `studio.sources.${s}`),
      ...['full', 'edit', 'source'].map((m) => `studio.versionModes.${m}`),
      ...['subject', 'logo', 'element', 'anchor', 'reference', 'style_sample', 'attachment', 'edit_base', 'edit_marker']
        .map((r) => `studio.roles.${r}`),
      'studio.jobs.frame',
    ]
    for (const lang of Object.keys(all)) {
      const missing = needed.filter((k) => !all[lang][k])
      expect(missing, lang).toEqual([])
    }
  })
})

describe('studio components', () => {
  const files = import.meta.glob('../components/studio/*.vue')

  it('all compile', async () => {
    expect(Object.keys(files).length).toBeGreaterThanOrEqual(10)
    for (const [path, load] of Object.entries(files)) {
      const mod = await load()
      expect(mod.default, path).toBeTruthy()
    }
  })
})
