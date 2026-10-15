import { describe, expect, it } from 'vitest'
import {
  DESCRIBE_PHOTOS, assetsOfKind, brandErrorText, countByKind, describeEstimate, moveItem, normalizeHex,
  photoIdsMovedForward,
} from '../utils/brand.js'
import en from '../i18n/locales/en/brand.json'
import ru from '../i18n/locales/ru/brand.json'
import uk from '../i18n/locales/uk/brand.json'

const keys = (obj, prefix = '') => Object.entries(obj).flatMap(([k, v]) => (
  v && typeof v === 'object' ? keys(v, `${prefix}${k}.`) : [`${prefix}${k}`]
)).sort()

describe('normalizeHex', () => {
  it('accepts long and short codes with or without #', () => {
    expect(normalizeHex('#1a2b3c')).toBe('#1A2B3C')
    expect(normalizeHex('1A2B3C')).toBe('#1A2B3C')
    expect(normalizeHex(' #abc ')).toBe('#AABBCC')
  })

  it('rejects anything else', () => {
    for (const bad of ['', null, undefined, '#12', '#12345', '#1234567', 'red', '#ggg000']) {
      expect(normalizeHex(bad)).toBeNull()
    }
  })
})

describe('moveItem', () => {
  it('moves an item and leaves the input alone', () => {
    const list = ['a', 'b', 'c', 'd']
    expect(moveItem(list, 2, 0)).toEqual(['c', 'a', 'b', 'd'])
    expect(moveItem(list, 0, 3)).toEqual(['b', 'c', 'd', 'a'])
    expect(list).toEqual(['a', 'b', 'c', 'd'])
  })

  it('returns a copy for out-of-range moves', () => {
    const list = ['a', 'b']
    expect(moveItem(list, 0, -1)).toEqual(['a', 'b'])
    expect(moveItem(list, 5, 0)).toEqual(['a', 'b'])
    expect(moveItem(null, 0, 1)).toEqual([])
  })
})

describe('assets', () => {
  const assets = [
    { id: 5, kind: 'logo', sort: 2 },
    { id: 3, kind: 'font', sort: 1 },
    { id: 4, kind: 'logo', sort: 1 },
    { id: 2, kind: 'logo', sort: 1 },
    { id: 9, kind: 'reference', sort: 1 },
  ]

  it('keeps the saved order inside a kind (sort, then id)', () => {
    expect(assetsOfKind(assets, 'logo').map((a) => a.id)).toEqual([2, 4, 5])
    expect(assetsOfKind(assets, 'frame')).toEqual([])
    expect(assetsOfKind(null, 'logo')).toEqual([])
  })

  it('counts by kind', () => {
    expect(countByKind(assets)).toEqual({ logo: 3, font: 1, reference: 1 })
    expect(countByKind([])).toEqual({})
  })
})

describe('subject photos', () => {
  const photos = [{ id: 11 }, { id: 12 }, { id: 13 }]

  it('moves a photo one place forward', () => {
    expect(photoIdsMovedForward(photos, 2)).toEqual([11, 13, 12])
    expect(photoIdsMovedForward(photos, 1)).toEqual([12, 11, 13])
  })

  it('keeps the order for the first photo', () => {
    expect(photoIdsMovedForward(photos, 0)).toEqual([11, 12, 13])
  })
})

describe('describeEstimate', () => {
  it('asks nothing without photos', () => {
    expect(describeEstimate(0)).toBeNull()
    expect(describeEstimate(undefined)).toBeNull()
  })

  it('prices the vision role with at most the photos it sends', () => {
    expect(describeEstimate(2)).toEqual({ kind: 'text', role: 'vision_describe', input_images: 2, purpose: 'subject_describe' })
    expect(describeEstimate(12).input_images).toBe(DESCRIBE_PHOTOS)
  })
})

describe('brandErrorText', () => {
  const messages = {
    'brand.errors.too_many_colors': 'Up to {max} colors.',
    'errors.file_in_use': 'The file is used.',
    'errors.generic': 'Error {code}',
  }
  const t = (key, params = {}) => (messages[key] || key).replace(/\{(\w+)\}/g, (_, k) => String(params[k] ?? ''))
  const te = (key) => key in messages

  it('uses the brand text with details', () => {
    expect(brandErrorText({ code: 'too_many_colors', details: { max: 16 } }, t, te)).toBe('Up to 16 colors.')
  })

  it('falls back to the app-wide text, then to the message', () => {
    expect(brandErrorText({ code: 'file_in_use' }, t, te)).toBe('The file is used.')
    expect(brandErrorText({ code: 'odd', message: 'Google said no' }, t, te)).toBe('Google said no')
    expect(brandErrorText({ code: 'odd' }, t, te)).toBe('Error odd')
  })
})

describe('brand locales', () => {
  it('have the same keys in every language', () => {
    expect(keys(ru)).toEqual(keys(en))
    expect(keys(uk)).toEqual(keys(en))
  })
})
