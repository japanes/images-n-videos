import { describe, expect, it } from 'vitest'
import {
  IDEAS_ERROR_CODES, IDEAS_LANGUAGES, IDEAS_MAX_COUNT, IDEAS_PICTURE_GROUPS, IDEAS_TEXT_FIELDS, ideasAddPictures,
  ideasBriefBody, ideasCanSubmit, ideasCardState, ideasDefaultLanguage, ideasDraftKeep, ideasDraftTake, ideasDrawable,
  ideasEmptyForm, ideasErrorText, ideasItemError, ideasJobRoute, ideasPrefill, ideasProductToFrames, ideasReasonText,
  ideasSafeUrl, ideasSceneCount, ideasSceneToggle, ideasSentFields, ideasSourceHost, ideasStartBody, ideasTotal,
} from '../utils/ideasView.js'
import { chatKindFileName } from '../utils/chatView.js'
import en from '../i18n/locales/en/ideas.json'
import ru from '../i18n/locales/ru/ideas.json'
import uk from '../i18n/locales/uk/ideas.json'
import enChat from '../i18n/locales/en/chat.json'
import enCommon from '../i18n/locales/en/common.json'

const flat = (obj, prefix = '') => Object.fromEntries(Object.entries(obj).flatMap(([k, v]) => (
  v && typeof v === 'object' ? Object.entries(flat(v, `${prefix}${k}.`)) : [[`${prefix}${k}`, v]]
)))

// A tiny stand-in for vue-i18n over the real English texts.
const dict = { ...flat(en), ...flat(enChat), ...flat(enCommon) }
const t = (key, params = {}) => (key in dict ? dict[key].replace(/\{(\w+)\}/g, (_, k) => params[k] ?? '') : key)
const te = (key) => key in dict

const filled = () => ({
  ...ideasEmptyForm('ru'),
  niche: '  skin care ', brand: 'Glow', platform: 'Instagram', count: 4,
  product: [{ id: 5, url: '/f/5' }, { id: 6 }], productNote: ' bottle ', visual: [{ id: 9 }],
  scene: { light: ['soft_window'], props: [], surface: ['marble'] },
})

describe('texts', () => {
  it('has the same keys in every language', () => {
    const keys = Object.keys(flat(en)).sort()
    expect(Object.keys(flat(ru)).sort()).toEqual(keys)
    expect(Object.keys(flat(uk)).sort()).toEqual(keys)
  })

  it('has a text for every error code, field, language and picture group', () => {
    for (const code of IDEAS_ERROR_CODES) expect(te(`ideas.errors.${code}`), code).toBe(true)
    for (const f of IDEAS_TEXT_FIELDS) expect(te(`ideas.fields.${f}`), f).toBe(true)
    for (const l of IDEAS_LANGUAGES) expect(te(`ideas.languages.${l}`), l).toBe(true)
    for (const g of IDEAS_PICTURE_GROUPS) {
      for (const k of ['', 'Hint', 'Note', 'NotePlaceholder']) expect(te(`ideas.pictures.${g}${k}`), g + k).toBe(true)
    }
  })
})

describe('the window', () => {
  it('starts with the search off, the first frame on and the interface language', () => {
    const form = ideasEmptyForm('uk-UA')
    expect(form.research).toBe(false)
    expect(form.drawFirst).toBe(true)
    expect(form.language).toBe('uk')
    expect(ideasDefaultLanguage('de')).toBe('en')
    expect(ideasCanSubmit(form)).toBe(false)
  })

  it('takes the composer text as the niche only when the niche is empty', () => {
    expect(ideasPrefill(ideasEmptyForm(), '  coffee\n beans ').niche).toBe('coffee beans')
    expect(ideasPrefill({ ...ideasEmptyForm(), niche: 'tea' }, 'coffee').niche).toBe('tea')
    expect(ideasPrefill(ideasEmptyForm(), 'x'.repeat(300)).niche).toHaveLength(200)
  })

  it('builds the brief and the start body', () => {
    const form = filled()
    const brief = ideasBriefBody(form)
    expect(brief.niche).toBe('skin care')
    expect(brief.count).toBe(4)
    expect(brief.product_refs).toEqual([5, 6])
    expect(brief.visual_refs).toEqual([9])
    expect(brief.product_note).toBe('bottle')
    const body = ideasStartBody({ ...form, research: true }, 7)
    expect(body.chat_id).toBe(7)
    expect(body.scene).toEqual({ light: ['soft_window'], surface: ['marble'] })
    expect(body.research).toBe(true)
    expect(body.draw_first).toBe(true)
    expect(body.product_to_frames).toBe(true)
  })

  it('sends a refused switch as off and product pictures only when there are some', () => {
    const form = { ...filled(), research: true }
    expect(ideasStartBody(form, 1, { research: true, drawFirst: true })).toMatchObject({ research: false, draw_first: false })
    expect(ideasProductToFrames({ ...form, product: [] })).toBe(false)
    expect(ideasProductToFrames({ ...form, productToFrames: false })).toBe(false)
  })

  it('prices only the parts that are on and not refused', () => {
    const est = { ideas_usd: 0.01, research_usd: 0.035, frame_usd: 0.04, research_refusal: null, frame_refusal: null }
    expect(ideasTotal(null, filled())).toBe(null)
    expect(ideasTotal(est, { research: false, drawFirst: false })).toBe(0.01)
    expect(ideasTotal(est, { research: true, drawFirst: true })).toBe(0.085)
    expect(ideasTotal({ ...est, frame_refusal: 'model_disabled' }, { research: false, drawFirst: true })).toBe(0.01)
  })

  it('picks place and light by the rules of each line', () => {
    let scene = ideasSceneToggle({}, 'light', 'a')
    scene = ideasSceneToggle(scene, 'light', 'b')
    expect(scene).toEqual({ light: ['b'] })
    expect(ideasSceneToggle(scene, 'light', 'b')).toEqual({})
    scene = ideasSceneToggle(ideasSceneToggle({}, 'props', 'x', 2), 'props', 'y', 2)
    expect(ideasSceneToggle(scene, 'props', 'z', 2)).toEqual({ props: ['x', 'y'] })
    expect(ideasSceneCount({ ...scene, light: ['b'] })).toBe(3)
  })

  it('adds pictures once each, up to the limit', () => {
    const list = ideasAddPictures([{ id: 1 }], [{ id: 1 }, { id: 2, thumb_url: '/t/2' }, { id: 3 }], 2)
    expect(list.map((f) => f.id)).toEqual([1, 2])
    expect(list[1].thumb_url).toBe('/t/2')
  })

  it('keeps an unsent window per chat once', () => {
    ideasDraftKeep(3, filled())
    ideasDraftKeep(null, filled())
    expect(ideasDraftTake(4)).toBe(null)
    expect(ideasDraftTake(3).niche).toBe('  skin care ')
    expect(ideasDraftTake(3)).toBe(null)
  })

  it('has as many frame choices as the backend takes', () => {
    expect(IDEAS_MAX_COUNT).toBe(10)
  })
})

