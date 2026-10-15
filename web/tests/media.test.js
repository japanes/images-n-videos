import { describe, expect, it } from 'vitest'
import {
  MEDIA_PAGE_SIZE, mediaApplyIngestJob, mediaCheckFile, mediaDisplayName, mediaFiltersFromQuery, mediaFiltersToQuery,
  mediaHasFilters, mediaIngestBusy, mediaIngestFailed, mediaKindOfMime, mediaListParams, mediaLocalDayStart,
  mediaMergeFile, mediaSizeText, mediaUsageLink,
} from '../composables/useMediaLibrary.js'

const MB = 1024 * 1024
const LIMITS = { max_mb: { image: 25, video: 300, audio: 100, font: 25 } }

describe('media filters and the address bar', () => {
  it('reads a query and drops anything odd', () => {
    expect(mediaFiltersFromQuery({ kind: 'video', source: 'avatar', q: '  cat ', from: '2026-10-01', to: '2026-10-15', page: '3' }))
      .toEqual({ kind: 'video', source: 'avatar', q: 'cat', from: '2026-10-01', to: '2026-10-15', page: 3 })
    expect(mediaFiltersFromQuery({ kind: 'font', source: 'nope', from: '1.10.2026', to: ['2026-10-15'], page: '-2' }))
      .toEqual({ kind: '', source: '', q: '', from: '', to: '', page: 1 })
    expect(mediaFiltersFromQuery()).toEqual({ kind: '', source: '', q: '', from: '', to: '', page: 1 })
  })

  it('writes only what differs from the defaults', () => {
    expect(mediaFiltersToQuery({ kind: '', source: '', q: '', from: '', to: '', page: 1 })).toEqual({})
    expect(mediaFiltersToQuery({ kind: 'image', source: '', q: 'logo', from: '', to: '2026-10-15', page: 2 }))
      .toEqual({ kind: 'image', q: 'logo', to: '2026-10-15', page: '2' })
  })

  it('round-trips', () => {
    const f = { kind: 'audio', source: 'upload', q: 'voice', from: '2026-09-01', to: '2026-09-30', page: 4 }
    expect(mediaFiltersFromQuery(mediaFiltersToQuery(f))).toEqual(f)
  })

  it('knows when a filter is on (the page number is not a filter)', () => {
    expect(mediaHasFilters(mediaFiltersFromQuery({ page: '5' }))).toBe(false)
    expect(mediaHasFilters(mediaFiltersFromQuery({ q: 'x' }))).toBe(true)
    expect(mediaHasFilters(mediaFiltersFromQuery({ from: '2026-10-01' }))).toBe(true)
  })
})

describe('media list request', () => {
  it('turns local days into UTC bounds with the "to" day included', () => {
    const from = mediaLocalDayStart('2026-10-01')
    expect(new Date(from).getTime()).toBe(new Date(2026, 9, 1).getTime())
    expect(new Date(mediaLocalDayStart('2026-10-31', 1)).getTime()).toBe(new Date(2026, 10, 1).getTime())
    expect(mediaLocalDayStart('')).toBeNull()
    expect(mediaLocalDayStart('2026-13-45x')).toBeNull()
  })

  it('builds the query for the server', () => {
    const params = mediaListParams({ kind: 'video', source: '', q: 'clip', from: '2026-10-01', to: '2026-10-01', page: 2 })
    expect(params).toMatchObject({ page: 2, limit: MEDIA_PAGE_SIZE, kind: 'video', q: 'clip' })
    expect(params.source).toBeUndefined()
    expect(new Date(params.date_to) - new Date(params.date_from)).toBeGreaterThanOrEqual(23 * 3600 * 1000)
    expect(mediaListParams(mediaFiltersFromQuery({}), 10)).toEqual({ page: 1, limit: 10 })
  })
})

