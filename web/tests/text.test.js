import { describe, expect, it } from 'vitest'
import {
  TEXT_ALIGNS, TEXT_BUILTIN_LAYOUTS, TEXT_ERROR_CODES, TEXT_LANGUAGES, TEXT_MAX_BACKGROUNDS, TEXT_MAX_LAYERS,
  TEXT_MAX_TEXT, TEXT_MAX_TEXTS, TEXT_MAX_VARIANTS, TEXT_MIN_SIDE, TEXT_PLACE_SOURCES, TEXT_ROLES, TEXT_SHAPES,
  TEXT_SIZES, TEXT_TABS, TEXT_VERTICALS, textBackgroundError, textBackgroundsBody, textBackgroundsBusy, textBindTexts,
  textBoxStyle, textCanAddBlock, textCanAddLayer, textClampBox, textDefaultLanguage, textEmptyForms, textErrorText,
  textEstimateQuery, textFontShare, textFreeId, textHumanizeBody, textJobRoute, textLayerLabel, textLayoutTemplate,
  textLayoutTitle, textMoveBox, textMoveLayer, textNewBlock, textNewLogoLayer, textNewShapeLayer, textNewTextLayer,
  textParseReport, textPatchLayer, textPlaceBody, textPlacePrice, textPlaceSummary, textPrice, textPutVariant,
  textReasonText, textRemoveBlock, textRemoveLayer, textReportNotes, textResizeBox, textUnplaced, textVariantsBody,
  textVariantsReady, textWriteBody,
} from '../utils/textView.js'
import en from '../i18n/locales/en/text.json'
import ru from '../i18n/locales/ru/text.json'
import uk from '../i18n/locales/uk/text.json'
import enChat from '../i18n/locales/en/chat.json'
import enCommon from '../i18n/locales/en/common.json'
import enSpend from '../i18n/locales/en/spend.json'
import enMedia from '../i18n/locales/en/media.json'

const flat = (obj, prefix = '') => Object.fromEntries(Object.entries(obj).flatMap(([k, v]) => (
  v && typeof v === 'object' ? Object.entries(flat(v, `${prefix}${k}.`)) : [[`${prefix}${k}`, v]]
)))

// A tiny stand-in for vue-i18n over the real English texts.
const dict = { ...flat(en), ...flat(enChat), ...flat(enCommon) }
const t = (key, params = {}) => (key in dict ? dict[key].replace(/\{(\w+)\}/g, (_, k) => params[k] ?? '') : key)
const te = (key) => key in dict

const box = (x, y, w, h) => ({ x, y, w, h })

describe('texts', () => {
  it('has the same keys in every language', () => {
    const keys = Object.keys(flat(en)).sort()
    expect(Object.keys(flat(ru)).sort()).toEqual(keys)
    expect(Object.keys(flat(uk)).sort()).toEqual(keys)
  })

  it('has a text for every code the tool shows', () => {
    for (const code of TEXT_ERROR_CODES) expect(te(`text.errors.${code}`), code).toBe(true)
    for (const code of TEXT_BUILTIN_LAYOUTS) expect(te(`text.layouts.${code}`), code).toBe(true)
    for (const s of TEXT_PLACE_SOURCES) expect(te(`text.place.sources.${s}`), s).toBe(true)
    for (const tab of TEXT_TABS) expect(te(`text.tabs.${tab}`), tab).toBe(true)
    for (const r of TEXT_ROLES) {
      expect(te(`text.roles.${r}`), r).toBe(true)
      expect(te(`text.words.placeholder.${r}`), r).toBe(true)
    }
    for (const x of TEXT_SIZES) expect(te(`text.sizes.${x}`), x).toBe(true)
    for (const x of TEXT_ALIGNS) expect(te(`text.aligns.${x}`), x).toBe(true)
    for (const x of TEXT_VERTICALS) expect(te(`text.verticals.${x}`), x).toBe(true)
    for (const x of TEXT_LANGUAGES) expect(te(`text.languages.${x}`), x).toBe(true)
    for (const x of TEXT_SHAPES) expect(te(`text.layers.${x}`), x).toBe(true)
    for (const x of ['queued', 'running', 'done', 'error', 'cancelled']) expect(te(`text.generate.status.${x}`), x).toBe(true)
    for (const x of ['place', 'write', 'variants', 'humanize', 'backgrounds']) expect(te(`text.preview.steps.${x}`), x).toBe(true)
  })

  it('uses «|» only between plural forms', () => {
    for (const [key, value] of Object.entries(flat(en))) {
      expect(value.split('|').length, key).toBe(value.split(' | ').length)
      if (value.includes(' | ')) expect(value.split(' | ').length, key).toBe(2)
    }
  })

  it('names the spend purposes, the spend link and the library usage of the module', () => {
    for (const p of ['text_placement', 'text_write', 'text_variants', 'text_humanize', 'text_background']) {
      expect(enSpend.spend.purposes[p], p).toBeTruthy()
    }
    expect(enSpend.spend.refTypes.text_design).toBeTruthy()
    expect(enMedia.media.usageTypes.text).toBeTruthy()
  })
})

