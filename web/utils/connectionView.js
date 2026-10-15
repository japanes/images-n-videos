/**
 * Pure helpers of the Google connection screen and first-run wizard (module 01):
 * the setup instruction as data, console links, error hints, small text markup.
 * No Vue here, so everything is unit-tested in tests/connection.test.js.
 */
import { apiErrorText } from '~/utils/apiErrorText.js'

export const LINKS = {
  freeTrial: 'https://cloud.google.com/free',
  createProject: 'https://console.cloud.google.com/projectcreate',
  billing: 'https://console.cloud.google.com/billing/linkedaccount',
  api: 'https://console.cloud.google.com/apis/library/aiplatform.googleapis.com',
  serviceAccounts: 'https://console.cloud.google.com/iam-admin/serviceaccounts',
  iam: 'https://console.cloud.google.com/iam-admin/iam',
  orgPolicies: 'https://console.cloud.google.com/iam-admin/orgpolicies',
  budgets: 'https://console.cloud.google.com/billing/budgets',
  quotas: 'https://console.cloud.google.com/iam-admin/quotas?service=aiplatform.googleapis.com',
  pricing: 'https://cloud.google.com/vertex-ai/generative-ai/pricing',
  cloudShell: 'https://shell.cloud.google.com',
}

// Pages that belong to one project: the link opens them for the user's project.
const PROJECT_PAGES = new Set(['billing', 'api', 'serviceAccounts', 'iam', 'orgPolicies', 'quotas'])

/** Console link; project pages get `?project=<id>` once the key tells us the id. */
export function consoleUrl(linkId, projectId) {
  const base = LINKS[linkId]
  if (!base) return ''
  if (!projectId || !PROJECT_PAGES.has(linkId)) return base
  return `${base}${base.includes('?') ? '&' : '?'}project=${encodeURIComponent(projectId)}`
}

/**
 * The setup instruction, step by step. Texts live in
 * `connection.guide.steps.<id>.{title,text}`, link labels in `connection.links.<linkId>`.
 * Error hints refer to these numbers ("see step 3"), so keep the order.
 */
export const GUIDE_STEPS = [
  { id: 'register', links: ['freeTrial', 'pricing'] },
  { id: 'project', links: ['createProject'] },
  { id: 'billing', links: ['billing'] },
  { id: 'api', links: ['api'] },
  { id: 'account', links: ['serviceAccounts', 'iam'] },
  { id: 'ban', links: [], policy: 'lift' },
  { id: 'key', links: ['serviceAccounts'] },
  { id: 'budget', links: ['budgets'], optional: true },
].map((s, i) => ({ ...s, number: i + 1 }))

export function stepNumber(id) {
  return GUIDE_STEPS.find((s) => s.id === id)?.number ?? null
}

/**
 * The ban on key files (guide "google-key-policy"): parts and their lines.
 * Texts: `connection.policy.<part>.<line>`; `link` is shown after the line.
 */
export const POLICY = {
  lift: [
    { id: 'iam', link: 'iam', part: 1 },
    { id: 'org', part: 1 },
    { id: 'grant', part: 1 },
    { id: 'project', part: 2 },
    { id: 'policies', link: 'orgPolicies', part: 2 },
    { id: 'override', part: 2 },
    { id: 'wait', part: 2 },
    { id: 'key', link: 'serviceAccounts', part: 2 },
  ],
  restore: [
    { id: 'policies', link: 'orgPolicies' },
    { id: 'inherit' },
    { id: 'role', link: 'iam' },
    { id: 'keeps' },
  ],
  trouble: [{ id: 'noGrant' }, { id: 'inactive' }, { id: 'stillBanned' }, { id: 'noKeys' }],
}

export const POLICY_CONSTRAINTS = ['iam.disableServiceAccountKeyCreation', 'iam.managed.disableServiceAccountKeyCreation']

function projectLine(projectId) {
  // A real project id has only [a-z0-9-]; anything else falls back to the placeholder.
  const id = /^[a-z][a-z0-9-]{5,29}$/.test(projectId || '') ? projectId : 'your-project-id'
  return `PROJECT_ID="${id}"`
}

const SHELL_HEAD = [
  'EMAIL="$(gcloud config get-value account)"',
  'ORG_ID="$(gcloud projects get-ancestors "$PROJECT_ID" --format=\'value(id)\' | tail -n1)"',
]

