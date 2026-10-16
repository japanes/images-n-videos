import { describe, expect, it } from 'vitest'
import {
  CLIP_ASPECTS, CLIP_CROP_MODES, CLIP_MAX_CUTS, CLIP_MAX_IMAGE_LAYERS, CLIP_MAX_LAYERS, CLIP_STT_LANGUAGES,
  CLIP_TRACK_ROLES, clipActiveJobs, clipAddRemoved, clipBrandFonts, clipCanAddLayer, clipCaptionAt,
  clipCreateHistory, clipEditorRoute, clipEffectivePreset, clipErrorText, clipFormatTime, clipFrameSize,
  clipGroupLines, clipLayerActive, clipLuma, clipMove, clipNextKept, clipOutputDuration, clipParseTime,
  clipPartPoints, clipProjectRoute, clipRemovedAt, clipReplaceLine, clipResolveBrand, clipRetimeLine,
  clipRoundSeconds, clipSegments, clipTextStyle, clipToggleCut, clipToOutput,
} from '../utils/clipState.js'
import en from '../i18n/locales/en/clip.json'
import ru from '../i18n/locales/ru/clip.json'
import uk from '../i18n/locales/uk/clip.json'
import enCommon from '../i18n/locales/en/common.json'

const flat = (obj, prefix = '') => Object.fromEntries(Object.entries(obj).flatMap(([k, v]) => (
  v && typeof v === 'object' ? Object.entries(flat(v, `${prefix}${k}.`)) : [[`${prefix}${k}`, v]]
)))

// A tiny stand-in for vue-i18n over the real English texts.
const dict = { ...flat(en), ...flat(enCommon) }
const t = (key, params = {}) => (key in dict ? dict[key].replace(/\{(\w+)\}/g, (_, k) => params[k] ?? '') : key)
const te = (key) => key in dict

describe('routes', () => {
  it('opens the editor for a file or a project', () => {
    expect(clipEditorRoute(12)).toBe('/clip/new?file=12')
    expect(clipProjectRoute(3)).toBe('/clip/3')
  })
})

describe('time', () => {
  it('formats and parses times', () => {
    expect(clipFormatTime(65.25)).toBe('1:05.2')
    expect(clipFormatTime(3725)).toBe('1:02:05.0')
    expect(clipFormatTime(59.96, { tenths: false })).toBe('1:00')
    expect(clipFormatTime(-3)).toBe('0:00.0')
    expect(clipParseTime('1:05.2')).toBe(65.2)
    expect(clipParseTime('65,5')).toBe(65.5)
    expect(clipParseTime('1:02:05')).toBe(3725)
    expect(clipParseTime('')).toBeNull()
    expect(clipParseTime('abc')).toBeNull()
    expect(clipParseTime('1:2:3:4')).toBeNull()
  })

  it('rounds the time estimate', () => {
    expect(clipRoundSeconds(3)).toBe(5)
    expect(clipRoundSeconds(40)).toBe(40)
    expect(clipRoundSeconds(95)).toBe(100)
    expect(clipRoundSeconds(610)).toBe(600)
  })
})