describe('media items', () => {
  it('shows the title, else the original name, else the id', () => {
    expect(mediaDisplayName({ id: 7, title: 'Logo', original_name: 'logo.png' })).toBe('Logo')
    expect(mediaDisplayName({ id: 7, title: null, original_name: 'logo.png' })).toBe('logo.png')
    expect(mediaDisplayName({ id: 7 })).toBe('#7')
    expect(mediaDisplayName(null)).toBe('')
  })

  it('links a usage only inside the app', () => {
    expect(mediaUsageLink({ url: '/brand/3' })).toBe('/brand/3')
    expect(mediaUsageLink({ url: '//evil.example/x' })).toBeNull()
    expect(mediaUsageLink({ url: 'https://evil.example' })).toBeNull()
    expect(mediaUsageLink({ type: 'style', id: 1 })).toBeNull()
  })

  it('reads the kind from the type and prints the size', () => {
    expect(mediaKindOfMime('video/mp4')).toBe('video')
    expect(mediaKindOfMime('font/woff2')).toBe('font')
    expect(mediaKindOfMime('application/pdf')).toBeNull()
    expect(mediaSizeText({ width: 1920, height: 1080 })).toBe('1920 × 1080')
    expect(mediaSizeText({ width: null, height: 1080 })).toBe('')
  })

  it('tells the preview state', () => {
    expect(mediaIngestBusy({ ingest: { status: 'running' } })).toBe(true)
    expect(mediaIngestBusy({ ingest: null })).toBe(false)
    expect(mediaIngestFailed({ ingest: { status: 'interrupted' } })).toBe(true)
    expect(mediaIngestFailed({ ingest: { status: 'done' } })).toBe(false)
  })
})

describe('quick check before uploading', () => {
  const file = (type, size) => ({ name: 'x', type, size })

  it('lets a normal file through', () => {
    expect(mediaCheckFile(file('image/png', 2 * MB), LIMITS)).toBeNull()
    expect(mediaCheckFile(file('video/mp4', 200 * MB), LIMITS)).toBeNull()
  })

  it('refuses an empty file', () => {
    expect(mediaCheckFile(file('image/png', 0), LIMITS)).toEqual({ code: 'upload_empty', details: {} })
  })

  it('refuses types the server does not take', () => {
    expect(mediaCheckFile(file('image/heic', MB), LIMITS)?.code).toBe('unsupported_type')
    expect(mediaCheckFile(file('image/svg+xml', MB), LIMITS)?.code).toBe('unsupported_type')
    expect(mediaCheckFile(file('font/woff2', MB), LIMITS)?.code).toBe('unsupported_type')
    expect(mediaCheckFile(file('font/woff2', MB), LIMITS, ['font'])).toBeNull()
    expect(mediaCheckFile(file('video/mp4', MB), LIMITS, ['image'])?.code).toBe('unsupported_type')
  })

  it('refuses a file over the limit of its kind', () => {
    expect(mediaCheckFile(file('image/jpeg', 26 * MB), LIMITS))
      .toEqual({ code: 'file_too_large', details: { kind: 'image', max_mb: 25 } })
    expect(mediaCheckFile(file('audio/mpeg', 101 * MB), LIMITS)?.details.max_mb).toBe(100)
  })

  it('leaves an unknown browser type to the server, under the biggest limit', () => {
    expect(mediaCheckFile(file('', 250 * MB), LIMITS)).toBeNull()
    expect(mediaCheckFile(file('', 301 * MB), LIMITS)?.code).toBe('file_too_large')
    expect(mediaCheckFile(file('image/png', 99 * MB), null)).toBeNull()
  })
})

describe('live updates of the list', () => {
  const list = () => [
    { id: 1, title: 'a', usage_count: 2, ingest: null },
    { id: 2, title: 'b', usage_count: 0, ingest: { status: 'queued', error_code: null, error: null } },
  ]

  it('merges a changed file and keeps library-only fields', () => {
    const items = list()
    expect(mediaMergeFile(items, { id: 1, title: 'new', thumb_url: '/files/1?w=480' })).toBe(true)
    expect(items[0]).toMatchObject({ id: 1, title: 'new', usage_count: 2, thumb_url: '/files/1?w=480' })
    expect(mediaMergeFile(items, { id: 9, title: 'x' })).toBe(false)
  })

  it('applies a preview job to its file only', () => {
    const items = list()
    const job = { id: 5, kind: 'media.ingest', ref_type: 'file', ref_id: 2, status: 'error', error_code: 'render_failed', error: 'boom' }
    expect(mediaApplyIngestJob(items, job)).toBe(true)
    expect(items[1].ingest).toEqual({ status: 'error', error_code: 'render_failed', error: 'boom' })
    expect(mediaApplyIngestJob(items, { ...job, kind: 'image.generate' })).toBe(false)
    expect(mediaApplyIngestJob(items, { ...job, ref_type: 'avatar' })).toBe(false)
    expect(mediaApplyIngestJob(items, { ...job, ref_id: 99 })).toBe(false)
  })
})