describe('words', () => {
  it('writes in the interface language when it can', () => {
    expect(textDefaultLanguage('uk-UA')).toBe('uk')
    expect(textDefaultLanguage('ru')).toBe('ru')
    expect(textDefaultLanguage('de')).toBe('en')
    expect(textDefaultLanguage(null)).toBe('en')
  })

  it('gives free ids', () => {
    expect(textFreeId([], 't')).toBe('t1')
    expect(textFreeId([{ id: 't2' }], 't')).toBe('t3')
    expect(textFreeId([{ id: 't1' }, { id: 't3' }], 't')).toBe('t4')
    expect(textFreeId([{ id: 't3' }, { id: 't4' }], 't')).toBe('t5')
  })

  it('makes a new block with the role size and stops at the limit', () => {
    expect(textNewBlock([], 'headline')).toEqual({ id: 't1', role: 'headline', text: '', size: 'xl', locked: false })
    expect(textNewBlock([], 'nonsense').role).toBe('body')
    const full = Array.from({ length: TEXT_MAX_TEXTS }, (_, i) => ({ id: `t${i + 1}` }))
    expect(textCanAddBlock(full)).toBe(false)
    expect(textCanAddBlock(full.slice(1))).toBe(true)
  })

  it('removes a block together with the text layers that show it', () => {
    const texts = [{ id: 't1' }, { id: 't2' }]
    const layers = [
      { id: 'l1', type: 'text', block_id: 't1' }, { id: 'l2', type: 'text', block_id: 't2' },
      { id: 'l3', type: 'logo' }, { id: 'l4', type: 'text', block_id: null },
    ]
    const out = textRemoveBlock(texts, layers, 't1')
    expect(out.texts.map((x) => x.id)).toEqual(['t2'])
    expect(out.layers.map((l) => l.id)).toEqual(['l2', 'l3', 'l4'])
  })

  it('shows the words of a block on its layers and lets go of lost blocks', () => {
    const texts = [{ id: 't1', role: 'headline', text: 'Sale' }]
    const layers = [
      { id: 'l1', type: 'text', block_id: 't1', text: 'old', role: 'body' },
      { id: 'l2', type: 'text', block_id: 't9', text: 'own' },
      { id: 'l3', type: 'shape' },
    ]
    const out = textBindTexts(layers, texts)
    expect(out[0]).toMatchObject({ text: 'Sale', role: 'headline' })
    expect(out[1]).toMatchObject({ block_id: null, text: 'own' })
    expect(out[2]).toBe(layers[2])
  })

  it('finds blocks with words and no layer', () => {
    const texts = [{ id: 't1', text: 'A' }, { id: 't2', text: '  ' }, { id: 't3', text: 'C' }]
    const layers = [{ id: 'l1', type: 'text', block_id: 't1' }]
    expect(textUnplaced(texts, layers).map((x) => x.id)).toEqual(['t3'])
  })

  it('puts a variant into one block, cut to the limit', () => {
    const out = textPutVariant([{ id: 't1', text: 'a' }, { id: 't2', text: 'b' }], 't2', 'x'.repeat(TEXT_MAX_TEXT + 5))
    expect(out[0].text).toBe('a')
    expect(out[1].text).toHaveLength(TEXT_MAX_TEXT)
  })
})

