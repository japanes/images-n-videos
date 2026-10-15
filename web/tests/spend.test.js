import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  SPEND_DEFAULT_PERIOD, SPEND_KINDS, spendApiQuery, spendDebounce, spendDefaultFilters, spendFiltersFromQuery,
  spendFiltersToQuery, spendHasNarrowing, spendIsoDay, spendLabel, spendLabelEvery, spendMeterTone, spendNiceScale,
  spendParseDay, spendPeriodRange, spendPrettyJson, spendRefMatches, spendStack, spendTzOffset, spendUnitParts,
} from '../composables/useSpend.js'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const en = JSON.parse(readFileSync(join(ROOT, 'i18n', 'locales', 'en', 'spend.json'), 'utf8'))
const hasKey = (path) => path.split('.').reduce((o, k) => (o && typeof o === 'object' ? o[k] : undefined), en) !== undefined

// A fixed local "today": 15 Oct 2026, mid-day.
const TODAY = new Date(2026, 9, 15, 13, 30)

describe('days', () => {
  it('round-trips local days', () => {
    expect(spendIsoDay(new Date(2026, 0, 5))).toBe('2026-01-05')
    const d = spendParseDay('2026-02-28')
    expect([d.getFullYear(), d.getMonth(), d.getDate()]).toEqual([2026, 1, 28])
  })
  it('rejects bad days', () => {
    expect(spendParseDay('2026-02-30')).toBeNull()
    expect(spendParseDay('2026-2-3')).toBeNull()
    expect(spendParseDay('')).toBeNull()
    expect(spendParseDay(null)).toBeNull()
  })
  it('tz offset is minutes east of UTC', () => {
    const fake = { getTimezoneOffset: () => -180 }
    expect(spendTzOffset(fake)).toBe(180)
    expect(spendTzOffset({ getTimezoneOffset: () => 0 })).toBe(0)
  })
})

describe('periods', () => {
  it('presets count today in', () => {
    expect(spendPeriodRange('today', TODAY)).toEqual({ from: '2026-10-15', to: '2026-10-15' })
    expect(spendPeriodRange('7d', TODAY)).toEqual({ from: '2026-10-09', to: '2026-10-15' })
    expect(spendPeriodRange('30d', TODAY)).toEqual({ from: '2026-09-16', to: '2026-10-15' })
    expect(spendPeriodRange('90d', TODAY)).toEqual({ from: '2026-07-18', to: '2026-10-15' })
    expect(spendPeriodRange('month', TODAY)).toEqual({ from: '2026-10-01', to: '2026-10-15' })
    expect(spendPeriodRange('all', TODAY)).toEqual({ from: null, to: null })
  })
  it('custom range swaps reversed ends and drops bad ones', () => {
    expect(spendPeriodRange('custom', TODAY, { from: '2026-10-10', to: '2026-10-01' }))
      .toEqual({ from: '2026-10-01', to: '2026-10-10' })
    expect(spendPeriodRange('custom', TODAY, { from: 'x', to: '2026-10-01' })).toEqual({ from: null, to: '2026-10-01' })
  })
})

describe('filters and the URL', () => {
  it('defaults stay out of the URL', () => {
    expect(spendFiltersToQuery(spendDefaultFilters())).toEqual({})
    expect(spendFiltersFromQuery({})).toEqual(spendDefaultFilters())
    expect(spendDefaultFilters().period).toBe(SPEND_DEFAULT_PERIOD)
  })
  it('round-trips every field', () => {
    const f = {
      ...spendDefaultFilters(),
      period: 'custom', from: '2026-10-01', to: '2026-10-10', kind: 'video', status: 'error',
      model: 'veo-3.1-generate-001', purpose: 'video_clip', stub: true, refType: 'work', refId: 7, page: 3,
    }
    const q = spendFiltersToQuery(f)
    expect(q).toMatchObject({ period: 'custom', from: '2026-10-01', ref_type: 'work', ref_id: '7', stub: '1', page: '3' })
    expect(spendFiltersFromQuery(q)).toEqual(f)
  })
  it('ignores junk', () => {
    const f = spendFiltersFromQuery({ period: 'year', from: '2026-13-01', page: '-2', ref_id: '5', stub: 'yes' })
    expect(f.period).toBe(SPEND_DEFAULT_PERIOD)
    expect(f.from).toBe('')
    expect(f.page).toBe(1)
    expect(f.refId).toBeNull() // an id without a type means nothing
    expect(f.stub).toBe(false)
    expect(spendFiltersFromQuery({ kind: ['image', 'video'] }).kind).toBe('image')
  })
  it('builds the API query', () => {
    const f = { ...spendDefaultFilters(), period: '7d', kind: 'image', model: 'm', stub: true, refType: 'clip', refId: 4 }
    expect(spendApiQuery(f, { today: TODAY, tz: 120 })).toEqual({
      tz: 120, date_from: '2026-10-09', date_to: '2026-10-15', kind: 'image', model_id: 'm',
      include_stub: true, ref_type: 'clip', ref_id: 4,
    })
    expect(spendApiQuery({ ...spendDefaultFilters(), period: 'all' }, { today: TODAY, tz: 0 })).toEqual({ tz: 0 })
  })
  it('knows when the list is narrowed', () => {
    expect(spendHasNarrowing(spendDefaultFilters())).toBe(false)
    expect(spendHasNarrowing({ ...spendDefaultFilters(), purpose: 'frame' })).toBe(true)
  })
})