describe('edit list', () => {
  const state = { trim: { start: 1, end: 10 }, removed: [[6, 7], [3, 4]], cuts: [] }
  const segs = clipSegments(state, 20)

  it('keeps trim minus removed ranges', () => {
    expect(segs).toEqual([[1, 3], [4, 6], [7, 10]])
    expect(clipOutputDuration(segs)).toBe(7)
    expect(clipSegments({ trim: { start: 0, end: null }, removed: [] }, 20)).toEqual([[0, 20]])
    expect(clipSegments({ trim: { start: 1, end: 10 }, removed: [[0, 2]] }, 20)).toEqual([[2, 10]])
    // a sliver shorter than the minimum piece is dropped
    expect(clipSegments({ trim: { start: 0, end: 10 }, removed: [[3, 9.97]] }, 20)).toEqual([[0, 3]])
    expect(clipSegments({ trim: { start: 0, end: 10 }, removed: [[0, 10]] }, 20)).toEqual([])
  })

  it('maps source time to result time', () => {
    expect(clipToOutput(1, segs)).toBe(0)
    expect(clipToOutput(5, segs)).toBe(3)
    expect(clipToOutput(3.5, segs)).toBeNull()
    expect(clipNextKept(2, segs)).toBe(2)
    expect(clipNextKept(3.5, segs)).toBe(4)
    expect(clipNextKept(11, segs)).toBeNull()
  })

  it('merges removed ranges', () => {
    const removed = [[1, 2]]
    expect(clipAddRemoved(removed, 1.5, 3)).toEqual([[1, 3]])
    expect(clipAddRemoved(removed, 5, 4)).toEqual([[1, 2], [4, 5]])
    const same = clipAddRemoved(removed, 5, 5.01)
    expect(same).toEqual(removed)
    expect(same).not.toBe(removed)
    expect(clipRemovedAt([[1, 2], [4, 5]], 4.5)).toBe(1)
    expect(clipRemovedAt([[1, 2], [4, 5]], 3)).toBe(-1)
  })

  it('toggles split marks and moves them to result time', () => {
    expect(clipToggleCut([2], 5)).toEqual([2, 5])
    expect(clipToggleCut([2, 5], 5.1)).toEqual([2])
    const full = Array.from({ length: CLIP_MAX_CUTS }, (_, i) => i)
    expect(clipToggleCut(full, 100)).toHaveLength(CLIP_MAX_CUTS)
    // 3.5 is cut away, 9.99 is too close to the end
    expect(clipPartPoints([9.99, 5, 3.5, 2], segs)).toEqual([1, 3])
  })

  it('works out the frame size', () => {
    expect(clipFrameSize({ crop: { aspect: '9:16' } }, { width: 640, height: 360 })).toEqual({ width: 1080, height: 1920 })
    expect(clipFrameSize({ crop: { aspect: '' } }, { width: 1281, height: 721 })).toEqual({ width: 1280, height: 720 })
    expect(clipFrameSize({}, {})).toEqual({ width: 1920, height: 1080 })
  })
})

describe('layers', () => {
  it('moves items and respects limits', () => {
    expect(clipMove(['a', 'b', 'c'], 0, 1)).toEqual(['b', 'a', 'c'])
    expect(clipMove(['a', 'b'], 0, -1)).toEqual(['a', 'b'])
    const images = Array.from({ length: CLIP_MAX_IMAGE_LAYERS }, () => ({ type: 'image' }))
    expect(clipCanAddLayer(images, 'image')).toBe(false)
    expect(clipCanAddLayer(images, 'text')).toBe(true)
    const many = Array.from({ length: CLIP_MAX_LAYERS }, () => ({ type: 'text' }))
    expect(clipCanAddLayer(many, 'text')).toBe(false)
  })

  it('knows when a layer is on screen', () => {
    expect(clipLayerActive({ start: 1, end: null, visible: true }, 5)).toBe(true)
    expect(clipLayerActive({ start: 1, end: 3, visible: true }, 4)).toBe(false)
    expect(clipLayerActive({ start: 1, end: null, visible: false }, 5)).toBe(false)
  })

  it('sizes text the way libass does', () => {
    const style = clipTextStyle({ size: 0.058, plate: true, plate_color: '#FF0000', plate_opacity: 0.5 }, 1160)
    expect(parseFloat(style.fontSize)).toBeCloseTo(58, 5)
    expect(style.background).toBe('rgba(255,0,0,0.5)')
  })
})

