import { describe, expect, it } from 'vitest'
import en from '../i18n/locales/en/library.json'
import {
  LIBRARY_ERROR_CODES, LIBRARY_KINDS, LIBRARY_LIMITS, LIBRARY_PAGE_SIZE, libraryAncestors, libraryBuildTree,
  libraryCategoryOptions, libraryCategoryTitle, libraryCheckZones, libraryErrorText, libraryFiltersFromQuery,
  libraryFiltersToQuery, libraryPruneEmpty, librarySlotCount, libraryStylesQuery, libraryVariableKey,
  libraryVariableType, libraryVariables, libraryVisibleRows, libraryZonesText,
} from '../composables/useLibrary.js'

const has = (obj, path) => path.split('.').reduce((o, k) => (o && typeof o === 'object' ? o[k] : undefined), obj) !== undefined

describe('style text fields (same rules as the server)', () => {
  it('finds keys, defaults and types; the first occurrence wins', () => {
    const prompt = 'A {{Subject|red sneaker}} on {{background_color|#ffffff}} with {{brand}}, '
      + '{{subject|ignored}} and {{accent_color}} {{Mood}}'
    const found = libraryVariables(prompt)
    expect(found.map((v) => v.key)).toEqual(['subject', 'background_color', 'brand', 'accent_color', 'mood'])
    expect(found[0]).toEqual({ key: 'subject', name: 'Subject', default: 'red sneaker', type: 'subject' })
    expect(found.map((v) => v.type)).toEqual(['subject', 'color', 'brand', 'color', 'text'])
  })

  it('tells a colour by a whole word only', () => {
    expect(libraryVariableType('discolour')).toBe('text')
    expect(libraryVariableType('hex')).toBe('color')
    expect(libraryVariableType('Колір фону')).toBe('color')
    expect(libraryVariableType('цвет фона')).toBe('color')
    expect(libraryVariableType('Additional elements')).toBe('subjects')
    expect(libraryVariableType('text-on-subject')).toBe('text')
  })

  it('keys ignore case and spaces around', () => {
    expect(libraryVariableKey('  Brand ')).toBe('brand')
    expect(libraryVariables('{{ Brand }} and {{brand|x}}')).toEqual([{ key: 'brand', name: 'Brand', default: '', type: 'brand' }])
  })

  it('stops at twenty fields but counts them all', () => {
    const prompt = Array.from({ length: 30 }, (_, i) => `{{v${i}}}`).join(' ')
    expect(libraryVariables(prompt)).toHaveLength(LIBRARY_LIMITS.variables)
    expect(librarySlotCount(prompt)).toBe(30)
    expect(librarySlotCount('{{a}} {{A}} {{b|x}}')).toBe(2)
    expect(librarySlotCount('no fields')).toBe(0)
  })
})

describe('category tree', () => {
  const flat = [
    { slug: 'b', title: 'B', parent: null, depth: 0, sort: 2, count: 0 },
    { slug: 'a', title: 'A', title_en: 'A en', parent: null, depth: 0, sort: 1, count: 3 },
    { slug: 'a/x', title: 'X', parent: 'a', depth: 1, sort: 2, count: 1 },
    { slug: 'a/w', title: 'W', parent: 'a', depth: 1, sort: 1, count: 2 },
    { slug: 'a/w/z', title: 'Z', parent: 'a/w', depth: 2, sort: 1, count: 0 },
  ]

  it('nests and orders by the library order', () => {
    const tree = libraryBuildTree(flat)
    expect(tree.map((n) => n.slug)).toEqual(['a', 'b'])
    expect(tree[0].children.map((n) => n.slug)).toEqual(['a/w', 'a/x'])
    expect(tree[0].children[0].children.map((n) => n.slug)).toEqual(['a/w/z'])
  })

  it('hides empty branches only when asked', () => {
    const pruned = libraryPruneEmpty(libraryBuildTree(flat))
    expect(pruned.map((n) => n.slug)).toEqual(['a'])
    expect(pruned[0].children.map((n) => n.slug)).toEqual(['a/w', 'a/x'])
    expect(pruned[0].children[0].children).toEqual([])
  })

  it('shows children of open nodes only', () => {
    const tree = libraryBuildTree(flat)
    expect(libraryVisibleRows(tree, new Set()).map((r) => r.node.slug)).toEqual(['a', 'b'])
    expect(libraryVisibleRows(tree, new Set(['a', 'a/w'])).map((r) => [r.node.slug, r.depth]))
      .toEqual([['a', 0], ['a/w', 1], ['a/w/z', 2], ['a/x', 1], ['b', 0]])
    expect(libraryAncestors('a/w/z')).toEqual(['a', 'a/w'])
    expect(libraryAncestors('a')).toEqual([])
    expect(libraryAncestors('')).toEqual([])
  })

  it('lists every category for the select, indented', () => {
    const options = libraryCategoryOptions(libraryBuildTree(flat), 'en')
    expect(options.map((o) => [o.slug, o.depth])).toEqual([['a', 0], ['a/w', 1], ['a/w/z', 2], ['a/x', 1], ['b', 0]])
    expect(options[0].label).toBe('A en')
    expect(options[2].label.endsWith('Z')).toBe(true)
    expect(options[2].label.length).toBeGreaterThan(1)
  })

  it('names a category in the interface language, else as shipped', () => {
    const cat = { slug: 's', title: 'Свет', title_en: 'Light', title_uk: null }
    expect(libraryCategoryTitle(cat, 'en')).toBe('Light')
    expect(libraryCategoryTitle(cat, 'uk')).toBe('Свет')
    expect(libraryCategoryTitle(cat, 'ru')).toBe('Свет')
    expect(libraryCategoryTitle({ slug: 'only-slug' }, 'en')).toBe('only-slug')
    expect(libraryCategoryTitle(null, 'en')).toBe('')
  })
})

