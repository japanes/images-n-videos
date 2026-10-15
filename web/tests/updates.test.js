import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import {
  UPDATE_RESULTS, UPDATE_SOURCES, UPDATE_STATES, canForce, canInstall, draftFrom, isConnectionLost, noticeFor,
  parseInline, parseNotes, resultKey, safeHref, settingsDiff, sourceKey, stateKey, timeZones, updatesErrorText,
} from '../utils/updatesView.js'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const en = JSON.parse(readFileSync(join(ROOT, 'i18n', 'locales', 'en', 'updates.json'), 'utf8'))
const hasKey = (path) => path.split('.').reduce((o, k) => (o && typeof o === 'object' ? o[k] : undefined), en) !== undefined

const GITHUB_NOTES = `<!-- Release notes generated using configuration in .github/release.yml -->

## What's Changed
### Features
* feat: long videos by @someone in https://github.com/japanes/images-n-videos/pull/12
* fix: **bold** and \`code\` and [docs](https://example.com/docs)
  wrapped line

1. first
2. second

> a quote

\`\`\`
<script>alert(1)</script>
\`\`\`

---
**Full Changelog**: https://github.com/japanes/images-n-videos/compare/v1.4.0...v1.5.0.`

describe('links', () => {
  it('keeps only http(s)', () => {
    expect(safeHref('https://github.com/x')).toBe('https://github.com/x')
    expect(safeHref('http://example.com')).toBe('http://example.com')
    expect(safeHref('javascript:alert(1)')).toBeNull()
    expect(safeHref('JaVaScRiPt:alert(1)')).toBeNull()
    expect(safeHref('data:text/html,hi')).toBeNull()
    expect(safeHref('//evil.example')).toBeNull()
    expect(safeHref('https://a.b/"onmouseover=x')).toBeNull()
    expect(safeHref('https://a.b/\u0001')).toBeNull()
    expect(safeHref('https://')).toBeNull()
    expect(safeHref(null)).toBeNull()
  })
})

describe('inline markdown', () => {
  it('splits text, bold, italics, code and links', () => {
    expect(parseInline('a **b** _c_ `d` [e](https://x.y/z) f')).toEqual([
      { type: 'text', text: 'a ' },
      { type: 'strong', text: 'b' },
      { type: 'text', text: ' ' },
      { type: 'em', text: 'c' },
      { type: 'text', text: ' ' },
      { type: 'code', text: 'd' },
      { type: 'text', text: ' ' },
      { type: 'link', text: 'e', href: 'https://x.y/z' },
      { type: 'text', text: ' f' },
    ])
  })
  it('turns unsafe links into plain text', () => {
    expect(parseInline('[click](javascript:alert(1))')).toEqual([{ type: 'text', text: 'click)' }])
    expect(parseInline('[x](data:text/html,1)')).toEqual([{ type: 'text', text: 'x' }])
    expect(parseInline('[x](//evil.example/a)')).toEqual([{ type: 'text', text: 'x' }])
  })
  it('links bare URLs without trailing punctuation', () => {
    const parts = parseInline('see https://github.com/a/b/compare/v1...v2.')
    expect(parts).toEqual([
      { type: 'text', text: 'see ' },
      { type: 'link', text: 'https://github.com/a/b/compare/v1...v2', href: 'https://github.com/a/b/compare/v1...v2' },
      { type: 'text', text: '.' },
    ])
  })
  it('leaves snake_case words and HTML as text', () => {
    expect(parseInline('a snake_case_name here')).toEqual([{ type: 'text', text: 'a snake_case_name here' }])
    expect(parseInline('<img src=x onerror=alert(1)>')).toEqual([{ type: 'text', text: '<img src=x onerror=alert(1)>' }])
  })
})