describe('subtitles', () => {
  const words = [
    { text: 'Hello', start: 0, end: 0.4 },
    { text: 'world.', start: 0.5, end: 0.9 },
    { text: 'Next', start: 1, end: 1.2 },
    { text: 'one', start: 3, end: 3.3 },
  ]

  it('groups words into lines', () => {
    expect(clipGroupLines(words, 4).map((l) => l.map((w) => w.text))).toEqual([['Hello', 'world.'], ['Next'], ['one']])
    expect(clipGroupLines(words.slice(0, 2), 1)).toHaveLength(2)
  })

  it('shows the caption under the play head', () => {
    const at = clipCaptionAt(words, 0.6)
    expect(at.words.map((w) => w.text)).toEqual(['Hello', 'world.'])
    expect(at.lit).toBe(1)
    expect(clipCaptionAt(words, 2.5)).toBeNull()
    expect(clipCaptionAt(words, 0.45, { mode: 'word' }).words[0].text).toBe('Hello')
    expect(clipCaptionAt([], 1)).toBeNull()
  })

  it('edits a line', () => {
    const line = words.slice(0, 2)
    expect(clipRetimeLine(line, 'Hi there')).toEqual([
      { text: 'Hi', start: 0, end: 0.4 }, { text: 'there', start: 0.5, end: 0.9 },
    ])
    const three = clipRetimeLine(line, 'one two three')
    expect(three).toHaveLength(3)
    expect(three[0].start).toBe(0)
    expect(three[2].end).toBeCloseTo(0.9, 3)
    expect(clipRetimeLine(line, '   ')).toEqual([])
    const replaced = clipReplaceLine(words, 4, 0, 'Hi there')
    expect(replaced.map((w) => w.text)).toEqual(['Hi', 'there', 'Next', 'one'])
    expect(clipReplaceLine(words, 4, 9, 'x')).toEqual(words)
  })

  it('applies position and mode over the preset', () => {
    const preset = { alignment: 2, margin_v_ratio: 0.08, mode: 'line' }
    expect(clipEffectivePreset(preset, { position: 'top', mode: 'word' })).toMatchObject({ alignment: 8, margin_v_ratio: 0.08, mode: 'word' })
    expect(clipEffectivePreset(preset, { position: 'middle' })).toMatchObject({ alignment: 5, margin_v_ratio: 0, mode: 'line' })
    expect(clipEffectivePreset(null, {})).toBeNull()
  })

  it('folds the brand kit into a brand preset', () => {
    const brand = {
      fonts: [
        { family: 'Body', file_id: 2, category: 'body' },
        { family: 'Head', file_id: 1, category: 'display' },
        { family: 'NoFile', category: 'display' },
      ],
      colors: [{ hex: '#FF0000' }, { hex: '#101010' }],
    }
    expect(clipBrandFonts(brand).map((f) => f.family)).toEqual(['Head', 'Body'])
    expect(clipResolveBrand({ use_brand: true }, brand)).toMatchObject({
      font_family: 'Head', font_file_id: 1, highlight_color: '#FF0000', outline_color: '#101010',
    })
    const plain = { use_brand: false }
    expect(clipResolveBrand(plain, brand)).toBe(plain)
    expect(clipLuma('#FFFFFF')).toBeCloseTo(1, 5)
    expect(clipLuma('#000000')).toBe(0)
    expect(clipLuma('bad')).toBe(0)
  })
})

describe('undo history', () => {
  it('undoes, redoes and forgets the oldest steps', () => {
    const h = clipCreateHistory(2)
    h.reset({ a: 1 })
    expect(h.canUndo()).toBe(false)
    const live = { a: 2 }
    expect(h.push(live)).toBe(true)
    expect(h.push({ a: 2 })).toBe(false)
    live.a = 99 // the snapshot must not change with the live state
    h.push({ a: 3 })
    h.push({ a: 4 })
    expect(h.size()).toBe(3)
    expect(h.undo()).toEqual({ a: 3 })
    expect(h.undo()).toEqual({ a: 2 })
    expect(h.undo()).toBeNull()
    expect(h.canRedo()).toBe(true)
    expect(h.redo()).toEqual({ a: 3 })
    h.push({ a: 5 })
    expect(h.canRedo()).toBe(false)
  })
})

