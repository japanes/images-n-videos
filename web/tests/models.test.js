import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import {
  aspectSizeRows, aspectSizesValue, modelAvailability, modelCapChips, modelPriceBody,
  modelPriceFields, modelPriceLines, parseSettingInput, parseVideoResolutions, priceInputText,
  priceText, sameSettingValue, settingMessageKeys, settingsGroups, videoResolutionName,
} from '../utils/modelsView.js'

const LOCALES = ['ru', 'uk', 'en']
const read = (code, name) => JSON.parse(readFileSync(join(process.cwd(), 'i18n', 'locales', code, name), 'utf8'))
const dig = (tree, path) => path.split('.').reduce((node, part) => (node && typeof node === 'object' ? node[part] : undefined), tree)

describe('models: availability, price, capabilities', () => {
  it('reads the availability mark', () => {
    expect(modelAvailability({ available: true })).toBe('available')
    expect(modelAvailability({ available: false })).toBe('unavailable')
    expect(modelAvailability({ available: null })).toBe('unchecked')
    expect(modelAvailability(null)).toBe('unchecked')
  })

  it('lists price lines of a picture model only for allowed sizes', () => {
    const model = {
      kind: 'image',
      price: { input_per_1m: 0.5, output_per_1m: 60, image_output_tokens: { '1K': 1000, '2K': 2000, '4K': 4000 } },
      caps: { allowed_resolutions: ['1K', '2K'] },
    }
    const lines = modelPriceLines(model)
    expect(lines[0]).toEqual({ key: 'tokens', input: 0.5, output: 60 })
    expect(lines.filter((l) => l.key === 'perImage').map((l) => l.size)).toEqual(['1K', '2K'])
    expect(lines.find((l) => l.size === '2K').usd).toBeCloseTo(0.12)
  })

  it('lists per-second and search prices', () => {
    const video = { kind: 'video', price: { per_second: { '720p': 0.1, '4k': 0.4 } } }
    expect(modelPriceLines(video)).toEqual([
      { key: 'perSecond', res: '720p', usd: 0.1 },
      { key: 'perSecond', res: '4K', usd: 0.4 },
    ])
    const omni = { kind: 'video', price: { output_per_1m: 10, output_tokens_per_second: 5000 } }
    expect(modelPriceLines(omni)).toContainEqual({ key: 'perSecondApprox', usd: 0.05 })
    const text = { kind: 'text', price: { search_per_request: 0.014, search_unit: 'prompt' } }
    expect(modelPriceLines(text)).toEqual([{ key: 'searchPrompt', usd: 0.014 }])
    expect(modelPriceLines({ kind: 'text', price: {} })).toEqual([])
  })

  it('reads video resolutions with their length limits', () => {
    expect(videoResolutionName('4k')).toBe('4K')
    expect(parseVideoResolutions('720p, 1080p@8, 4k@8|6')).toEqual([
      { res: '720p', only: [] },
      { res: '1080p', only: [8] },
      { res: '4K', only: [8, 6] },
    ])
    expect(parseVideoResolutions(null)).toEqual([])
  })

  it('turns capabilities into chips and keeps unknown ones as they are', () => {
    const chips = modelCapChips({ kind: 'text', caps: { accepts_images: true, json_mode: true, brand_new: true, level: 3 } })
    expect(chips).toContainEqual({ key: 'readsImages', params: {} })
    expect(chips).toContainEqual({ key: 'json', params: {} })
    expect(chips).toContainEqual({ raw: 'brand_new' })
    expect(chips).toContainEqual({ raw: 'level: 3' })
    const video = modelCapChips({ kind: 'video', caps: { allowed_resolutions: '720p,1080p@8', generates_audio: true } })
    expect(video).toContainEqual({ key: 'resolutionOnly', params: { res: '1080p', seconds: '8' } })
    expect(video).toContainEqual({ key: 'audioAlways', params: {} })
  })

  it('sends only real price changes', () => {
    const model = {
      seed_price: { input_per_1m: 0.3, output_per_1m: 2.5, per_second: { '720p': 0.1 } },
      price: { input_per_1m: 0.4, output_per_1m: 2.5, per_second: { '720p': 0.1 } },
    }
    const fields = modelPriceFields(model)
    expect(fields.map((f) => f.path)).toEqual(['input_per_1m', 'output_per_1m', 'per_second.720p'])
    expect(fields[0]).toMatchObject({ seed: 0.3, value: 0.4 })
    expect(modelPriceBody(fields, { input_per_1m: '0,3', output_per_1m: '2.5', 'per_second.720p': '0.1' })).toEqual({ price: null })
    expect(modelPriceBody(fields, { input_per_1m: '0.4', output_per_1m: '2.5', 'per_second.720p': '0.2' }))
      .toEqual({ price: { input_per_1m: 0.4, per_second: { '720p': 0.2 } } })
    expect(modelPriceBody(fields, { input_per_1m: '-1', output_per_1m: '2.5', 'per_second.720p': '0.1' })).toEqual({ error: 'input_per_1m' })
    expect(modelPriceBody(fields, { input_per_1m: '0.3', output_per_1m: '', 'per_second.720p': '0.1' })).toEqual({ error: 'output_per_1m' })
  })

  it('writes small prices readably', () => {
    expect(priceText(0)).toBe('$0')
    expect(priceText(2)).toBe('$2')
    expect(priceText(1.5)).toBe('$1.50')
    expect(priceText(0.25)).toBe('$0.25')
    expect(priceText(0.014)).toBe('$0.014')
    expect(priceText(0.1)).toBe('$0.10')
    expect(priceText(undefined)).toBe('—')
    expect(priceInputText(0.1 + 0.2)).toBe('0.3')
    expect(priceInputText(null)).toBe('')
  })
})

