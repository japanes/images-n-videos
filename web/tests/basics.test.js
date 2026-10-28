import { describe, expect, it, vi } from 'vitest'
import { effectScope } from 'vue'
import { slavicPlural } from '../utils/plural.js'
import { formatBytes, formatDuration, formatUsd, parseTs } from '../utils/format.js'
import { apiErrorText } from '../utils/apiErrorText.js'
import { ApiError, toApiError } from '../composables/useApi.js'
import { useConfirm } from '../composables/useConfirm.js'
import { dispatchEvent, useEvents } from '../composables/useEvents.js'
import { MOVED_PATHS, NAV_SECTIONS, SETTINGS_TABS, settingsTabKey } from '../utils/nav.js'

describe('slavicPlural', () => {
  it('picks one/few/many', () => {
    const pick = (n) => slavicPlural(n, 3)
    expect([1, 21, 101].map(pick)).toEqual([0, 0, 0])
    expect([2, 3, 4, 22, 34].map(pick)).toEqual([1, 1, 1, 1, 1])
    expect([0, 5, 11, 12, 14, 20, 111].map(pick)).toEqual([2, 2, 2, 2, 2, 2, 2])
  })
  it('supports a leading zero form', () => {
    const pick = (n) => slavicPlural(n, 4)
    expect([0, 1, 2, 5, 21].map(pick)).toEqual([0, 1, 2, 3, 1])
  })
})

describe('format', () => {
  it('money', () => {
    expect(formatUsd(0.16, { approx: true })).toBe('≈$0.16')
    expect(formatUsd(0.004)).toBe('<$0.01')
    expect(formatUsd(0)).toBe('$0.00')
    expect(formatUsd(null)).toBe('—')
    expect(formatUsd(123.4)).toBe('$123')
  })
  it('bytes and durations', () => {
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(25 * 1024 * 1024)).toBe('25 MB')
    expect(formatDuration(75)).toBe('1:15')
    expect(formatDuration(3725)).toBe('1:02:05')
  })
  it('timestamps without a zone are UTC', () => {
    expect(parseTs('2026-10-15T12:00:00').toISOString()).toBe('2026-10-15T12:00:00.000Z')
    expect(parseTs('2026-10-15T12:00:00.123Z').toISOString()).toBe('2026-10-15T12:00:00.123Z')
    expect(parseTs('')).toBeNull()
  })
})

describe('errors', () => {
  const dict = { 'errors.no_key': 'connect first', 'errors.generic': 'oops {code}' }
  const t = (key, params = {}) => (key in dict ? dict[key].replace('{code}', params.code) : key)
  const te = (key) => key in dict

  it('localized text wins, then the backend message, then generic', () => {
    expect(apiErrorText(new ApiError({ code: 'no_key', message: 'x' }), t, te)).toBe('connect first')
    expect(apiErrorText(new ApiError({ code: 'odd', message: 'Google said no' }), t, te)).toBe('Google said no')
    expect(apiErrorText(new ApiError({ code: 'odd' }), t, te)).toBe('oops odd')
  })

  it('toApiError reads the backend error body', () => {
    const err = toApiError({ statusCode: 409, data: { error: { code: 'no_key', message: 'm', details: { a: 1 } } } })
    expect(err).toMatchObject({ code: 'no_key', message: 'm', status: 409, details: { a: 1 } })
    expect(toApiError(new TypeError('fetch failed')).code).toBe('network')
    expect(toApiError({ statusCode: 502, message: 'bad' }).code).toBe('http_502')
  })
})

describe('useConfirm', () => {
  it('resolves true on accept and false on cancel', async () => {
    const c = useConfirm()
    const first = c.confirm({ message: 'a' })
    expect(c.state.value.open).toBe(true)
    c.accept()
    await expect(first).resolves.toBe(true)
    const second = c.confirm('b')
    expect(c.state.value.opts.message).toBe('b')
    c.cancel()
    await expect(second).resolves.toBe(false)
  })
  it('a second dialog cancels the first', async () => {
    const c = useConfirm()
    const first = c.confirm('a')
    const second = c.confirm('b')
    await expect(first).resolves.toBe(false)
    c.accept()
    await expect(second).resolves.toBe(true)
  })
})

describe('useEvents', () => {
  it('routes events by type and to wildcard handlers, unsubscribes with the scope', () => {
    const scope = effectScope()
    const seen = vi.fn()
    const all = vi.fn()
    scope.run(() => {
      useEvents().on('job.updated', seen)
      useEvents().on('*', all)
    })
    dispatchEvent(JSON.stringify({ type: 'job.updated', data: { id: 1 } }))
    dispatchEvent('not json')
    dispatchEvent(JSON.stringify({ nope: 1 }))
    expect(seen).toHaveBeenCalledWith({ id: 1 })
    expect(all).toHaveBeenCalledTimes(1)
    scope.stop()
    dispatchEvent(JSON.stringify({ type: 'job.updated', data: { id: 2 } }))
    expect(seen).toHaveBeenCalledTimes(1)
  })
})

describe('settings tabs', () => {
  it('finds the tab of a path', () => {
    expect(settingsTabKey('/settings')).toBe('general')
    expect(settingsTabKey('/settings/spend')).toBe('spend')
    expect(settingsTabKey('/settings/jobs')).toBe('jobs')
    expect(settingsTabKey('/settings/connection')).toBe('connection')
    expect(settingsTabKey('/settings/models')).toBe('models')
    expect(settingsTabKey('/settings/spendings')).toBe('general')
  })
  it('sends every old menu address to its tab, not to the menu', () => {
    const menu = NAV_SECTIONS.flatMap((s) => s.items.map((i) => i.to))
    for (const [from, to] of Object.entries(MOVED_PATHS)) {
      expect(menu).not.toContain(from)
      expect(SETTINGS_TABS.map((t) => t.to)).toContain(to)
    }
  })
})