describe('release notes', () => {
  const blocks = parseNotes(GITHUB_NOTES)

  it('drops HTML comments', () => {
    expect(JSON.stringify(blocks)).not.toContain('release.yml')
  })
  it('reads headings, lists, quotes, code and rules', () => {
    expect(blocks.map((b) => b.type)).toEqual(['heading', 'heading', 'list', 'list', 'quote', 'code', 'rule', 'paragraph'])
    expect(blocks[0]).toMatchObject({ level: 2, parts: [{ type: 'text', text: "What's Changed" }] })
    expect(blocks[2].ordered).toBe(false)
    expect(blocks[2].items).toHaveLength(2)
    expect(blocks[2].items[0].parts.find((p) => p.type === 'link').href).toBe('https://github.com/japanes/images-n-videos/pull/12')
    expect(blocks[2].items[1].parts.at(-1)).toEqual({ type: 'text', text: ' wrapped line' })
    expect(blocks[3]).toMatchObject({ ordered: true, items: [{ parts: [{ text: 'first' }] }, { parts: [{ text: 'second' }] }] })
  })
  it('keeps code as text, never as markup', () => {
    expect(blocks[5]).toEqual({ type: 'code', text: '<script>alert(1)</script>' })
  })
  it('strips raw HTML tags outside code', () => {
    const out = parseNotes('<details><summary>More</summary>\nhello <b>world</b>\n</details>')
    expect(out).toEqual([{ type: 'paragraph', lines: [[{ type: 'text', text: 'More' }], [{ type: 'text', text: 'hello world' }]] }])
  })
  it('handles empty and huge input', () => {
    expect(parseNotes('')).toEqual([])
    expect(parseNotes(null)).toEqual([])
    expect(parseNotes('# a\n\n'.repeat(1000)).length).toBe(300)
    expect(parseNotes('<!-- never closed\n# hidden')).toEqual([])
  })
  it('nested list items get a depth', () => {
    const [list] = parseNotes('- a\n  - b\n    - c')
    expect(list.items.map((i) => i.depth)).toEqual([0, 1, 2])
  })
})

describe('labels', () => {
  it('every state, result and source has a string', () => {
    for (const s of [...UPDATE_STATES, 'weird']) expect(hasKey(stateKey(s)), s).toBe(true)
    for (const r of [...UPDATE_RESULTS, 'weird']) expect(hasKey(resultKey(r)), r).toBe(true)
    for (const s of [...UPDATE_SOURCES, undefined]) expect(hasKey(sourceKey(s)), String(s)).toBe(true)
    expect(stateKey('weird')).toBe('updates.state.unknown')
  })
  it('every error code of the backend has a string', () => {
    for (const code of ['updates_dev_mode', 'update_busy', 'update_not_newer', 'update_needs_beta', 'update_check_failed',
      'update_conflict', 'update_not_found', 'update_bad_request', 'updater_unavailable', 'updater_failed', 'forbidden']) {
      expect(hasKey(`updates.errors.${code}`), code).toBe(true)
    }
  })
  it('error text prefers this module, then the shared wording', () => {
    const known = new Set(['updates.errors.update_busy', 'errors.network'])
    const t = (key, params) => `${key}${params?.message ? `:${params.message}` : ''}`
    const te = (key) => known.has(key)
    expect(updatesErrorText({ code: 'update_busy', message: 'x' }, t, te)).toBe('updates.errors.update_busy:x')
    expect(updatesErrorText({ code: 'network' }, t, te)).toBe('errors.network')
    expect(updatesErrorText({ code: 'odd', message: 'raw text' }, t, te)).toBe('raw text')
  })
})

const release = (version, extra = {}) => ({ version, installable: true, prerelease: false, notes_md: '', ...extra })
const overview = (extra = {}, updater = {}) => ({
  app_version: '1.4.0',
  reachable: true,
  newest: '1.5.0',
  running_jobs: [],
  updater: { dev: false, operation: null, available: [release('1.5.0')], ...updater },
  ...extra,
})

