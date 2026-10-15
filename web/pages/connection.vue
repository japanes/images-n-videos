<template>
  <div class="page space-y-4">
    <div v-if="!state && loading" class="flex justify-center py-16"><Spinner :size="28" /></div>

    <div v-else-if="!state && loadError" class="flex flex-wrap items-center gap-3 rounded-card bg-rose-50 px-4 py-3 text-sm text-rose-800 dark:bg-rose-500/10 dark:text-rose-200">
      <AppIcon name="alert" :size="16" />
      <span class="min-w-0 flex-1">{{ t('connection.loadFailed') }} {{ loadError }}</span>
      <button type="button" class="btn-secondary btn-sm" @click="conn.load()">{{ t('common.retry') }}</button>
    </div>

    <!-- First run: a step-by-step wizard -->
    <section v-else-if="state && showWizard" class="mx-auto max-w-3xl space-y-4">
      <header>
        <h1 class="page-title">{{ t('connection.wizard.title') }}</h1>
        <p class="mt-1 text-sm muted">{{ t('connection.wizard.subtitle') }}</p>
      </header>
      <ConnectionStepper :step="step" />

      <div class="card p-4 sm:p-5">
        <p class="mb-3 text-xs font-medium uppercase tracking-wide muted">
          {{ t('connection.wizard.stepOf', { n: stepIndex + 1, total: WIZARD_STEPS.length }) }}
        </p>

        <ConnectionGuide v-if="step === 'guide'" :project-id="projectId" />

        <div v-else-if="step === 'upload'" class="space-y-3">
          <p class="text-sm">{{ t('connection.wizard.uploadIntro') }}</p>
          <ConnectionKeyDrop :busy="busy === 'upload'" :error="uploadError" @file="onWizardFile" />
        </div>

        <div v-else-if="step === 'checks'" class="space-y-3">
          <p class="text-sm">{{ t('connection.wizard.checksIntro') }}</p>
          <ConnectionChecks :state="state" :busy="busy" @check="runCheck" @step="openGuide" />
          <p
            v-if="passed"
            class="flex gap-2 rounded-input bg-emerald-50 px-3 py-2 text-sm text-emerald-800 dark:bg-emerald-500/10 dark:text-emerald-200"
          >
            <AppIcon name="check" :size="16" class="mt-0.5 shrink-0" />{{ t('connection.wizard.checksPassed') }}
          </p>
          <p
            v-else-if="state.last_check_at"
            class="flex gap-2 rounded-input bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:bg-amber-500/10 dark:text-amber-200"
          >
            <AppIcon name="info" :size="16" class="mt-0.5 shrink-0" />{{ t('connection.wizard.checksFailed') }}
          </p>
          <div>
            <button type="button" class="btn-ghost btn-sm" :aria-expanded="otherFileOpen" @click="otherFileOpen = !otherFileOpen">
              <AppIcon :name="otherFileOpen ? 'chevron-down' : 'chevron-right'" :size="14" />{{ t('connection.wizard.otherFile') }}
            </button>
            <div v-if="otherFileOpen" class="mt-2">
              <ConnectionKeyDrop :busy="busy === 'upload'" :error="uploadError" @file="onWizardFile" />
            </div>
          </div>
        </div>

        <div v-else-if="step === 'ban'" class="space-y-3">
          <p class="text-sm">{{ t('connection.wizard.banIntro') }}</p>
          <p class="text-xs muted">{{ t('connection.wizard.banNothing') }}</p>
          <ConnectionKeyPolicy part="restore" :project-id="projectId" />
        </div>

        <div v-else-if="step === 'trial'" class="space-y-1">
          <p class="text-sm">{{ t('connection.wizard.trialIntro') }}</p>
          <ConnectionTrialDate :trial="state.trial" :busy="busy === 'marks'" :show-text="false" @save="saveTrial" />
        </div>

        <footer class="mt-5 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-4 dark:border-slate-700/60">
          <button v-if="prevStep" type="button" class="btn-ghost" :disabled="!!busy" @click="go(prevStep)">
            <AppIcon name="chevron-left" :size="16" />{{ t('connection.wizard.back') }}
          </button>
          <span class="flex-1" />
          <template v-if="step === 'guide'">
            <button type="button" class="btn-primary" @click="go('upload')">{{ t('connection.wizard.haveKey') }}</button>
          </template>
          <template v-else-if="step === 'checks'">
            <button type="button" class="btn-ghost" :disabled="!!busy" @click="finishWizard(false)">{{ t('connection.wizard.later') }}</button>
            <button type="button" class="btn-primary" :disabled="!passed || !!busy" @click="go('ban')">
              {{ t('connection.wizard.next') }}<AppIcon name="chevron-right" :size="16" />
            </button>
          </template>
          <template v-else-if="step === 'ban'">
            <button type="button" class="btn-ghost" :disabled="!!busy" @click="go('trial')">{{ t('connection.wizard.skip') }}</button>
            <button type="button" class="btn-primary" :disabled="!!busy" @click="banRestoredInWizard">
              <Spinner v-if="busy === 'marks'" :size="14" />{{ t('connection.wizard.banDone') }}
            </button>
          </template>
          <template v-else-if="step === 'trial'">
            <button type="button" class="btn-primary" :disabled="!!busy" @click="finishWizard(true)">
              {{ state.trial?.started_on ? t('connection.wizard.finish') : t('connection.wizard.skip') }}
            </button>
          </template>
        </footer>
      </div>
    </section>

    <!-- The connection screen -->
    <template v-else-if="state">
      <header class="flex flex-wrap items-start gap-3">
        <div class="min-w-0 flex-1">
          <h1 class="page-title">{{ t('connection.title') }}</h1>
          <p class="mt-1 text-sm muted">{{ t('connection.subtitle') }}</p>
        </div>
        <button type="button" class="btn-secondary" @click="openGuide('')">
          <AppIcon name="info" :size="16" />{{ t('connection.openGuide') }}
        </button>
      </header>

      <div class="grid gap-4 lg:grid-cols-2">
        <div class="space-y-4">
          <ConnectionKeyCard
            :key-info="state.key"
            :last-check-at="state.last_check_at"
            :busy="busy"
            @replace="askReplace"
            @delete="askDelete"
          />
          <ConnectionChecks :state="state" :busy="busy" @check="runCheck" @step="openGuide" />
        </div>
        <div class="space-y-4">
          <ConnectionCapabilities :state="state" :busy="busy" @image="runImage" @omni="runOmni" @step="openGuide" />
          <ConnectionBanCard
            :restored="!!state.key_ban_restored"
            :project-id="projectId"
            :busy="busy === 'marks'"
            @mark="markBan"
          />
          <section class="card p-4">
            <h2 class="text-sm font-semibold">{{ t('connection.trial.title') }}</h2>
            <ConnectionTrialDate class="mt-1" :trial="state.trial" :busy="busy === 'marks'" @save="saveTrial" />
          </section>
        </div>
      </div>

      <details class="card p-4">
        <summary class="cursor-pointer text-sm font-semibold">{{ t('connection.regions.title') }}</summary>
        <p class="mt-2 text-sm muted">{{ t('connection.regions.text') }}</p>
        <div class="mt-3 overflow-x-auto">
          <table class="w-full text-left text-sm">
            <thead class="text-xs muted">
              <tr>
                <th class="py-1 pr-4 font-medium">{{ t('connection.regions.capability') }}</th>
                <th class="py-1 pr-4 font-medium">{{ t('connection.regions.model') }}</th>
                <th class="py-1 font-medium">{{ t('connection.regions.region') }}</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100 dark:divide-slate-700/60">
              <tr v-for="cap in state.capabilities" :key="cap.id">
                <td class="py-1.5 pr-4">{{ t(`connection.caps.names.${cap.id}`) }}</td>
                <td class="py-1.5 pr-4">{{ cap.model_title || cap.model_id || '—' }}</td>
                <td class="py-1.5 font-mono text-xs">{{ cap.region || '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="mt-2 text-xs muted">{{ t('connection.regions.list', { region: state.list_region }) }}</p>
      </details>
    </template>

    <ModalShell :open="guideOpen" :title="t('connection.guide.title')" size="lg" @close="guideOpen = false">
      <ConnectionGuide :project-id="projectId" :highlight="guideHighlight" />
    </ModalShell>

    <ModalShell :open="replaceOpen" :title="t('connection.upload.title')" @close="closeReplace">
      <ConnectionKeyDrop :busy="busy === 'upload'" :error="uploadError" @file="onReplaceFile" />
    </ModalShell>
  </div>
</template>

<script setup>
// Module 01: connecting Google Cloud. Without a key: the first-run wizard
// (instruction → key file → checks → restore the ban → trial date).
// With a key: the key card, checks, ticks, ban reminder and trial date.
import {
  WIZARD_STEPS, basicChecksPassed, prevWizardStep, precheckKeyFile, wizardIndex,
} from '~/utils/connectionView.js'

const { t } = useI18n()
const toast = useToast()
const { confirm } = useConfirm()
const conn = useConnection()
const { state, loading, loadError, busy } = conn

const inWizard = ref(false)
const step = ref('guide')
const uploadError = ref('')
const otherFileOpen = ref(false)
const guideOpen = ref(false)
const guideHighlight = ref('')
const replaceOpen = ref(false)

const hasKey = computed(() => !!state.value?.key)
const showWizard = computed(() => !hasKey.value || inWizard.value)
const projectId = computed(() => state.value?.key?.project_id || '')
const passed = computed(() => basicChecksPassed(state.value))
const stepIndex = computed(() => wizardIndex(step.value))
const prevStep = computed(() => prevWizardStep(step.value, hasKey.value))

// Key appears or disappears (here, in another tab, after a reload).
watch(hasKey, (now, before) => {
  if (state.value === null) return
  if (!now) {
    inWizard.value = true
    if (before !== undefined && wizardIndex(step.value) > wizardIndex('upload')) step.value = 'guide'
  } else if (inWizard.value && wizardIndex(step.value) < wizardIndex('checks')) {
    step.value = 'checks'
  }
})

onMounted(async () => {
  conn.listen()
  await conn.load()
  if (state.value && !state.value.key) inWizard.value = true
})

function go(next) {
  uploadError.value = ''
  otherFileOpen.value = false
  step.value = next
  if (import.meta.client) window.scrollTo({ top: 0, behavior: 'smooth' })
}

function openGuide(stepId) {
  guideHighlight.value = stepId || ''
  guideOpen.value = true
}

function toastError(err) {
  toast.error(conn.errorText(err))
}

// ── key file ──────────────────────────────────────────────────────────────

async function uploadFile(file) {
  uploadError.value = ''
  const reason = precheckKeyFile(file, state.value?.max_key_bytes)
  if (reason) {
    uploadError.value = t(`connection.upload.reasons.${reason}`, { fields: '' })
    return false
  }
  try {
    await conn.upload(file)
    return true
  } catch (err) {
    uploadError.value = conn.errorText(err)
    return false
  }
}

async function onWizardFile(file) {
  const replacing = hasKey.value
  if (!await uploadFile(file)) return
  otherFileOpen.value = false
  toast.success(replacing ? t('connection.upload.replaced') : t('connection.upload.uploaded'))
  step.value = 'checks'
}

async function askReplace() {
  const ok = await confirm({
    title: t('connection.key.replaceTitle'),
    message: t('connection.key.replaceText'),
    confirmLabel: t('connection.key.replaceConfirm'),
  })
  if (!ok) return
  uploadError.value = ''
  replaceOpen.value = true
}

function closeReplace() {
  if (busy.value === 'upload') return
  replaceOpen.value = false
  uploadError.value = ''
}

async function onReplaceFile(file) {
  if (!await uploadFile(file)) return
  replaceOpen.value = false
  toast.success(t('connection.upload.replaced'))
}

async function askDelete() {
  const ok = await confirm({
    title: t('connection.key.deleteTitle'),
    message: t('connection.key.deleteText'),
    confirmLabel: t('connection.key.delete'),
    tone: 'danger',
  })
  if (!ok) return
  try {
    await conn.removeKey()
    step.value = 'guide'
    toast.success(t('connection.key.deleted'))
  } catch (err) {
    toastError(err)
  }
}

// ── checks (paid ones are explicit clicks with the price on the button) ───

async function runCheck() {
  try { await conn.check() } catch (err) { toastError(err) }
}

async function runImage() {
  try { await conn.checkImage() } catch (err) { toastError(err) }
}

async function runOmni() {
  try { await conn.checkOmni() } catch (err) { toastError(err) }
}

// ── marks ─────────────────────────────────────────────────────────────────

async function markBan(restored) {
  try { await conn.saveMarks({ key_ban_restored: restored }) } catch (err) { toastError(err) }
}

async function banRestoredInWizard() {
  try {
    await conn.saveMarks({ key_ban_restored: true })
    go('trial')
  } catch (err) {
    toastError(err)
  }
}

async function saveTrial(day) {
  try {
    await conn.saveMarks({ trial_started_on: day })
    if (day) toast.success(t('connection.trial.saved'))
  } catch (err) {
    toastError(err)
  }
}

function finishWizard(done) {
  inWizard.value = false
  otherFileOpen.value = false
  if (done) toast.success(t('connection.wizard.done'))
  if (import.meta.client) window.scrollTo({ top: 0, behavior: 'smooth' })
}
</script>
