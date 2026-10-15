import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  jobKindLabel, jobRefRoute, jobRefTypes, registerJobKind, registerJobRef, unregisterJobKind, unregisterJobRef,
} from '../utils/jobRefs.js'
import {
  applyProgress, hasErrorDetails, isActive, jobErrorText, jobMatches, jobSeconds, mergeJob, progressPercent,
} from '../utils/jobsView.js'

const job = (over = {}) => ({
  id: 10, kind: 'image.frame', group_name: 'image', status: 'running', title: 'Cat on a roof',
  ref_type: null, ref_id: null, progress: null, error: null, error_code: null,
  created_at: '2026-10-15T12:00:00', started_at: '2026-10-15T12:00:00', finished_at: null, ...over,
})

describe('jobRefs', () => {
  afterEach(() => {
    for (const type of jobRefTypes()) unregisterJobRef(type)
    unregisterJobKind('image.frame')
  })

  it('gives no link for unregistered types', () => {
    expect(jobRefRoute(job({ ref_type: 'frame', ref_id: 5 }))).toBeNull()
    expect(jobRefRoute(job())).toBeNull()
    expect(jobRefRoute(null)).toBeNull()
  })

  it('fills a path pattern', () => {
    registerJobRef('file', '/media?file=:id')
    expect(jobRefRoute(job({ ref_type: 'file', ref_id: 7 }))).toBe('/media?file=7')
    expect(jobRefRoute(job({ ref_type: 'file', ref_id: 'a b' }))).toBe('/media?file=a%20b')
    expect(jobRefRoute(job({ ref_type: 'file', ref_id: null }))).toBeNull()
    expect(jobRefTypes()).toEqual(['file'])
  })

  it('calls a resolver function and survives its errors', () => {
    registerJobRef('video', (id, j) => (j.title ? { path: `/chat/${id}` } : null))
    expect(jobRefRoute(job({ ref_type: 'video', ref_id: 3 }))).toEqual({ path: '/chat/3' })
    expect(jobRefRoute(job({ ref_type: 'video', ref_id: 3, title: '' }))).toBeNull()
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    registerJobRef('broken', () => { throw new Error('boom') })
    expect(jobRefRoute(job({ ref_type: 'broken', ref_id: 1 }))).toBeNull()
    expect(spy).toHaveBeenCalled()
    spy.mockRestore()
  })

  it('unregister removes only its own resolver', () => {
    const off = registerJobRef('frame', '/a/:id')
    registerJobRef('frame', '/b/:id')
    off()
    expect(jobRefRoute(job({ ref_type: 'frame', ref_id: 1 }))).toBe('/b/1')
    unregisterJobRef('frame')
    expect(jobRefRoute(job({ ref_type: 'frame', ref_id: 1 }))).toBeNull()
  })

  it('rejects bad registrations', () => {
    expect(() => registerJobRef('', '/x')).toThrow()
    expect(() => registerJobRef('x', 42)).toThrow()
    expect(() => registerJobKind('x', '')).toThrow()
  })

  it('labels kinds through the owning module key', () => {
    const t = (key) => ({ 'studio.jobs.frame': 'Frame' }[key] ?? key)
    expect(jobKindLabel('image.frame', t)).toBe('image.frame')
    const off = registerJobKind('image.frame', 'studio.jobs.frame')
    expect(jobKindLabel('image.frame', t)).toBe('Frame')
    registerJobKind('image.other', 'missing.key')
    expect(jobKindLabel('image.other', t)).toBe('image.other')
    unregisterJobKind('image.other')
    off()
    expect(jobKindLabel('image.frame', t)).toBe('image.frame')
    expect(jobKindLabel(undefined, t)).toBe('')
  })
})

