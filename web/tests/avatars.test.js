import { describe, expect, it } from 'vitest'
import {
  AVATAR_CATEGORIES, AVATAR_ERROR_CODES, AVATAR_FACE_CODE, AVATAR_LIMITS, AVATAR_MODES, AVATAR_SHOT_COUNT, AVATAR_STATES,
  AVATAR_TABS, avatarsBatchPhotos, avatarsBatchProgress, avatarsCandidateCount, avatarsCandidatesBlock, avatarsCategory,
  avatarsChatAvatarId, avatarsCompareChoices, avatarsDefaultTab, avatarsDescribeBlock, avatarsDraftFileIds,
  avatarsDuration, avatarsEmptySlots, avatarsErrorText, avatarsExportUrl, avatarsFitSize, avatarsGroupSlots,
  avatarsIdentityCheck, avatarsItemError, avatarsJobRoute, avatarsMention, avatarsPackBlock, avatarsPhotosLeft,
  avatarsReasonText, avatarsShotNumber, avatarsShotTitle, avatarsSlotState, avatarsSpendLink, avatarsThumb,
  avatarsTimeText,
} from '../utils/avatarsView.js'
import { chatKindFileName } from '../utils/chatView.js'
import en from '../i18n/locales/en/avatars.json'
import ru from '../i18n/locales/ru/avatars.json'
import uk from '../i18n/locales/uk/avatars.json'
import enChat from '../i18n/locales/en/chat.json'
import enCommon from '../i18n/locales/en/common.json'

const flat = (obj, prefix = '') => Object.fromEntries(Object.entries(obj).flatMap(([k, v]) => (
  v && typeof v === 'object' ? Object.entries(flat(v, `${prefix}${k}.`)) : [[`${prefix}${k}`, v]]
)))

// A tiny stand-in for vue-i18n over the real English texts (English plurals: one | many).
const dict = { ...flat(en), ...flat(enChat), ...flat(enCommon) }
const t = (key, params = {}, plural = undefined) => {
  if (!(key in dict)) return key
  const forms = String(dict[key]).split(' | ')
  const text = plural === undefined || forms.length < 2 ? forms[0] : forms[Number(plural) === 1 ? 0 : 1]
  return text.replace(/\{'@'\}/g, '@').replace(/\{(\w+)\}/g, (_, k) => params[k] ?? '')
}
const te = (key) => key in dict

const slot = (n, extra = {}) => {
  const code = `SHOT_${String(n).padStart(2, '0')}`
  return { id: 100 + n, shot_code: code, category: 'identity/full-36/portraits', status: 'empty', file_id: null, ...extra }
}

const view = (extra = {}) => ({
  id: 3,
  name: 'Anna',
  init_mode: 'reference',
  identity: 'x'.repeat(300),
  identity_locked: false,
  describing: false,
  brief: '',
  face: { id: 50 },
  sources: [{ id: 1, file_id: 11 }, { id: 2, file_id: 12 }],
  candidates: [{ id: 7, file_id: 50 }],
  slots: [slot(1, { file_id: 50, status: 'done' }), slot(2), slot(3, { file_id: 60, status: 'done' })],
  ...extra,
})

describe('texts', () => {
  it('has the same keys in every language', () => {
    const keys = Object.keys(flat(en)).sort()
    expect(Object.keys(flat(ru)).sort()).toEqual(keys)
    expect(Object.keys(flat(uk)).sort()).toEqual(keys)
  })

  it('has a text for every error code, mode, state, tab, category and shot', () => {
    for (const code of AVATAR_ERROR_CODES) expect(te(`avatars.errors.${code}`), code).toBe(true)
    for (const m of AVATAR_MODES) {
      expect(te(`avatars.modes.${m}.name`), m).toBe(true)
      expect(te(`avatars.modes.${m}.text`), m).toBe(true)
    }
    for (const s of AVATAR_STATES) expect(te(`avatars.states.${s}`), s).toBe(true)
    for (const tab of AVATAR_TABS) expect(te(`avatars.tabs.${tab}`), tab).toBe(true)
    for (const c of AVATAR_CATEGORIES) expect(te(`avatars.categories.${c}`), c).toBe(true)
    for (let n = 1; n <= AVATAR_SHOT_COUNT; n += 1) {
      const code = `SHOT_${String(n).padStart(2, '0')}`
      expect(te(`avatars.shots.${code}`), code).toBe(true)
    }
    expect(te('avatars.identity.source.model')).toBe(true)
    expect(te('avatars.identity.source.manual')).toBe(true)
  })

  it('writes the mention sign so that vue-i18n keeps it', () => {
    for (const lang of [en, ru, uk]) {
      for (const [key, text] of Object.entries(flat(lang))) {
        expect(String(text).replace(/\{'@'\}/g, ''), key).not.toContain('@')
      }
    }
    expect(t('avatars.pack.asSubjectOn', { name: 'Anna' })).toContain('@Anna')
  })
})

