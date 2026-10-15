import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { describe, expect, it } from 'vitest'
import { buildMessages, flatKeys } from '../utils/i18nMessages.js'

// vitest runs from web/
const ROOT = process.cwd()
const LOCALES = ['ru', 'uk', 'en']

function loadFiles() {
  const files = {}
  for (const code of LOCALES) {
    const dir = join(ROOT, 'i18n', 'locales', code)
    for (const name of readdirSync(dir).filter((n) => n.endsWith('.json'))) {
      files[`./locales/${code}/${name}`] = JSON.parse(readFileSync(join(dir, name), 'utf8'))
    }
  }
  return files
}

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    if (['node_modules', '.nuxt', '.output', 'dist', 'tests', 'locales', 'i18n'].includes(name)) continue
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p, out)
    else if (/\.(vue|js)$/.test(name) && !/\.config\.js$/.test(name)) out.push(p)
  }
  return out
}

const messages = buildMessages(loadFiles())

function lookup(obj, key) {
  return key.split('.').reduce((o, k) => (o && typeof o === 'object' ? o[k] : undefined), obj)
}

describe('locales', () => {
  it('every locale has the same files', () => {
    const names = LOCALES.map((c) => readdirSync(join(ROOT, 'i18n', 'locales', c)).filter((n) => n.endsWith('.json')).sort())
    expect(names[1]).toEqual(names[0])
    expect(names[2]).toEqual(names[0])
  })

  it('every locale has the same keys', () => {
    const en = flatKeys(messages.en)
    for (const code of ['ru', 'uk']) {
      const keys = flatKeys(messages[code])
      expect(keys.filter((k) => !en.includes(k)), `${code}: keys missing in en`).toEqual([])
      expect(en.filter((k) => !keys.includes(k)), `${code}: keys missing in ${code}`).toEqual([])
    }
  })

  it('no empty strings', () => {
    for (const code of LOCALES) {
      const empty = flatKeys(messages[code]).filter((k) => {
        const v = lookup(messages[code], k)
        return typeof v === 'string' && !v.trim()
      })
      expect(empty, code).toEqual([])
    }
  })

  it('plural forms: ru/uk have 3 or 4 forms whenever en is plural', () => {
    for (const key of flatKeys(messages.en)) {
      const en = lookup(messages.en, key)
      if (typeof en !== 'string' || !en.includes(' | ')) continue
      for (const code of ['ru', 'uk']) {
        const forms = String(lookup(messages[code], key)).split(' | ').length
        expect([3, 4], `${code}.${key}`).toContain(forms)
      }
    }
  })

  it('placeholders match across locales', () => {
    const vars = (s) => [...String(s).matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort()
    for (const key of flatKeys(messages.en)) {
      const en = [...new Set(vars(lookup(messages.en, key)))]
      for (const code of ['ru', 'uk']) {
        const other = [...new Set(vars(lookup(messages[code], key)))]
        expect(other, `${code}.${key}`).toEqual(en)
      }
    }
  })

  it('every literal key used in the code exists', () => {
    const used = new Map()
    for (const file of walk(ROOT)) {
      const src = readFileSync(file, 'utf8')
      for (const m of src.matchAll(/(?<![\w.])\$?(?:t|te|tm)\(\s*['"]([a-zA-Z][\w-]*(?:\.[\w-]+)+)['"]/g)) {
        used.set(m[1], relative(ROOT, file))
      }
      for (const m of src.matchAll(/(?:keypath|i18n-key)="([a-zA-Z][\w-]*(?:\.[\w-]+)+)"/g)) {
        used.set(m[1], relative(ROOT, file))
      }
    }
    const missing = [...used].filter(([key]) => lookup(messages.en, key) === undefined)
      .map(([key, file]) => `${key} (${file})`)
    expect(missing).toEqual([])
  })

  it('no Cyrillic text outside locales', () => {
    const offenders = walk(ROOT).filter((f) => /[Ѐ-ӿ]/.test(readFileSync(f, 'utf8')))
      .map((f) => relative(ROOT, f))
    expect(offenders).toEqual([])
  })

  it('two files with the same namespace are rejected', () => {
    expect(() => buildMessages({
      './locales/en/a.json': { x: { a: 1 } },
      './locales/en/b.json': { x: { b: 1 } },
    })).toThrow(/defined twice/)
  })
})
