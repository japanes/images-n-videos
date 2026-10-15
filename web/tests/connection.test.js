import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import {
  CAPABILITIES, ERROR_HELP, GUIDE_STEPS, LINKS, POLICY_CONSTRAINTS, WIZARD_STEPS, basicChecksPassed, blockingError,
  capabilityTone, checkStatus, connectionErrorKey, connectionErrorText, consoleUrl, errorHelp, guideKeys, isValidDay,
  liftCommands, localDay, nextWizardStep, parseRich, precheckKeyFile, prevWizardStep, restoreCommands, stepNumber,
  wizardIndex,
} from '../utils/connectionView.js'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const locale = (code) => JSON.parse(readFileSync(join(ROOT, 'i18n', 'locales', code, 'connection.json'), 'utf8'))
const LOCALES = { en: locale('en'), ru: locale('ru'), uk: locale('uk') }
const lookup = (obj, key) => key.split('.').reduce((o, k) => (o && typeof o === 'object' ? o[k] : undefined), obj)

// Minimal t/te: looks keys up in the English file and fills {placeholders}.
const t = (key, params = {}) => {
  const v = lookup(LOCALES.en, key)
  if (typeof v !== 'string') return key
  return v.replace(/\{(\w+)\}/g, (_, name) => String(params[name] ?? ''))
}
const te = (key) => typeof lookup(LOCALES.en, key) === 'string'

describe('console links', () => {
  it('adds the project to project pages only', () => {
    expect(consoleUrl('billing', 'my-proj-123')).toBe(`${LINKS.billing}?project=my-proj-123`)
    expect(consoleUrl('quotas', 'my-proj-123')).toBe(`${LINKS.quotas}&project=my-proj-123`)
    expect(consoleUrl('freeTrial', 'my-proj-123')).toBe(LINKS.freeTrial)
    expect(consoleUrl('billing')).toBe(LINKS.billing)
    expect(consoleUrl('nope', 'x')).toBe('')
  })

  it('all links go to Google', () => {
    for (const url of Object.values(LINKS)) expect(url).toMatch(/^https:\/\/[a-z.]*google\.com(\/|$)/)
  })
})

describe('instruction steps and error hints', () => {
  it('keeps the numbering the error texts refer to', () => {
    expect(GUIDE_STEPS.map((s) => s.number)).toEqual(GUIDE_STEPS.map((_, i) => i + 1))
    expect(stepNumber('billing')).toBe(3)
    expect(stepNumber('api')).toBe(4)
    expect(stepNumber('account')).toBe(5)
    expect(stepNumber('key')).toBe(7)
    expect(stepNumber('missing')).toBeNull()
  })

  it('every hint with a step names that number in every language', () => {
    for (const [code, help] of Object.entries(ERROR_HELP)) {
      if (!help.step) continue
      for (const [lang, messages] of Object.entries(LOCALES)) {
        const text = lookup(messages, `connection.errors.${code}`)
        expect(text, `${lang} ${code}`).toContain(String(stepNumber(help.step)))
      }
    }
  })

  it('builds a hint with step and project links', () => {
    expect(errorHelp('billing_disabled', 'my-proj-123')).toEqual({
      key: 'connection.errors.billing_disabled',
      step: 3,
      stepId: 'billing',
      links: [{ id: 'billing', url: `${LINKS.billing}?project=my-proj-123` }],
    })
    expect(errorHelp('permission_denied').step).toBe(5)
    expect(errorHelp('rate_limited').step).toBeNull()
    expect(errorHelp('something_else')).toBeNull()
  })

  it('maps API errors to connection texts', () => {
    expect(connectionErrorKey({ code: 'key_invalid', details: { reason: 'oauth_client' } }))
      .toBe('connection.upload.reasons.oauth_client')
    expect(connectionErrorKey({ code: 'key_invalid', details: { reason: 'weird' } })).toBeNull()
    expect(connectionErrorKey({ code: 'api_disabled' })).toBe('connection.errors.api_disabled')
    expect(connectionErrorKey({ code: 'not_found' })).toBeNull()
    expect(connectionErrorKey(null)).toBeNull()
  })

  it('names the missing fields and keeps Google text for unknown errors', () => {
    const missing = connectionErrorText(
      { code: 'key_invalid', details: { reason: 'missing_fields', fields: ['private_key', 'client_email'] } }, t, te,
    )
    expect(missing).toContain('private_key, client_email')
    expect(connectionErrorText({ code: 'google_error', message: 'Quota exceeded for X' }, t, te))
      .toBe('Quota exceeded for X')
  })

  it('turns down empty and too large files before upload', () => {
    expect(precheckKeyFile(null, 65536)).toBe('empty')
    expect(precheckKeyFile({ size: 0 }, 65536)).toBe('empty')
    expect(precheckKeyFile({ size: 70000 }, 65536)).toBe('too_large')
    expect(precheckKeyFile({ size: 2300 }, 65536)).toBeNull()
    expect(precheckKeyFile({ size: 70000 })).toBeNull()
  })
})