describe('chart geometry', () => {
  it('nice scale', () => {
    expect(spendNiceScale(0)).toEqual({ max: 1, step: 0.25, ticks: [0, 0.25, 0.5, 0.75, 1] })
    expect(spendNiceScale(7.3).ticks).toEqual([0, 2, 4, 6, 8])
    expect(spendNiceScale(0.9).max).toBe(1)
    expect(spendNiceScale(42).max).toBe(80)
    expect(spendNiceScale(100).max).toBe(100)
  })
  it('stacks in fixed kind order with a gap, total height true', () => {
    const segs = spendStack({ video: 2, image: 1, other: 0 }, 4, 100)
    expect(segs.map((s) => s.kind)).toEqual(['image', 'video'])
    expect(segs[0]).toMatchObject({ y0: 0, y1: 23, top: false })
    expect(segs[1]).toMatchObject({ y0: 25, y1: 75, top: true })
    expect(spendStack({}, 0, 100)).toEqual([])
    expect(SPEND_KINDS).toEqual(['image', 'video', 'text', 'other'])
  })
  it('thins day labels so they never collide', () => {
    expect(spendLabelEvery(7, 700)).toBe(1)
    expect(spendLabelEvery(90, 600)).toBe(8)
    expect(spendLabelEvery(0, 600)).toBe(1)
  })
  it('meter tone', () => {
    expect(spendMeterTone(10)).toBe('ok')
    expect(spendMeterTone(80)).toBe('warn')
    expect(spendMeterTone(130)).toBe('over')
    expect(spendMeterTone(null)).toBe('ok')
  })
})

describe('labels and details', () => {
  const t = (k) => `T:${k}`
  it('falls back to the raw key', () => {
    const te = (k) => k === 'spend.purposes.frame'
    expect(spendLabel(t, te, 'purposes', 'frame')).toBe('T:spend.purposes.frame')
    expect(spendLabel(t, te, 'purposes', 'new_thing')).toBe('new thing')
    expect(spendLabel(t, te, 'purposes', null)).toBe('—')
  })
  it('every kind, status and known purpose has a name', () => {
    for (const k of SPEND_KINDS) expect(hasKey(`spend.kinds.${k}`)).toBe(true)
    for (const s of ['success', 'error', 'blocked', 'cancelled', 'running']) expect(hasKey(`spend.statuses.${s}`)).toBe(true)
    for (const p of ['connection_check', 'models_check', 'frame', 'video_clip', 'video_extend']) {
      expect(hasKey(`spend.purposes.${p}`)).toBe(true)
    }
  })
  it('matches refs of a finished call', () => {
    expect(spendRefMatches([['work', 7], ['file', 3]], 'work', '7')).toBe(true)
    expect(spendRefMatches([['work', 7]], 'clip', 7)).toBe(false)
    expect(spendRefMatches(null, 'work', 7)).toBe(false)
  })
  it('unit parts use existing keys', () => {
    const parts = spendUnitParts({
      tokens_in: 12000, tokens_out: 300, tokens_thinking: 50, video_seconds: 8, input_video_seconds: 2.25, search_queries: 1,
    })
    expect(parts.map((p) => p[0])).toEqual([
      'spend.units.tokens', 'spend.units.thinking', 'spend.units.seconds', 'spend.units.inputSeconds', 'spend.units.searches',
    ])
    expect(parts[0][1].in).toMatch(/^12\s000$/) // thin space between thousands
    expect(parts[0][1].out).toBe('300')
    expect(parts[3][1]).toEqual({ n: '2.3' })
    for (const [key] of parts) expect(hasKey(key)).toBe(true)
    expect(spendUnitParts({})).toEqual([])
    expect(spendUnitParts({ output_video_seconds: 6 })).toEqual([['spend.units.seconds', { n: '6' }]])
  })
  it('pretty JSON', () => {
    expect(spendPrettyJson('{"a":1}')).toBe('{\n  "a": 1\n}')
    expect(spendPrettyJson({ b: [1] })).toBe('{\n  "b": [\n    1\n  ]\n}')
    expect(spendPrettyJson('not json')).toBe('not json')
    expect(spendPrettyJson(null)).toBe('')
  })
})

describe('debounce', () => {
  afterEach(() => vi.useRealTimers())
  it('runs once after the last call and can be cancelled', () => {
    vi.useFakeTimers()
    const fn = vi.fn()
    const run = spendDebounce(fn, 100)
    run(1)
    run(2)
    vi.advanceTimersByTime(99)
    expect(fn).not.toHaveBeenCalled()
    vi.advanceTimersByTime(1)
    expect(fn).toHaveBeenCalledTimes(1)
    expect(fn).toHaveBeenCalledWith(2)
    run(3)
    run.cancel()
    vi.advanceTimersByTime(500)
    expect(fn).toHaveBeenCalledTimes(1)
  })
})
