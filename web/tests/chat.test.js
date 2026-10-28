import { afterEach, describe, expect, it } from 'vitest'
import {
  CHAT_ERROR_CODES, CHAT_IMAGE_ROLES, CHAT_LIMITS, CHAT_MODES, CHAT_VIDEO_ROLES, chatAddPictures, chatApplyProgress,
  chatAspectRatio, chatAttachmentsBody, chatCanSend, chatComposerButtons, chatDefaultRole, chatErrorText,
  chatEventTouches, chatFileThumb, chatFindQuery, chatImageActions, chatItemError, chatItemRatio, chatItemReady,
  chatKindComponent, chatKindFileName, chatMediaLink, chatMergeMessages, chatMessageBusy, chatNextRole, chatProgress,
  chatQueryId, chatReasonText, chatRegisterComposerButton, chatRegisterImageAction, chatRegisterKind,
  chatResetRegistries, chatRolesFor, chatRolesForMode, chatSendBody, chatTime, chatWaitingCount,
  chatWarnings, chatWarningText,
} from '../utils/chatView.js'
import en from '../i18n/locales/en/chat.json'
import ru from '../i18n/locales/ru/chat.json'
import uk from '../i18n/locales/uk/chat.json'
import enCommon from '../i18n/locales/en/common.json'

const flat = (obj, prefix = '') => Object.fromEntries(Object.entries(obj).flatMap(([k, v]) => (
  v && typeof v === 'object' ? Object.entries(flat(v, `${prefix}${k}.`)) : [[`${prefix}${k}`, v]]
)))

// A tiny stand-in for vue-i18n over the real English texts.
const dict = { ...flat(en), ...flat(enCommon) }
const t = (key, params = {}) => (key in dict ? dict[key].replace(/\{(\w+)\}/g, (_, k) => params[k] ?? '') : key)
const te = (key) => key in dict

describe('texts', () => {
  it('has the same keys in every language', () => {
    const keys = Object.keys(flat(en)).sort()
    expect(Object.keys(flat(ru)).sort()).toEqual(keys)
    expect(Object.keys(flat(uk)).sort()).toEqual(keys)
  })

  it('has a text for every error code of the chat', () => {
    for (const code of CHAT_ERROR_CODES) expect(te(`chat.errors.${code}`), code).toBe(true)
  })

  it('has a name for every mode and role', () => {
    for (const m of CHAT_MODES) expect(te(`chat.modes.${m}`), m).toBe(true)
    for (const r of new Set([...CHAT_IMAGE_ROLES, ...CHAT_VIDEO_ROLES])) expect(te(`chat.roles.${r}`), r).toBe(true)
  })
})

describe('errors', () => {
  it('puts details into the chat text', () => {
    const text = chatErrorText({ code: 'chat_too_many_attachments', details: { max: 10, count: 12 } }, t, te)
    expect(text).toContain('12')
    expect(text).toContain('10')
  })

  it('joins lists of details', () => {
    const text = chatErrorText({ code: 'chat_role_unknown', details: { role: 'x', allowed: ['a', 'b'] } }, t, te)
    expect(text).toContain('a, b')
  })

  it('keeps Google words for unknown codes', () => {
    expect(chatErrorText({ code: 'odd_code', message: 'Quota exceeded' }, t, te)).toBe('Quota exceeded')
    expect(chatErrorText({ code: 'odd_code' }, t, te)).toContain('odd_code')
  })

  it('reads a refusal code of an estimate', () => {
    expect(chatReasonText('chat_text_empty', t, te)).toBe(dict['chat.errors.chat_text_empty'])
    expect(chatReasonText('', t, te)).toBe('')
  })

  it('shows the known text of an item and keeps the raw words apart', () => {
    const err = chatItemError({ error_code: 'frame_gone', error: 'deleted by user' }, t, te)
    expect(err.text).toBe(dict['chat.errors.frame_gone'])
    expect(err.detail).toBe('deleted by user')
    expect(chatItemError({ error_code: 'google_x', error: 'SAFETY' }, t, te)).toEqual({ text: 'SAFETY', detail: '' })
  })

  it('gives warnings once and leaves unknown ones as codes', () => {
    expect(chatWarnings(['a', 'b'], ['b', null, 'c'])).toEqual(['a', 'b', 'c'])
    expect(chatWarningText('odd_warning', t, te)).toBe('odd_warning')
  })
})