describe('layers', () => {
  it('makes a text layer tied to a block, bold for a headline', () => {
    const l = textNewTextLayer([{ id: 'l1' }], { id: 't2', role: 'headline', text: 'Hi', size: 'lg' }, { file_id: 7, family: 'Inter' })
    expect(l).toMatchObject({ id: 'l2', type: 'text', block_id: 't2', text: 'Hi', size: 'lg', bold: true, font: { file_id: 7, family: 'Inter' } })
    const plain = textNewTextLayer([])
    expect(plain).toMatchObject({ block_id: null, role: 'body', size: 'md', bold: false, font: null })
  })

  it('makes logo and shape layers', () => {
    expect(textNewLogoLayer([], 5)).toMatchObject({ id: 'l1', type: 'logo', file_id: 5 })
    expect(textNewShapeLayer([], 'ellipse').shape).toBe('ellipse')
    expect(textNewShapeLayer([], 'star').shape).toBe('rect')
    const full = Array.from({ length: TEXT_MAX_LAYERS }, (_, i) => ({ id: `l${i + 1}` }))
    expect(textCanAddLayer(full)).toBe(false)
  })

  it('changes one layer and keeps its box inside the picture', () => {
    const layers = [{ id: 'l1', ...box(0.1, 0.1, 0.2, 0.2) }, { id: 'l2', ...box(0, 0, 0.5, 0.5) }]
    const out = textPatchLayer(layers, 'l1', { x: 0.95, color: '#000' })
    expect(out[0]).toMatchObject({ x: 0.8, color: '#000' })
    expect(out[1]).toBe(layers[1])
    expect(textRemoveLayer(layers, 'l1').map((l) => l.id)).toEqual(['l2'])
  })

  it('moves a layer up and down and stops at the ends', () => {
    const layers = [{ id: 'a' }, { id: 'b' }, { id: 'c' }]
    expect(textMoveLayer(layers, 'a', 1).map((l) => l.id)).toEqual(['b', 'a', 'c'])
    expect(textMoveLayer(layers, 'c', -1).map((l) => l.id)).toEqual(['a', 'c', 'b'])
    expect(textMoveLayer(layers, 'c', 1).map((l) => l.id)).toEqual(['a', 'b', 'c'])
    expect(textMoveLayer(layers, 'x', 1).map((l) => l.id)).toEqual(['a', 'b', 'c'])
  })

  it('keeps boxes, not words, in a layout of one\'s own', () => {
    const out = textLayoutTemplate([{ id: 'l1', type: 'text', text: 'Hi', block_id: 't1', x: 0.1 }, { id: 'l2', type: 'logo' }])
    expect(out[0]).toMatchObject({ text: '', block_id: null, x: 0.1 })
    expect(out[1]).toEqual({ id: 'l2', type: 'logo' })
  })

  it('names layouts and layers', () => {
    expect(textLayoutTitle({ code: 'top_title', builtin: true }, t, te)).toBe('Headline at the top')
    expect(textLayoutTitle({ code: null, title: 'Mine', builtin: false }, t, te)).toBe('Mine')
    expect(textLayerLabel({ type: 'text', text: '  Big\n sale ' }, t)).toBe('Big sale')
    expect(textLayerLabel({ type: 'text', text: 'x'.repeat(40) }, t)).toBe(`${'x'.repeat(31)}…`)
    expect(textLayerLabel({ type: 'text', text: '' }, t)).toBe('Empty text')
    expect(textLayerLabel({ type: 'logo' }, t)).toBe('Logo')
    expect(textLayerLabel({ type: 'shape', shape: 'ellipse' }, t)).toBe('Ellipse')
  })
})