describe('jobs and errors', () => {
  it('finds running jobs of a project', () => {
    const jobs = [
      { id: 1, ref_type: 'clip', ref_id: 7, kind: 'clip.export', status: 'running' },
      { id: 2, ref_type: 'clip', ref_id: 7, kind: 'clip.export', status: 'done' },
      { id: 3, ref_type: 'clip', ref_id: 7, kind: 'clip.preview', status: 'queued' },
      { id: 4, ref_type: 'clip', ref_id: 8, kind: 'clip.export', status: 'running' },
      { id: 5, ref_type: 'video', ref_id: 7, kind: 'clip.export', status: 'running' },
    ]
    expect(clipActiveJobs(jobs, 7).map((j) => j.id)).toEqual([3, 1])
    expect(clipActiveJobs(jobs, '7', 'clip.export').map((j) => j.id)).toEqual([1])
  })

  it('turns errors into plain text', () => {
    expect(clipErrorText({ code: 'clip_too_many_pieces', details: { max: 24 } }, t, te)).toContain('24')
    // a failed job carries error_code / error instead of code / message
    expect(clipErrorText({ error_code: 'stt_busy', error: 'busy' }, t, te)).toBe(en.clip.errors.stt_busy)
    expect(clipErrorText({ error_code: 'weird', error: 'Raw text' }, t, te)).toBe('Raw text')
  })
})

describe('clip locales', () => {
  const all = { en: flat(en), ru: flat(ru), uk: flat(uk) }
  const presets = ['clean', 'boxed', 'pop', 'brand']

  it('has every key the code builds on the fly', () => {
    const needed = [
      ...['source', 'vertical', 'square', 'portrait', 'wide'].map((a) => `clip.aspects.${a}`),
      ...CLIP_CROP_MODES.map((m) => `clip.cropModes.${m}`),
      ...CLIP_TRACK_ROLES.flatMap((r) => [`clip.audio.roles.${r}`, `clip.audio.roleHint.${r}`]),
      ...CLIP_STT_LANGUAGES.map((l) => `clip.stt.languages.${l}`),
      ...['turbo', 'small'].flatMap((m) => [`clip.stt.models.${m}`, `clip.stt.modelHint.${m}`]),
      ...['starting', 'downloading', 'decoding', 'loading', 'transcribing', 'done'].map((p) => `clip.stt.phase.${p}`),
      ...presets.flatMap((p) => [`clip.presets.${p}.name`, `clip.presets.${p}.text`]),
      ...['saved', 'saving', 'unsaved', 'failed'].map((s) => `clip.page.save.${s}`),
      ...['layers', 'subtitles', 'audio', 'export'].map((s) => `clip.tabs.${s}`),
      ...['image_skipped', 'too_many_overlays'].map((w) => `clip.export.warnings.${w}`),
      ...['not_video', 'file_missing', 'title_empty', 'no_brand', 'empty', 'too_many_pieces', 'no_duration',
        'stt_model', 'stt_language'].map((c) => `clip.errors.clip_${c}`),
      ...['model', 'language', 'speedTurbo', 'speedSmall'].flatMap((s) => [`clip.settings.${s}.label`, `clip.settings.${s}.help`]),
      'clip.jobs.export', 'clip.jobs.preview', 'clip.jobs.transcribe',
    ]
    expect(CLIP_ASPECTS).toHaveLength(5)
    for (const lang of Object.keys(all)) {
      const missing = needed.filter((k) => !all[lang][k])
      expect(missing, lang).toEqual([])
    }
  })
})

describe('clip components', () => {
  const files = import.meta.glob('../components/clip/*.vue')

  it('all compile', async () => {
    expect(Object.keys(files).length).toBeGreaterThanOrEqual(10)
    for (const [path, load] of Object.entries(files)) {
      const mod = await load()
      expect(mod.default, path).toBeTruthy()
    }
  })
})