describe('key ban commands', () => {
  it('use the project id only when it looks like one', () => {
    expect(liftCommands('my-proj-123')).toMatch(/^PROJECT_ID="my-proj-123"\n/)
    expect(liftCommands()).toMatch(/^PROJECT_ID="your-project-id"\n/)
    expect(liftCommands('x"; rm -rf ~; "')).toMatch(/^PROJECT_ID="your-project-id"\n/)
    expect(restoreCommands('my-proj-123')).toMatch(/^PROJECT_ID="my-proj-123"\n/)
  })

  it('cover both versions of the ban', () => {
    for (const c of POLICY_CONSTRAINTS) {
      expect(liftCommands('my-proj-123')).toContain(c)
      expect(restoreCommands('my-proj-123')).toContain(c)
    }
    expect(liftCommands('my-proj-123')).toContain('enforce: false')
    expect(liftCommands('my-proj-123')).toContain('add-iam-policy-binding')
    expect(restoreCommands('my-proj-123')).toContain('org-policies delete')
    expect(restoreCommands('my-proj-123')).toContain('remove-iam-policy-binding')
  })
})

describe('checks and ticks', () => {
  it('colours the ticks', () => {
    expect(capabilityTone('ok')).toBe('ok')
    expect(capabilityTone('seen')).toBe('good')
    expect(capabilityTone('error')).toBe('bad')
    expect(capabilityTone('blocked')).toBe('bad')
    expect(capabilityTone('not_listed')).toBe('warn')
    expect(capabilityTone('no_model')).toBe('warn')
    expect(capabilityTone('unknown')).toBe('idle')
    expect(capabilityTone(undefined)).toBe('idle')
  })

  it('reads check rows', () => {
    expect(checkStatus({ status: 'ok' })).toBe('ok')
    expect(checkStatus(null)).toBe('none')
  })

  it('the key works when token and text passed', () => {
    expect(basicChecksPassed({ checks: { token: { status: 'ok' }, text: { status: 'ok' } } })).toBe(true)
    expect(basicChecksPassed({ checks: { token: { status: 'ok' }, text: { status: 'error' } } })).toBe(false)
    expect(basicChecksPassed({ checks: {} })).toBe(false)
    expect(basicChecksPassed(null)).toBe(false)
  })

  it('shows one blocking error above the ticks', () => {
    const state = {
      checks: {
        token: { status: 'ok' },
        models: { status: 'ok' },
        text: { status: 'error', error: { code: 'billing_disabled', message: 'BILLING_DISABLED: verbatim' } },
      },
      capabilities: CAPABILITIES.map((id) => ({ id, state: 'blocked', blocked_by: 'billing_disabled' })),
    }
    expect(blockingError(state)).toEqual({ check: 'text', code: 'billing_disabled', message: 'BILLING_DISABLED: verbatim' })
    const notBlocking = { ...state, capabilities: [{ id: 'images', state: 'error', blocked_by: null }] }
    expect(blockingError(notBlocking)).toBeNull()
    expect(blockingError({})).toBeNull()
  })
})

describe('wizard', () => {
  it('walks forward to the end', () => {
    expect(WIZARD_STEPS[0]).toBe('guide')
    expect(nextWizardStep('guide')).toBe('upload')
    expect(nextWizardStep('ban')).toBe('trial')
    expect(nextWizardStep('trial')).toBeNull()
    expect(wizardIndex('nope')).toBe(0)
  })

  it('never goes back before the checks once a key is in', () => {
    expect(prevWizardStep('upload', false)).toBe('guide')
    expect(prevWizardStep('guide', false)).toBeNull()
    expect(prevWizardStep('checks', true)).toBeNull()
    expect(prevWizardStep('ban', true)).toBe('checks')
  })
})

describe('trial date', () => {
  it('accepts real past days only', () => {
    const today = '2026-10-15'
    expect(isValidDay('2026-09-14', today)).toBe(true)
    expect(isValidDay('2026-10-15', today)).toBe(true)
    expect(isValidDay('2026-10-16', today)).toBe(false)
    expect(isValidDay('2026-02-30', today)).toBe(false)
    expect(isValidDay('14.09.2026', today)).toBe(false)
    expect(isValidDay('', today)).toBe(false)
    expect(isValidDay(null, today)).toBe(false)
  })

  it('formats the local day', () => {
    expect(localDay(new Date(2026, 0, 5, 23, 59))).toBe('2026-01-05')
  })
})

describe('text markup', () => {
  it('splits bold and code without HTML', () => {
    expect(parseRich('Press **Create** and pick `roles/aiplatform.user`.')).toEqual([
      { type: 'text', value: 'Press ' },
      { type: 'bold', value: 'Create' },
      { type: 'text', value: ' and pick ' },
      { type: 'code', value: 'roles/aiplatform.user' },
      { type: 'text', value: '.' },
    ])
    expect(parseRich('<b>x</b> **open')).toEqual([{ type: 'text', value: '<b>x</b> **open' }])
    expect(parseRich(undefined)).toEqual([])
  })
})

describe('locales', () => {
  it('every key the instruction data needs exists in every language', () => {
    for (const [lang, messages] of Object.entries(LOCALES)) {
      const missing = guideKeys().filter((k) => typeof lookup(messages, k) !== 'string')
      expect(missing, lang).toEqual([])
    }
  })

  it('instruction markup is balanced', () => {
    const walk = (o, p, out) => {
      for (const [k, v] of Object.entries(o)) {
        if (v && typeof v === 'object') walk(v, `${p}.${k}`, out)
        else if ((String(v).match(/\*\*/g) || []).length % 2 || (String(v).match(/`/g) || []).length % 2) out.push(`${p}.${k}`)
      }
      return out
    }
    for (const [lang, messages] of Object.entries(LOCALES)) expect(walk(messages, lang, [])).toEqual([])
  })
})