describe('box math', () => {
  it('keeps a box inside the picture with a smallest side', () => {
    expect(textClampBox(box(-1, 2, 5, 0))).toEqual(box(0, 1 - TEXT_MIN_SIDE, 1, TEXT_MIN_SIDE))
    expect(textClampBox(box(0.1, 0.2, 0.3, 0.4))).toEqual(box(0.1, 0.2, 0.3, 0.4))
  })

  it('moves a box and stops it at the edges', () => {
    expect(textMoveBox(box(0.8, 0.8, 0.3, 0.1), 0.5, -1)).toEqual(box(0.7, 0, 0.3, 0.1))
    expect(textMoveBox(box(0.1, 0.1, 0.2, 0.2), 0.1, 0.05)).toEqual(box(0.2, 0.15, 0.2, 0.2))
  })

  it('drags a handle and keeps the opposite edges', () => {
    const b = box(0.1, 0.1, 0.5, 0.5)
    expect(textResizeBox(b, 'se', 0.1, 0.1)).toEqual(box(0.1, 0.1, 0.6, 0.6))
    expect(textResizeBox(b, 'e', 1, 1)).toEqual(box(0.1, 0.1, 0.9, 0.5))
    expect(textResizeBox(b, 'n', 0, -0.5)).toEqual(box(0.1, 0, 0.5, 0.6))
    expect(textResizeBox(b, 'nw', 0.6, 0.6)).toEqual(box(0.58, 0.58, TEXT_MIN_SIDE, TEXT_MIN_SIDE))
  })

  it('places a box over the canvas in percent and sizes the letters', () => {
    expect(textBoxStyle(box(0.1, 0.25, 0.5, 0.125))).toEqual({ left: '10%', top: '25%', width: '50%', height: '12.5%' })
    expect(textFontShare({ size: 'xl' })).toBe(0.082)
    expect(textFontShare({ size: 'xl', font_size: 0.1 })).toBe(0.1)
    expect(textFontShare({})).toBe(0.045)
  })
})

describe('paid steps', () => {
  it('opens with visible defaults: no paid look, no letters on new backgrounds', () => {
    const f = textEmptyForms('ru')
    expect(f.place).toEqual({ vision: false, replace: false })
    expect(f.background).toMatchObject({ count: 2, no_lettering: true, use_current: false })
    expect(f.write).toMatchObject({ use_brief: true, use_tone: true, use_neighbours: false })
    expect(f.language).toBe('ru')
  })

  it('sends exactly the switches of each panel', () => {
    const f = textEmptyForms('uk')
    f.write.note = '  spring sale  '
    f.write.max_chars = 9999
    expect(textWriteBody(f)).toEqual({
      use_neighbours: false, use_brief: true, use_tone: true, max_chars: TEXT_MAX_TEXT, language: 'uk', note: 'spring sale',
    })
    f.variants.count = 10
    f.variants.feedback = ' shorter '
    expect(textVariantsBody(f)).toMatchObject({ count: TEXT_MAX_VARIANTS, feedback: 'shorter', language: 'uk' })
    expect(textPlaceBody(f)).toEqual({ vision: false, replace: false })
    f.background.prompt = '  sea at dawn '
    f.background.count = 0
    expect(textBackgroundsBody(f)).toEqual({ prompt: 'sea at dawn', count: 1, no_lettering: true, use_current: false })
  })

  it('needs something to write variants about', () => {
    const f = textEmptyForms()
    for (const k of ['use_system', 'use_rules', 'use_language', 'use_tone', 'use_brief']) f.variants[k] = false
    expect(textVariantsReady(f)).toBe(false)
    f.variants.note = 'Big sale'
    expect(textVariantsReady(f)).toBe(true)
  })

  it('rewrites only blocks with words that are not kept', () => {
    const texts = [{ id: 't1', text: 'a' }, { id: 't2', text: 'b', locked: true }, { id: 't3', text: ' ' }]
    expect(textHumanizeBody(textEmptyForms('en'), texts)).toEqual({ text_ids: ['t1'], use_language: true, language: 'en' })
  })

  it('asks the prices for the counts of the panels', () => {
    const f = textEmptyForms()
    f.variants.count = 9
    f.background.count = 9
    f.background.use_current = true
    expect(textEstimateQuery(4, f)).toEqual({ design_id: 4, variants: TEXT_MAX_VARIANTS, backgrounds: TEXT_MAX_BACKGROUNDS, use_current: true })
    expect(textEstimateQuery(null, f).design_id).toBeUndefined()
  })

  it('shows a price, free placing, or nothing when refused', () => {
    expect(textPrice({ usd: 0.04 })).toBe(0.04)
    expect(textPrice({ usd: 0.04, refusal: 'no_picture' })).toBeNull()
    expect(textPrice(null)).toBeNull()
    expect(textPrice({ usd: 'x' })).toBeNull()
    const f = textEmptyForms()
    expect(textPlacePrice({ placement: { usd: 0.002 } }, f)).toBe(0)
    f.place.vision = true
    expect(textPlacePrice({ placement: { usd: 0.002 } }, f)).toBe(0.002)
  })

  it('sums where the words went, in a fixed order', () => {
    const placement = { sources: { t1: 'vision', t2: 'layer', t3: 'vision' } }
    expect(textPlaceSummary(placement)).toEqual([{ source: 'layer', n: 1 }, { source: 'vision', n: 2 }])
    expect(textPlaceSummary(null)).toEqual([])
  })

  it('knows when backgrounds are still drawing', () => {
    expect(textBackgroundsBusy([{ status: 'done' }, { status: 'running' }])).toBe(true)
    expect(textBackgroundsBusy([{ status: 'done' }, { status: 'cancelled' }])).toBe(false)
    expect(textBackgroundsBusy(null)).toBe(false)
  })
})