describe('errors', () => {
  it('uses the avatar texts first, then the chat ones, with the numbers filled in', () => {
    expect(avatarsErrorText({ code: 'avatar_no_face' }, t, te)).toBe(dict['avatars.errors.avatar_no_face'])
    expect(avatarsErrorText({ code: 'avatar_photo_limit', details: { max: 12, have: 12 } }, t, te)).toContain('12')
    expect(avatarsReasonText('avatar_nothing_to_draw', t, te)).toBe(dict['avatars.errors.avatar_nothing_to_draw'])
    expect(avatarsReasonText('', t, te)).toBe('')
    expect(avatarsErrorText({ code: 'chat_not_found' }, t, te)).not.toBe('')
  })

  it('keeps Google words apart from our text', () => {
    const err = avatarsItemError({ error_code: 'stuck', error_text: 'deadline exceeded' }, t, te)
    expect(err.text).toBe(dict['avatars.errors.stuck'])
    expect(err.detail).toBe('deadline exceeded')
    const same = avatarsItemError({ error_code: 'stuck', error: dict['avatars.errors.stuck'] }, t, te)
    expect(same.detail).toBe('')
  })
})

describe('the shots', () => {
  it('groups the slots in the catalog order, unknown groups last', () => {
    const groups = avatarsGroupSlots([
      slot(5, { category: 'identity/full-36/body' }),
      slot(1),
      slot(9, { category: 'identity/full-36/weird' }),
      slot(2, { category: 'identity/full-36/angles' }),
    ])
    expect(groups.map((g) => g.category)).toEqual(['portraits', 'angles', 'body', 'weird'])
    expect(avatarsCategory('identity/full-36/gaze')).toBe('gaze')
    expect(avatarsCategory('')).toBe('')
  })

  it('names a shot by its code and falls back to the catalog title', () => {
    expect(avatarsShotTitle('SHOT_08', t, te)).toBe(dict['avatars.shots.SHOT_08'])
    expect(avatarsShotTitle('SHOT_99', t, te, 'Some shot')).toBe('Some shot')
    expect(avatarsShotTitle('', t, te)).toBe('')
    expect(avatarsShotNumber('SHOT_07')).toBe(7)
    expect(avatarsShotNumber('FACE')).toBe(0)
    expect(AVATAR_FACE_CODE).toBe('SHOT_01')
  })

  it('draws only empty or failed slots, never the face or a busy one', () => {
    const slots = [
      slot(1),
      slot(2),
      slot(3, { status: 'error' }),
      slot(4, { status: 'drawing' }),
      slot(5, { file_id: 9, status: 'done' }),
    ]
    expect(avatarsEmptySlots(slots).map((s) => s.shot_code)).toEqual(['SHOT_02', 'SHOT_03'])
    expect(avatarsSlotState(slots[2])).toBe('error')
    expect(avatarsSlotState(slots[3])).toBe('busy')
    expect(avatarsSlotState(slot(6, { status: 'queued', file_id: 9 }))).toBe('busy')
    expect(avatarsSlotState(slots[4])).toBe('done')
    expect(avatarsSlotState(null)).toBe('empty')
  })

  it('finds the pictures of a batch and counts how far it is', () => {
    const v = view({ slots: [slot(2, { status: 'drawing' }), slot(3, { file_id: 60 }), slot(4, { status: 'error' })] })
    const photos = avatarsBatchPhotos(v, [103, 102, 104, 999, 7])
    expect(photos.map((p) => p.id)).toEqual([103, 102, 104, 7])
    expect(avatarsBatchProgress(photos)).toEqual({ done: 2, busy: 1, failed: 1, total: 4 })
    expect(avatarsBatchPhotos(null, [1])).toEqual([])
  })

  it('offers the face, the photos and the earlier versions to compare', () => {
    const s = slot(4, { file_id: 70, meta: { previous_file_ids: [61, 62] } })
    const choices = avatarsCompareChoices(s, view())
    expect(choices.map((c) => c.key)).toEqual(['face:50', 'photo:11', 'photo:12', 'previous:62', 'previous:61'])
    expect(choices.find((c) => c.key === 'previous:62').n).toBe(1)
    expect(avatarsCompareChoices(slot(1, { file_id: 50 }), view()).some((c) => c.kind === 'face')).toBe(false)
  })
})