describe('attached pictures', () => {
  it('offers roles per mode, or the ones the server sent', () => {
    expect(chatRolesFor('image')).toEqual(CHAT_IMAGE_ROLES)
    expect(chatRolesFor('video')).toEqual(CHAT_VIDEO_ROLES)
    expect(chatRolesFor('video', { video_roles: ['first'] })).toEqual(['first'])
  })

  it('gives a new picture a reference role, in video the first frame first', () => {
    expect(chatDefaultRole('image', [])).toBe('reference')
    expect(chatDefaultRole('video', [])).toBe('first')
    expect(chatDefaultRole('video', [{ role: 'first' }])).toBe('reference')
  })

  it('skips single roles held by another picture', () => {
    const list = [{ role: 'base' }, { role: 'reference' }]
    expect(chatNextRole(list, 1, 'image')).toBe('subject')
    expect(chatNextRole([{ role: 'subject' }], 0, 'image')).toBe('base')
    expect(chatNextRole([{ role: 'subject' }, { role: 'base' }], 0, 'image')).toBe('reference')
  })

  it('brings roles to the other mode', () => {
    const list = [{ file_id: 1, role: 'base' }, { file_id: 2, role: 'reference' }]
    expect(chatRolesForMode(list, 'video').map((a) => a.role)).toEqual(['first', 'reference'])
    const video = [{ file_id: 1, role: 'first' }, { file_id: 2, role: 'last' }]
    expect(chatRolesForMode(video, 'image').map((a) => a.role)).toEqual(['reference', 'reference'])
  })

  it('adds pictures once and stops at the limit', () => {
    const out = chatAddPictures([{ file_id: 1, role: 'reference' }], [{ id: 1 }, { id: 2 }, { id: 3 }, { id: 0 }], 'image', 2)
    expect(out.map((a) => a.file_id)).toEqual([1, 2])
    expect(chatAttachmentsBody([{ file_id: '5', role: 'base', file: {} }])).toEqual([{ file_id: 5, role: 'base' }])
  })
})

describe('the composer', () => {
  it('builds a new request', () => {
    const body = chatSendBody({ mode: 'image', text: 'cat', attachments: [{ file_id: 2, role: 'reference' }], enhance: true })
    expect(body).toEqual({
      mode: 'image', text: 'cat', attachments: [{ file_id: 2, role: 'reference' }], reply_to: null, reply_index: 0,
      enhance: true,
    })
  })

  it('sends a reply without pictures and without the improvement', () => {
    const body = chatSendBody({
      mode: 'video', text: '', attachments: [{ file_id: 2, role: 'first' }], replyTo: 7, replyIndex: '1',
      enhance: true, extendSeconds: '7', region: { x: 1 },
    })
    expect(body.attachments).toEqual([])
    expect(body.enhance).toBe(false)
    expect(body.reply_index).toBe(1)
    expect(body.extend_seconds).toBe(7)
    expect(body.region).toEqual({ x: 1 })
    expect(chatSendBody({ mode: 'odd', region: { x: 1 } })).not.toHaveProperty('region')
  })

  it('lets an extension go without text', () => {
    expect(chatCanSend({ text: '  ' })).toBe(false)
    expect(chatCanSend({ text: 'a' })).toBe(true)
    expect(chatCanSend({ text: '', replyKind: 'video' })).toBe(true)
    expect(chatCanSend({ text: '', replyKind: 'image' })).toBe(false)
  })
})

describe('messages and live updates', () => {
  const pictures = { id: 1, position: 2, status: 'done', refs: { work_id: 5 }, data: { items: [
    { job_id: 11, work_id: 5, status: 'running', progress: 0.5 }, { job_id: 12, work_id: 5, status: 'done', file_id: 3 },
  ] } }
  const video = { id: 2, position: 3, status: 'done', data: { items: [{ run_id: 21, status: 'queued' }] } }

  it('knows busy messages', () => {
    expect(chatMessageBusy(pictures)).toBe(true)
    expect(chatMessageBusy({ status: 'enhancing' })).toBe(true)
    expect(chatMessageBusy({ status: 'done', data: { items: [{ status: 'done' }] } })).toBe(false)
    expect(chatMessageBusy(null)).toBe(false)
  })

  it('matches events to the message they concern', () => {
    expect(chatEventTouches(pictures, 'job.updated', { id: 11 })).toBe(true)
    expect(chatEventTouches(pictures, 'job.progress', { id: 99 })).toBe(false)
    expect(chatEventTouches(pictures, 'studio.updated', { work_id: 5 })).toBe(true)
    expect(chatEventTouches(video, 'video.updated', { id: 21 })).toBe(true)
    expect(chatEventTouches(video, 'video.deleted', { id: 22 })).toBe(false)
    expect(chatEventTouches(video, 'other', { id: 21 })).toBe(false)
  })

  it('puts job progress on the item', () => {
    const queued = { id: 3, data: { items: [{ job_id: 7, status: 'queued' }] } }
    const out = chatApplyProgress(queued, { id: 7, progress: 0.4 })
    expect(out.data.items[0]).toEqual({ job_id: 7, status: 'running', progress: 0.4 })
    expect(chatApplyProgress(queued, { id: 8, progress: 1 })).toBe(queued)
  })

  it('merges fresh messages by id and position', () => {
    const merged = chatMergeMessages([video, pictures], [{ ...pictures, status: 'error' }, { id: 9, position: 1 }])
    expect(merged.map((m) => m.id)).toEqual([9, 1, 2])
    expect(merged[1].status).toBe('error')
  })

  it('counts progress, waiting pictures and ready ones', () => {
    expect(chatProgress(pictures)).toBeCloseTo(0.75)
    expect(chatProgress({ data: { items: [] } })).toBeNull()
    expect(chatWaitingCount({ data: { items: [{ status: 'waiting' }, { status: 'done' }, { status: 'waiting' }] } })).toBe(2)
    expect(chatItemReady({ status: 'done', file_id: 3 })).toBe(true)
    expect(chatItemReady({ status: 'done' })).toBe(false)
  })
})