describe('render report', () => {
  it('reads the header and turns it into lines', () => {
    const report = textParseReport('{"fallback_chars":"ё","missing_chars":"","clipped":["l1","l2"],"missing_files":[3]}')
    expect(textReportNotes(report)).toEqual([
      { key: 'text.report.fallback', params: { chars: 'ё', font: 'Roboto' } },
      { key: 'text.report.clipped', params: { n: 2 }, plural: 2 },
      { key: 'text.report.missingFiles', params: { n: 1 }, plural: 1 },
    ])
    expect(textParseReport('not json')).toBeNull()
    expect(textParseReport('')).toBeNull()
    expect(textReportNotes(null)).toEqual([])
  })
})

describe('errors', () => {
  it('says the module\'s own errors with their numbers and names', () => {
    expect(textErrorText({ code: 'font_in_kit', details: { family: 'Inter' } }, t, te)).toBe('The font «Inter» is already in the brand kit.')
    expect(textErrorText({ code: 'too_many_layers', details: { max: 30 } }, t, te)).toBe('Too many layers: up to 30.')
    expect(textReasonText('no_picture', t, te)).toBe('There is no picture to put words on.')
    expect(textReasonText('', t, te)).toBe('')
  })

  it('falls back to the chat texts and then to the plain message', () => {
    expect(textErrorText({ code: 'chat_archived' }, t, te)).toBe(t('chat.errors.chat_archived'))
    expect(textErrorText({ code: 'weird', message: 'Quota exceeded' }, t, te)).toBe('Quota exceeded')
  })

  it('shows a failed background in our words plus Google\'s own', () => {
    expect(textBackgroundError({ error_code: 'empty_prompt', error: 'raw words' }, t, te))
      .toEqual({ text: 'Describe what you want first.', detail: 'raw words' })
    expect(textBackgroundError({ error_code: 'x_unknown_code', error: 'Bad request' }, t, te))
      .toEqual({ text: 'Bad request', detail: '' })
  })
})

describe('jobs page', () => {
  it('leads a background job back to its chat message', () => {
    expect(textJobRoute(1, { result_json: { chat_id: 3, message_id: 9 } })).toBe('/chat/3?message=9')
    expect(textJobRoute(1, { result_json: { chat_id: 3 } })).toBe('/chat/3')
    expect(textJobRoute(1, { result_json: {} })).toBeNull()
    expect(textJobRoute(1, null)).toBeNull()
  })
})