describe('errors', () => {
  it('uses the module texts first, then the chat ones', () => {
    expect(ideasErrorText({ code: 'ideas_empty' }, t, te)).toBe(dict['ideas.errors.ideas_empty'])
    expect(ideasReasonText('ideas_niche_empty', t, te)).toBe(dict['ideas.errors.ideas_niche_empty'])
    expect(ideasReasonText('', t, te)).toBe('')
    expect(ideasErrorText({ code: 'chat_not_found' }, t, te)).not.toBe('')
  })

  it('keeps Google words apart from our text', () => {
    const err = ideasItemError({ error_code: 'ideas_empty', error: 'finish reason SAFETY' }, t, te)
    expect(err.text).toBe(dict['ideas.errors.ideas_empty'])
    expect(err.detail).toBe('finish reason SAFETY')
  })
})

describe('the card', () => {
  it('tells what the set is doing', () => {
    expect(ideasCardState({ status: 'running', research: null })).toBe('writing')
    expect(ideasCardState({ status: 'running', research: { done: false } })).toBe('researching')
    expect(ideasCardState({ status: 'running', research: { done: true } })).toBe('writing')
    expect(ideasCardState({ status: 'done' })).toBe('done')
    expect(ideasCardState({ status: 'cancelled' })).toBe('cancelled')
  })

  it('draws only cards with a prompt', () => {
    expect(ideasDrawable({ images: [{ n: 1, prompt: 'a' }, { n: 2, prompt: ' ' }] }).map((c) => c.n)).toEqual([1])
  })

  it('shows only web links, by their host', () => {
    expect(ideasSafeUrl('javascript:alert(1)')).toBe('')
    expect(ideasSafeUrl('https://www.vogue.com/a')).toBe('https://www.vogue.com/a')
    expect(ideasSourceHost('https://www.vogue.com/a')).toBe('vogue.com')
    expect(ideasSourceHost('not a link')).toBe('not a link')
  })

  it('lists what went to the model in the window order', () => {
    expect(ideasSentFields({ platform: 'IG', niche: 'tea', brand: ' ' })).toEqual([['niche', 'tea'], ['platform', 'IG']])
  })

  it('leads the jobs page to the card in the chat', () => {
    expect(ideasJobRoute(1, { result_json: { chat_id: 4, message_id: 9 } })).toBe('/chat/4?message=9')
    expect(ideasJobRoute(1, { result_json: { chat_id: 4 } })).toBe('/chat/4')
    expect(ideasJobRoute(1, { result_json: null })).toBe(null)
  })
})

describe('ideas components', () => {
  const files = {
    ...import.meta.glob('../components/ideas/*.vue'),
    ...import.meta.glob('../components/chat/kinds/IdeasConcept.vue'),
  }

  it('all compile', async () => {
    expect(Object.keys(files).length).toBe(3)
    for (const [path, load] of Object.entries(files)) {
      const mod = await load()
      expect(mod.default, path).toBeTruthy()
    }
  })

  it('the card is the file the chat looks for', () => {
    expect(chatKindFileName('ideas.concept')).toBe('IdeasConcept')
  })
})