describe('small helpers', () => {
  it('reads result links', () => {
    expect(chatQueryId('12')).toBe(12)
    expect(chatQueryId(['4', '5'])).toBe(4)
    expect(chatQueryId('x')).toBeNull()
    expect(chatQueryId('-1')).toBeNull()
    expect(chatFindQuery({ video: '3' })).toEqual({ key: 'video', id: 3 })
    expect(chatFindQuery({ frame: '1', work: '2' })).toEqual({ key: 'frame', id: 1 })
    expect(chatFindQuery({})).toBeNull()
  })

  it('gives ratios, thumbs and links', () => {
    expect(chatAspectRatio('4:5')).toBe('4 / 5')
    expect(chatAspectRatio('odd')).toBe('1 / 1')
    expect(chatItemRatio({ file: { width: 640, height: 480 } }, '1:1')).toBe('640 / 480')
    expect(chatItemRatio({}, '9:16')).toBe('9 / 16')
    expect(chatFileThumb({ url: 'u', thumb_url: 'th' })).toBe('th')
    expect(chatFileThumb(null)).toBe('')
    expect(chatMediaLink(4)).toBe('/media?file=4')
    expect(chatMediaLink(null)).toBe('')
  })

  it('shows only the time for today', () => {
    const now = new Date(2026, 9, 16, 15, 0)
    const today = chatTime(new Date(2026, 9, 16, 12, 30).toISOString(), 'en', now)
    const earlier = chatTime(new Date(2026, 9, 14, 12, 30).toISOString(), 'en', now)
    expect(today).toContain('30')
    expect(earlier.length).toBeGreaterThan(today.length)
    expect(chatTime('', 'en', now)).toBe('')
  })

  it('keeps the text limits the server has', () => {
    expect(CHAT_LIMITS.text).toBeGreaterThan(0)
    expect(CHAT_LIMITS.attachments).toBeGreaterThan(0)
  })
})

describe('extension points', () => {
  afterEach(() => chatResetRegistries())

  it('turns a kind into a file name', () => {
    expect(chatKindFileName('avatar.card')).toBe('AvatarCard')
    expect(chatKindFileName('ideas_list-v2')).toBe('IdeasListV2')
    expect(chatKindFileName('')).toBe('')
  })

  it('registers message kinds', () => {
    const component = { name: 'X' }
    chatRegisterKind('avatar.card', component)
    expect(chatKindComponent('avatar.card')).toBe(component)
    expect(chatKindComponent('other')).toBeNull()
  })

  it('registers composer buttons per mode, in order', () => {
    chatRegisterComposerButton({ id: 'b', order: 20 })
    chatRegisterComposerButton({ id: 'a', order: 10, modes: ['image'] })
    chatRegisterComposerButton({ labelKey: 'no.id' })
    expect(chatComposerButtons('image').map((b) => b.id)).toEqual(['a', 'b'])
    expect(chatComposerButtons('video').map((b) => b.id)).toEqual(['b'])
  })

  it('registers picture actions and forgets them all on reset', () => {
    chatRegisterImageAction({ id: 'text', order: 5 })
    chatRegisterImageAction({ id: 'crop' })
    expect(chatImageActions().map((a) => a.id)).toEqual(['text', 'crop'])
    chatRegisterKind('k', {})
    chatResetRegistries()
    expect(chatImageActions()).toEqual([])
    expect(chatComposerButtons('image')).toEqual([])
    expect(chatKindComponent('k')).toBeNull()
  })
})

describe('chat components', () => {
  const files = import.meta.glob('../components/chat/*.vue')

  it('all compile', async () => {
    expect(Object.keys(files).length).toBeGreaterThanOrEqual(15)
    for (const [path, load] of Object.entries(files)) {
      const mod = await load()
      expect(mod.default, path).toBeTruthy()
    }
  })

  it('the pages and the side list compile', async () => {
    const more = {
      ...import.meta.glob('../pages/chat/*.vue'),
      ...import.meta.glob('../components/layout/SidebarChats.vue'),
    }
    expect(Object.keys(more).length).toBe(3)
    for (const [path, load] of Object.entries(more)) {
      const mod = await load()
      expect(mod.default, path).toBeTruthy()
    }
  })
})