/** Cloud Shell commands that lift the ban (parts 1–2 of the guide). */
export function liftCommands(projectId) {
  return [
    projectLine(projectId),
    ...SHELL_HEAD,
    '',
    'gcloud organizations add-iam-policy-binding "$ORG_ID" \\',
    '  --member="user:$EMAIL" --role=roles/orgpolicy.policyAdmin',
    '',
    `for C in ${POLICY_CONSTRAINTS.join(' ')}; do`,
    '  printf \'name: projects/%s/policies/%s\\nspec:\\n  rules:\\n  - enforce: false\\n\' "$PROJECT_ID" "$C" > policy.yaml',
    '  gcloud org-policies set-policy policy.yaml',
    'done',
    'rm policy.yaml',
  ].join('\n')
}

/** Cloud Shell commands that restore the ban (part 3 of the guide). */
export function restoreCommands(projectId) {
  return [
    projectLine(projectId),
    ...SHELL_HEAD,
    '',
    `for C in ${POLICY_CONSTRAINTS.join(' ')}; do`,
    '  gcloud org-policies delete "$C" --project="$PROJECT_ID"',
    'done',
    'gcloud organizations remove-iam-policy-binding "$ORG_ID" \\',
    '  --member="user:$EMAIL" --role=roles/orgpolicy.policyAdmin',
  ].join('\n')
}

// ── errors ─────────────────────────────────────────────────────────────────

/** Errors with a connection-specific explanation: `connection.errors.<code>`. */
export const ERROR_HELP = {
  billing_disabled: { step: 'billing', links: ['billing'] },
  api_disabled: { step: 'api', links: ['api'] },
  permission_denied: { step: 'account', links: ['iam', 'serviceAccounts'] },
  invalid_grant: { step: 'key', links: ['serviceAccounts'] },
  model_not_found: { links: [] },
  rate_limited: { links: ['quotas'] },
  no_key: { links: [] },
  check_running: { links: [] },
  check_unavailable: { links: [] },
}

export const UPLOAD_REASONS = [
  'too_large', 'empty', 'not_json', 'oauth_client', 'not_service_account', 'missing_fields', 'bad_private_key',
]

/** Hint for a failed check: text key, instruction step and console links. Null for unknown codes. */
export function errorHelp(code, projectId) {
  const help = ERROR_HELP[code]
  if (!help) return null
  return {
    key: `connection.errors.${code}`,
    step: help.step ? stepNumber(help.step) : null,
    stepId: help.step || null,
    links: help.links.map((id) => ({ id, url: consoleUrl(id, projectId) })),
  }
}

/** Locale key for an ApiError of this screen, or null to use the app-wide text. */
export function connectionErrorKey(err) {
  const code = err?.code
  if (code === 'key_invalid' && UPLOAD_REASONS.includes(err?.details?.reason)) {
    return `connection.upload.reasons.${err.details.reason}`
  }
  return ERROR_HELP[code] ? `connection.errors.${code}` : null
}

export function connectionErrorText(err, t, te) {
  const key = connectionErrorKey(err)
  if (!key) return apiErrorText(err, t, te)
  const fields = Array.isArray(err?.details?.fields) ? err.details.fields.join(', ') : ''
  return t(key, { fields })
}

/** A file the browser can turn down before uploading (the server checks everything again). */
export function precheckKeyFile(file, maxBytes) {
  if (!file) return 'empty'
  if (!file.size) return 'empty'
  if (maxBytes && file.size > maxBytes) return 'too_large'
  return null
}

// ── checks and ticks ───────────────────────────────────────────────────────

export const CHECK_NAMES = ['token', 'models', 'text', 'image', 'omni']
export const CAPABILITIES = ['images', 'text', 'veo', 'omni']

/** Colour group of a capability tick. */
export function capabilityTone(state) {
  if (state === 'ok') return 'ok'
  if (state === 'seen') return 'good'
  if (state === 'error' || state === 'blocked') return 'bad'
  if (state === 'not_listed' || state === 'no_model') return 'warn'
  return 'idle'
}

/** Status of one check row: ok | error | skipped | none. */
export function checkStatus(result) {
  return result?.status || 'none'
}