describe('header notice', () => {
  it('offers the newest installable version', () => {
    expect(noticeFor(overview())).toMatchObject({ kind: 'available', version: '1.5.0' })
  })
  it('stays quiet without an updater, in developer mode, or when dismissed', () => {
    expect(noticeFor(overview({ reachable: false, updater: null }))).toBeNull()
    expect(noticeFor(overview({}, { dev: true }))).toBeNull()
    expect(noticeFor(overview({ newest: null }, { available: [] }))).toBeNull()
    expect(noticeFor(overview(), { dismissed: '1.5.0' })).toBeNull()
    expect(noticeFor(null)).toBeNull()
  })
  it('a dismissed version does not hide a newer one', () => {
    expect(noticeFor(overview({ newest: '1.6.0' }, { available: [release('1.6.0'), release('1.5.0')] }), { dismissed: '1.5.0' }))
      .toMatchObject({ version: '1.6.0' })
  })
  it('does not offer a version that cannot be installed', () => {
    expect(noticeFor(overview({}, { available: [release('1.5.0', { installable: false })] }))).toBeNull()
  })
  it('shows a running update even when dismissed', () => {
    const op = { active: true, kind: 'install', state: 'pulling', to: '1.5.0' }
    expect(noticeFor(overview({}, { operation: op }), { dismissed: '1.5.0' })).toEqual({ kind: 'running', version: '1.5.0' })
  })
  it('installing needs a reachable updater outside developer mode', () => {
    expect(canInstall(overview())).toBe(true)
    expect(canInstall(overview({}, { dev: true }))).toBe(false)
    expect(canInstall(overview({ reachable: false }))).toBe(false)
  })
})

describe('install anyway', () => {
  const op = { active: true, kind: 'install', state: 'preparing', to: '1.5.0', force: false, busy: [{ kind: 'video', title: 'Veo' }] }
  it('only while an install waits for running jobs', () => {
    expect(canForce(op)).toBe(true)
    expect(canForce({ ...op, busy: [] })).toBe(false)
    expect(canForce({ ...op, state: 'pulling' })).toBe(false)
    expect(canForce({ ...op, force: true })).toBe(false)
    expect(canForce({ ...op, active: false })).toBe(false)
    expect(canForce({ ...op, kind: 'apply' })).toBe(false)
    expect(canForce(null)).toBe(false)
  })
})

describe('settings', () => {
  it('sends only what changed', () => {
    const saved = { auto: true, time: '03:00', tz: 'UTC', channel: 'stable' }
    expect(settingsDiff(saved, { ...saved })).toEqual({})
    expect(settingsDiff(saved, { ...saved, auto: false, tz: 'Europe/Kyiv' })).toEqual({ auto: false, tz: 'Europe/Kyiv' })
    expect(settingsDiff(saved, { ...saved, time: '' })).toEqual({})
  })
  it('a form from the updater status', () => {
    expect(draftFrom({ auto: false, time: '04:30', tz: 'Europe/Moscow', channel: 'beta' }))
      .toEqual({ auto: false, time: '04:30', tz: 'Europe/Moscow', channel: 'beta' })
    expect(draftFrom({ channel: 'nightly' }).channel).toBe('stable')
  })
  it('time zones include the saved one', () => {
    const list = timeZones('Mars/Olympus')
    expect(list).toContain('Mars/Olympus')
    expect(list).toContain('UTC')
  })
})

describe('restarts', () => {
  it('a dropped connection is a restart, an updater error is not', () => {
    expect(isConnectionLost({ code: 'network' })).toBe(true)
    expect(isConnectionLost({ code: 'http_502', status: 502 })).toBe(true)
    expect(isConnectionLost({ code: 'updater_failed', status: 502 })).toBe(false)
    expect(isConnectionLost({ code: 'update_check_failed', status: 502 })).toBe(false)
    expect(isConnectionLost(null)).toBe(false)
  })
})