describe('what can start', () => {
  it('«Describe» needs photos, words or nothing, depending on the way', () => {
    expect(avatarsDescribeBlock(view())).toBe('')
    expect(avatarsDescribeBlock(view({ sources: [] }))).toBe('avatar_no_photos')
    expect(avatarsDescribeBlock(view({ init_mode: 'description' }))).toBe('avatar_no_brief')
    expect(avatarsDescribeBlock(view({ init_mode: 'description', brief: 'a woman' }))).toBe('')
    expect(avatarsDescribeBlock(view({ init_mode: 'auto', sources: [] }))).toBe('')
    expect(avatarsDescribeBlock(view({ identity_locked: true }))).toBe('avatar_identity_locked')
    expect(avatarsDescribeBlock(view({ describing: true }))).toBe('avatar_describe_busy')
    expect(avatarsDescribeBlock(null)).toBe('avatar_no_identity')
  })

  it('faces need a description, shots need a face and an empty slot', () => {
    expect(avatarsCandidatesBlock(view())).toBe('')
    expect(avatarsCandidatesBlock(view({ identity: ' ' }))).toBe('avatar_no_identity')
    expect(avatarsCandidatesBlock(view({ describing: true }))).toBe('avatar_describe_busy')
    expect(avatarsPackBlock(view())).toBe('')
    expect(avatarsPackBlock(view({ face: null }))).toBe('avatar_no_face')
    expect(avatarsPackBlock(view({ identity: '' }))).toBe('avatar_no_identity')
    expect(avatarsPackBlock(view({ slots: [slot(1, { file_id: 50 }), slot(2, { file_id: 51 })] }))).toBe('avatar_nothing_to_draw')
  })

  it('checks a typed description', () => {
    expect(avatarsIdentityCheck('   ')).toBe('avatar_identity_empty')
    expect(avatarsIdentityCheck('short text')).toBe('short')
    expect(avatarsIdentityCheck('x'.repeat(AVATAR_LIMITS.identityMin))).toBe('')
    expect(avatarsIdentityCheck('x'.repeat(AVATAR_LIMITS.identity + 1))).toBe('avatar_identity_too_long')
  })

  it('keeps the counts in range', () => {
    expect(avatarsCandidateCount(0)).toBe(1)
    expect(avatarsCandidateCount(9)).toBe(6)
    expect(avatarsCandidateCount('3')).toBe(3)
    expect(avatarsCandidateCount('abc')).toBe(4)
    expect(avatarsPhotosLeft(view())).toBe(AVATAR_LIMITS.photos - 2)
    expect(avatarsPhotosLeft({ sources: Array(20).fill({}) })).toBe(0)
  })

  it('opens the card on the step the avatar is at', () => {
    expect(avatarsDefaultTab(null)).toBe('person')
    expect(avatarsDefaultTab({ state: 'no_identity' })).toBe('person')
    expect(avatarsDefaultTab({ state: 'no_face' })).toBe('face')
    expect(avatarsDefaultTab({ state: 'unfinished' })).toBe('shots')
    expect(avatarsDefaultTab({ state: 'ready' })).toBe('shots')
  })
})