/** The basic checks (token and test text) passed: the key works. */
export function basicChecksPassed(state) {
  const c = state?.checks || {}
  return c.token?.status === 'ok' && c.text?.status === 'ok'
}

/** Error that stops everything (shown once above the ticks), or null. */
export function blockingError(state) {
  for (const name of ['token', 'models', 'text']) {
    const res = state?.checks?.[name]
    if (res?.status === 'error' && (state?.capabilities || []).some((c) => c.blocked_by === res.error?.code)) {
      return { check: name, ...res.error }
    }
  }
  return null
}

// ── wizard ─────────────────────────────────────────────────────────────────

export const WIZARD_STEPS = ['guide', 'upload', 'checks', 'ban', 'trial']

export function wizardIndex(step) {
  const i = WIZARD_STEPS.indexOf(step)
  return i < 0 ? 0 : i
}

/** Steps 1–2 need no key; with a key the wizard never goes back before "checks". */
export function nextWizardStep(step) {
  const i = wizardIndex(step)
  return i + 1 < WIZARD_STEPS.length ? WIZARD_STEPS[i + 1] : null
}

export function prevWizardStep(step, hasKey) {
  const i = wizardIndex(step)
  const first = hasKey ? wizardIndex('checks') : 0
  return i - 1 >= first ? WIZARD_STEPS[i - 1] : null
}

// ── trial ──────────────────────────────────────────────────────────────────

/** Today as YYYY-MM-DD in local time (for the date input's max). */
export function localDay(now = new Date()) {
  const p = (n) => String(n).padStart(2, '0')
  return `${now.getFullYear()}-${p(now.getMonth() + 1)}-${p(now.getDate())}`
}

export function isValidDay(value, today = localDay()) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '')) return false
  const d = new Date(`${value}T00:00:00Z`)
  if (Number.isNaN(d.getTime()) || d.toISOString().slice(0, 10) !== value) return false
  return value <= today
}

// ── text markup ────────────────────────────────────────────────────────────

/**
 * Tiny markup for instruction texts in the locales: `**bold**` for button and
 * menu names, `` `code` `` for ids and role codes. Returns parts to render
 * without v-html. Unclosed markers stay as plain text.
 */
export function parseRich(text) {
  const parts = []
  const src = String(text ?? '')
  const re = /\*\*([^*]+)\*\*|`([^`]+)`/g
  let last = 0
  let m
  while ((m = re.exec(src)) !== null) {
    if (m.index > last) parts.push({ type: 'text', value: src.slice(last, m.index) })
    parts.push(m[1] !== undefined ? { type: 'bold', value: m[1] } : { type: 'code', value: m[2] })
    last = re.lastIndex
  }
  if (last < src.length) parts.push({ type: 'text', value: src.slice(last) })
  return parts
}

/** Every locale key the instruction data refers to (checked by the tests). */
export function guideKeys() {
  const keys = []
  for (const s of GUIDE_STEPS) {
    keys.push(`connection.guide.steps.${s.id}.title`, `connection.guide.steps.${s.id}.text`)
    for (const l of s.links) keys.push(`connection.links.${l}`)
  }
  for (const [part, lines] of Object.entries(POLICY)) {
    for (const line of lines) {
      keys.push(`connection.policy.${part}.${line.id}`)
      if (line.link) keys.push(`connection.links.${line.link}`)
    }
  }
  for (const [code, help] of Object.entries(ERROR_HELP)) {
    keys.push(`connection.errors.${code}`)
    for (const l of help.links) keys.push(`connection.links.${l}`)
  }
  for (const r of UPLOAD_REASONS) keys.push(`connection.upload.reasons.${r}`)
  for (const c of CHECK_NAMES) keys.push(`connection.checks.names.${c}`)
  for (const c of CAPABILITIES) keys.push(`connection.caps.names.${c}`)
  for (const s of ['ok', 'seen', 'not_listed', 'error', 'blocked', 'unknown', 'no_model']) keys.push(`connection.caps.state.${s}`)
  for (const s of ['ok', 'error', 'skipped', 'none']) keys.push(`connection.checks.status.${s}`)
  for (const s of WIZARD_STEPS) keys.push(`connection.wizard.steps.${s}`)
  return keys
}