describe('text zones', () => {
  it('gives the same codes as the server', () => {
    expect(libraryCheckZones('')).toBeNull()
    expect(libraryCheckZones('  ')).toBeNull()
    expect(libraryCheckZones('{"zones": [{"x": 1}]}')).toBeNull()
    expect(libraryCheckZones('{"canvas": {}}')).toBeNull()
    expect(libraryCheckZones('{nope')).toBe('text_zones_invalid_json')
    expect(libraryCheckZones('[1, 2]')).toBe('text_zones_not_an_object')
    expect(libraryCheckZones('{"zones": "x"}')).toBe('text_zones_not_an_object')
    expect(libraryCheckZones(`{${' '.repeat(LIBRARY_LIMITS.zones)}}`)).toBe('text_zones_too_large')
  })

  it('shows saved zones as indented JSON', () => {
    expect(libraryZonesText(null)).toBe('')
    expect(JSON.parse(libraryZonesText({ zones: [] }))).toEqual({ zones: [] })
  })
})

describe('filters and requests', () => {
  it('reads the address bar and drops odd values', () => {
    expect(libraryFiltersFromQuery({ tab: 'mine', kind: 'photo_style', cat: 'a/b', q: ' neon ' }))
      .toEqual({ tab: 'mine', kind: 'photo_style', category: 'a/b', q: 'neon' })
    expect(libraryFiltersFromQuery({ tab: 'all', kind: 'banner', cat: ['x', 'y'] }))
      .toEqual({ tab: 'builtin', kind: '', category: 'x', q: '' })
    expect(libraryFiltersFromQuery()).toEqual({ tab: 'builtin', kind: '', category: '', q: '' })
  })

  it('writes only what differs from the defaults and round-trips', () => {
    expect(libraryFiltersToQuery({ tab: 'builtin', kind: '', category: '', q: '' })).toEqual({})
    const f = { tab: 'mine', kind: 'style', category: 'a', q: 'neon' }
    expect(libraryFiltersToQuery(f)).toEqual({ tab: 'mine', kind: 'style', cat: 'a', q: 'neon' })
    expect(libraryFiltersFromQuery(libraryFiltersToQuery(f))).toEqual(f)
  })

  it('sends no empty fields', () => {
    expect(libraryStylesQuery({ tab: 'mine', kind: '', category: '', q: '  ' }))
      .toEqual({ tab: 'mine', limit: LIBRARY_PAGE_SIZE, offset: 0 })
    expect(libraryStylesQuery({ kind: 'style', category: 'a', q: ' x ', offset: 48 }))
      .toEqual({ tab: 'builtin', kind: 'style', category: 'a', q: 'x', limit: LIBRARY_PAGE_SIZE, offset: 48 })
  })
})

describe('texts', () => {
  it('has a text for every error code, kind and field type', () => {
    for (const code of LIBRARY_ERROR_CODES) expect(has(en, `library.errors.${code}`), code).toBe(true)
    for (const kind of LIBRARY_KINDS) {
      expect(has(en, `library.kinds.${kind}`)).toBe(true)
      expect(has(en, `library.kindOne.${kind}`)).toBe(true)
      expect(has(en, `library.kindHint.${kind}`)).toBe(true)
    }
    for (const type of ['subject', 'subjects', 'brand', 'color', 'text']) {
      expect(has(en, `library.editor.fieldTypes.${type}`), type).toBe(true)
    }
  })

  it('uses the module wording first, then the shared one', () => {
    const dict = { 'library.errors.library_too_long': 'long {max}', 'errors.not_found': 'gone' }
    const t = (key, params = {}) => (key in dict ? dict[key].replace(/\{(\w+)\}/g, (_, k) => params[k]) : key)
    const te = (key) => key in dict
    expect(libraryErrorText({ code: 'library_too_long', details: { max: 200 } }, t, te)).toBe('long 200')
    expect(libraryErrorText({ code: 'not_found' }, t, te)).toBe('gone')
    expect(libraryErrorText({ code: 'odd', message: 'Server words' }, t, te)).toBe('Server words')
  })
})
