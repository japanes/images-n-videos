<template>
  <div class="space-y-4 text-sm">
    <div v-if="part === 'lift'" class="rounded-card bg-slate-50 p-3 dark:bg-slate-900/60">
      <p class="font-medium">{{ t('connection.policy.whyTitle') }}</p>
      <ConnectionRichText tag="p" class="mt-1 muted" :text="t('connection.policy.why')" />
    </div>

    <section v-for="group in groups" :key="group.title">
      <h4 class="font-semibold">{{ group.title }}</h4>
      <ol class="mt-2 list-decimal space-y-2 pl-5">
        <li v-for="line in group.lines" :key="line.id">
          <ConnectionRichText :text="t(`connection.policy.${linesOf}.${line.id}`)" />
          <ConnectionLink v-if="line.link" :id="line.link" :project-id="projectId" class="ml-2" />
        </li>
      </ol>
    </section>

    <p v-if="part === 'lift'" class="muted">{{ t('connection.policy.again') }}</p>

    <details v-if="part === 'lift'" class="rounded-card border border-slate-200 px-3 py-2 dark:border-slate-700">
      <summary class="cursor-pointer font-medium">{{ t('connection.policy.troubleTitle') }}</summary>
      <ul class="mt-2 list-disc space-y-2 pl-5">
        <li v-for="line in POLICY.trouble" :key="line.id">
          <ConnectionRichText :text="t(`connection.policy.trouble.${line.id}`)" />
        </li>
      </ul>
    </details>

    <details class="rounded-card border border-slate-200 px-3 py-2 dark:border-slate-700">
      <summary class="cursor-pointer font-medium">{{ t('connection.policy.shellTitle') }}</summary>
      <div class="mt-2 space-y-2">
        <p class="muted">
          <ConnectionRichText :text="t('connection.policy.shellText')" />
          <ConnectionLink id="cloudShell" class="ml-2" />
        </p>
        <p>{{ part === 'lift' ? t('connection.policy.shellLift') : t('connection.policy.shellRestore') }}</p>
        <div class="relative">
          <pre class="overflow-x-auto rounded-card bg-slate-900 p-3 pr-12 font-mono text-xs leading-relaxed text-slate-100">{{ commands }}</pre>
          <button
            type="button"
            class="btn-ghost btn-sm absolute right-1 top-1 text-slate-200 hover:bg-white/10"
            :title="t('common.copy')"
            @click="copy"
          >
            <AppIcon name="copy" :size="14" />
          </button>
        </div>
      </div>
    </details>
  </div>
</template>

<script setup>
// The ban on service-account key files (guide "google-key-policy"):
// part="lift" shows why + parts 1–2, part="restore" shows part 3.
import { POLICY, liftCommands, restoreCommands } from '~/utils/connectionView.js'

const props = defineProps({
  part: { type: String, default: 'lift' },
  projectId: { type: String, default: '' },
})

const { t } = useI18n()
const toast = useToast()

const linesOf = computed(() => (props.part === 'lift' ? 'lift' : 'restore'))
const groups = computed(() => (props.part === 'lift'
  ? [
      { title: t('connection.policy.part1'), lines: POLICY.lift.filter((l) => l.part === 1) },
      { title: t('connection.policy.part2'), lines: POLICY.lift.filter((l) => l.part === 2) },
    ]
  : [{ title: t('connection.policy.part3'), lines: POLICY.restore }]))
const commands = computed(() => (props.part === 'lift' ? liftCommands(props.projectId) : restoreCommands(props.projectId)))

async function copy() {
  try {
    await navigator.clipboard.writeText(commands.value)
    toast.success(t('common.copied'))
  } catch {
    toast.error(t('errors.generic', { code: 'clipboard' }))
  }
}
</script>