describe('the chat', () => {
  it('knows the avatar of an avatar chat only', () => {
    expect(avatarsChatAvatarId({ kind: 'avatar', meta: { avatar_id: 4 } })).toBe(4)
    expect(avatarsChatAvatarId({ kind: 'image', meta: { avatar_id: 4 } })).toBe(null)
    expect(avatarsChatAvatarId({ kind: 'avatar', meta: {} })).toBe(null)
  })

  it('takes picture files from the composer, once each', () => {
    const draft = {
      attachments: [
        { file_id: 5, file: { mime: 'image/png' } },
        { file_id: 5, file: { mime: 'image/png' } },
        { file_id: 6, file: { mime: 'video/mp4' } },
        { file_id: 7 },
        { file_id: 'x' },
      ],
    }
    expect(avatarsDraftFileIds(draft)).toEqual([5, 7])
    expect(avatarsDraftFileIds(null)).toEqual([])
  })

  it('adds the mention at the end of the text', () => {
    expect(avatarsMention('a portrait  ', 'Anna')).toBe('a portrait @Anna ')
    expect(avatarsMention('', 'Anna')).toBe('@Anna ')
    expect(avatarsMention('text', ' ')).toBe('text')
  })

  it('leads from a job to its message and from a call to the expenses', () => {
    expect(avatarsJobRoute(1, { result_json: { chat_id: 8, message_id: 30 } })).toBe('/chat/8?message=30')
    expect(avatarsJobRoute(1, { result_json: { chat_id: 8 } })).toBe('/chat/8')
    expect(avatarsJobRoute(1, {})).toBe(null)
    expect(avatarsSpendLink('avatar_photo', 5)).toBe('/settings/spend?ref_type=avatar_photo&ref_id=5&period=all')
    expect(avatarsSpendLink('avatar_photo', 0)).toBe('')
    expect(avatarsExportUrl(3)).toBe('/api/avatars/3/export')
    expect(avatarsThumb(9, 200)).toBe('/files/9?w=200')
    expect(avatarsThumb(null)).toBe('')
  })
})

describe('time and size', () => {
  it('rounds the time to something easy to read', () => {
    expect(avatarsDuration(2)).toEqual({ key: 'seconds', n: 5 })
    expect(avatarsDuration(47)).toEqual({ key: 'seconds', n: 45 })
    expect(avatarsDuration(150)).toEqual({ key: 'minutes', n: 3 })
    expect(avatarsDuration(5400)).toEqual({ key: 'hours', n: 1.5 })
  })

  it('writes «about N minutes» and nothing without a time', () => {
    expect(avatarsTimeText({ seconds: 60 }, t)).toBe('About 60 seconds')
    expect(avatarsTimeText({ seconds: 600 }, t)).toBe('About 10 minutes')
    expect(avatarsTimeText({ seconds: 60 * 60 * 2 }, t)).toBe('About 2 h')
    expect(avatarsTimeText(null, t)).toBe('')
    expect(avatarsTimeText({ seconds: 0 }, t)).toBe('')
  })

  it('makes big photos smaller before upload', () => {
    expect(avatarsFitSize(4000, 3000, 2000)).toEqual({ width: 2000, height: 1500, scale: 0.5 })
    expect(avatarsFitSize(800, 600, 2000)).toEqual({ width: 800, height: 600, scale: 1 })
  })
})

describe('avatar components', () => {
  const files = {
    ...import.meta.glob('../components/avatars/*.vue'),
    ...import.meta.glob('../components/chat/kinds/Avatar*.vue'),
  }

  it('all compile', async () => {
    expect(Object.keys(files).length).toBe(12)
    for (const [path, load] of Object.entries(files)) {
      const mod = await load()
      expect(mod.default, path).toBeTruthy()
    }
  })

  it('the cards are the files the chat looks for', () => {
    expect(chatKindFileName('avatar.card')).toBe('AvatarCard')
    expect(chatKindFileName('avatar.identity')).toBe('AvatarIdentity')
    expect(chatKindFileName('avatar.candidates')).toBe('AvatarCandidates')
    expect(chatKindFileName('avatar.pack')).toBe('AvatarPack')
  })
})