describe('jobsView', () => {
  it('matches filters like the backend', () => {
    const j = job({ ref_type: 'frame', ref_id: 4 })
    expect(jobMatches(j, {})).toBe(true)
    expect(jobMatches(j, { status: 'active' })).toBe(true)
    expect(jobMatches(j, { status: 'problems' })).toBe(false)
    expect(jobMatches(job({ status: 'interrupted' }), { status: 'problems' })).toBe(true)
    expect(jobMatches(job({ status: 'done' }), { status: 'finished' })).toBe(true)
    expect(jobMatches(j, { status: 'finished' })).toBe(false)
    expect(jobMatches(j, { status: 'running' })).toBe(true)
    expect(jobMatches(j, { group: 'video' })).toBe(false)
    expect(jobMatches(j, { kind: 'image.frame' })).toBe(true)
    expect(jobMatches(j, { q: 'ROOF' })).toBe(true)
    expect(jobMatches(j, { q: '10' })).toBe(true)
    expect(jobMatches(j, { q: 'dog' })).toBe(false)
    expect(jobMatches(j, { refType: 'frame', refId: '4' })).toBe(true)
    expect(jobMatches(j, { refType: 'frame', refId: 5 })).toBe(false)
    expect(jobMatches(j, { refType: 'video' })).toBe(false)
    expect(jobMatches(null, {})).toBe(false)
    expect(isActive(job({ status: 'queued' }))).toBe(true)
    expect(isActive(job({ status: 'done' }))).toBe(false)
  })

  it('merges live updates', () => {
    const items = [job({ id: 12 }), job({ id: 10 })]
    // in place, even if it leaves the filter
    expect(mergeJob(items, { id: 10, status: 'error', error: 'x' }, { status: 'active' })).toBe(true)
    expect(items[1]).toMatchObject({ id: 10, status: 'error', retryable: true, cancellable: false, title: 'Cat on a roof' })
    // a new matching job goes on top
    expect(mergeJob(items, job({ id: 13, status: 'queued' }), { status: 'active' })).toBe(true)
    expect(items[0]).toMatchObject({ id: 13, cancellable: true, retryable: false, known: true })
    // not matching, or older than the newest shown: skipped
    expect(mergeJob(items, job({ id: 14, status: 'done' }), { status: 'active' })).toBe(false)
    expect(mergeJob(items, job({ id: 11 }), {})).toBe(false)
    expect(mergeJob(items, null, {})).toBe(false)
    expect(items.map((x) => x.id)).toEqual([13, 12, 10])
    // into an empty list
    const empty = []
    expect(mergeJob(empty, job({ id: 1 }), {})).toBe(true)
    expect(empty).toHaveLength(1)
  })

  it('applies progress', () => {
    const items = [job()]
    expect(applyProgress(items, { id: 10, progress: 0.5, note: 'half' })).toBe(true)
    expect(items[0]).toMatchObject({ progress: 0.5, progress_note: 'half' })
    expect(applyProgress(items, { id: 99, progress: 1 })).toBe(false)
    expect(progressPercent(items[0])).toBe(50)
    expect(progressPercent(job({ progress: 1.7 }))).toBe(100)
    expect(progressPercent(job({ progress: null }))).toBeNull()
    expect(progressPercent(job({ progress: 'x' }))).toBeNull()
  })

  it('counts seconds', () => {
    const now = Date.parse('2026-10-15T12:01:30Z')
    expect(jobSeconds(job(), now)).toBe(90)
    expect(jobSeconds(job({ status: 'done', finished_at: '2026-10-15T12:00:20' }), now)).toBe(20)
    expect(jobSeconds(job({ started_at: null }), now)).toBeNull()
  })

  it('explains errors', () => {
    const dict = { 'errors.stuck': 'Stuck.', 'errors.generic': 'Failed ({code}).' }
    const t = (key, vars = {}) => (dict[key] ?? key).replace(/\{(\w+)\}/g, (_, v) => vars[v])
    const te = (key) => key in dict
    expect(jobErrorText(job({ error_code: 'stuck', error: 'No progress for 3 minutes' }), t, te)).toBe('Stuck.')
    expect(jobErrorText(job({ error_code: 'rate_limited_x', error: 'Quota exceeded' }), t, te)).toBe('Quota exceeded')
    expect(jobErrorText(job({ error_code: 'weird' }), t, te)).toBe('Failed (weird).')
    expect(jobErrorText(job(), t, te)).toBe('')
    expect(jobErrorText(job({ error_code: 'stuck' }), t)).toBe('Stuck.')
    expect(hasErrorDetails(job({ error: 'raw' }), 'Stuck.')).toBe(true)
    expect(hasErrorDetails(job({ error: 'raw' }), 'raw')).toBe(false)
    expect(hasErrorDetails(job(), '')).toBe(false)
  })
})