describe('settings: groups, values, sizes', () => {
  it('puts the known groups first and the rest by name', () => {
    const items = [{ key: 'z.a', group: 'zeta' }, { key: 'j.a', group: 'jobs' }, { key: 'a.a', group: 'alpha' },
      { key: 'g.a', group: 'general' }, { key: 'x' }]
    expect(settingsGroups(items).map((g) => g.group)).toEqual(['general', 'jobs', 'alpha', 'zeta'])
    expect(settingsGroups(items)[0].items.map((i) => i.key)).toEqual(['g.a', 'x'])
  })

  it('finds strings of a setting in the settings locale or in its module', () => {
    const keys = settingMessageKeys({ key: 'other.thing', meta: { label_key: 'other.settings.thing' } })
    expect(keys.label).toEqual(['settings.keys.other.thing.label', 'other.settings.thing'])
    expect(keys.help).toEqual(['settings.keys.other.thing.help'])
    expect(keys.choice('en')).toBe('settings.keys.other.thing.choices.en')
  })

  it('checks numbers against the kind and the range', () => {
    const int = { kind: 'int', min: 1, max: 8 }
    expect(parseSettingInput(int, '3')).toEqual({ value: 3 })
    expect(parseSettingInput(int, ' 2 ')).toEqual({ value: 2 })
    expect(parseSettingInput(int, '2.5')).toEqual({ error: 'whole' })
    expect(parseSettingInput(int, '9')).toEqual({ error: 'range' })
    expect(parseSettingInput(int, '')).toEqual({ error: 'number' })
    expect(parseSettingInput(int, 'abc')).toEqual({ error: 'number' })
    expect(parseSettingInput({ kind: 'float', min: 0, max: 10 }, '2,5')).toEqual({ value: 2.5 })
    expect(parseSettingInput({ kind: 'json' }, '{"a":1}')).toEqual({ value: { a: 1 } })
    expect(parseSettingInput({ kind: 'json' }, '{a')).toEqual({ error: 'json' })
    expect(parseSettingInput({ kind: 'str' }, 'x')).toEqual({ value: 'x' })
    expect(sameSettingValue({ a: [1, 2] }, { a: [1, 2] })).toBe(true)
    expect(sameSettingValue(undefined, null)).toBe(true)
  })

  it('edits sizes per shape and refuses sides out of range', () => {
    const defaults = { '1:1': [1080, 1080], '4:5': [1080, 1350] }
    const rows = aspectSizeRows({ '4:5': [1200, 1500], '2:1': [2000, 1000] }, defaults)
    expect(rows).toEqual([
      { aspect: '1:1', w: 1080, h: 1080 },
      { aspect: '4:5', w: 1200, h: 1500 },
      { aspect: '2:1', w: 2000, h: 1000 },
    ])
    expect(aspectSizeRows('junk', defaults).map((r) => r.w)).toEqual([1080, 1080])
    expect(aspectSizesValue([{ aspect: '1:1', w: '1000', h: 1000 }])).toEqual({ '1:1': [1000, 1000] })
    expect(aspectSizesValue([{ aspect: '1:1', w: '10', h: 1000 }])).toBeNull()
    expect(aspectSizesValue([{ aspect: '1:1', w: '1000.5', h: 1000 }])).toBeNull()
    expect(aspectSizesValue([{ aspect: '1:1', w: '', h: 1000 }])).toBeNull()
  })
})

// Settings of the core and of this module. Other modules' settings are not
// listed here on purpose: they come and go as modules land, and the screen
// shows the key itself when a label is missing.
const CORE_SETTINGS = [
  'general.text_language', 'general.variants', 'general.max_attachments', 'general.aspect_sizes',
  'google.max_concurrency', 'google.max_rpm', 'google.timeout_seconds', 'google.max_attempts',
  'google.video_wait_minutes', 'google.daily_cap_usd', 'google.refusal_retries', 'google.refusal_retry_seconds',
  'jobs.limit.image', 'jobs.limit.avatar', 'jobs.limit.video', 'jobs.limit.render', 'jobs.limit.stt',
  'jobs.limit.text', 'jobs.limit.default',
]
const ROLES = ['vision_describe', 'image_regions', 'text_placement', 'shot_ideas', 'research', 'video_brief',
  'image_text', 'prompt_enhance']

describe('models and settings strings', () => {
  it.each(LOCALES)('%s: core settings have a label and a help line', (code) => {
    const tree = read(code, 'settings.json')
    const missing = CORE_SETTINGS.filter((key) => !dig(tree, `settings.keys.${key}.label`) || !dig(tree, `settings.keys.${key}.help`))
    expect(missing).toEqual([])
    for (const choice of ['ru', 'uk', 'en']) {
      expect(dig(tree, `settings.keys.general.text_language.choices.${choice}`)).toBeTruthy()
    }
  })

  it.each(LOCALES)('%s: every role has a name and a description', (code) => {
    const tree = read(code, 'models.json')
    const missing = ROLES.filter((role) => !dig(tree, `models.roles.items.${role}.name`) || !dig(tree, `models.roles.items.${role}.description`))
    expect(missing).toEqual([])
  })

  it.each(LOCALES)('%s: errors of this module are in common.json', (code) => {
    const tree = read(code, 'common.json')
    for (const name of ['invalid_setting', 'unknown_setting', 'model_unknown', 'model_is_default', 'role_unknown',
      'role_model_unsuitable', 'bad_price']) {
      expect(dig(tree, `errors.${name}`), name).toBeTruthy()
    }
  })
})
