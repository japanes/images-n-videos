<template>
  <div class="space-y-4">
    <p class="text-sm muted">{{ t('models.roles.intro') }}</p>

    <section class="card space-y-2 p-4">
      <label class="block max-w-xl">
        <span class="label">{{ t('models.roles.defaultModel') }}</span>
        <select class="input" :value="defaultText?.id || ''" :disabled="busy" @change="makeDefault($event.target.value)">
          <option v-if="!defaultText" value="" disabled>—</option>
          <option v-for="m in textModels" :key="m.id" :value="m.id" :disabled="m.available === false">
            {{ optionText(m) }}
          </option>
        </select>
        <span class="mt-1 block text-xs muted">{{ t('models.roles.defaultHint') }}</span>
      </label>
      <p
        v-if="replacedText"
        class="flex gap-2 rounded-card bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:bg-amber-500/10 dark:text-amber-200"
      >
        <AppIcon name="alert" :size="16" class="mt-0.5 shrink-0" />{{ replacedText }}
      </p>
    </section>

    <section class="card">
      <header class="flex flex-wrap items-center gap-2 border-b border-slate-200 px-4 py-3 dark:border-slate-700">
        <h2 class="font-semibold">{{ t('models.roles.listTitle') }}</h2>
        <span v-if="changedCount" class="badge bg-sky-50 text-sky-700 dark:bg-sky-500/10 dark:text-sky-300">
          {{ t('models.roles.changed', { count: changedCount }) }}
        </span>
      </header>
      <ul class="divide-y divide-slate-100 dark:divide-slate-700">
        <li v-for="r in roles" :key="r.role" class="grid gap-3 px-4 py-3 md:grid-cols-[1fr_minmax(16rem,22rem)]">
          <div class="min-w-0">
            <p class="font-medium">{{ roleText(r.role, 'name') || r.role }}</p>
            <p v-if="roleText(r.role, 'description')" class="mt-0.5 text-sm muted">{{ roleText(r.role, 'description') }}</p>
            <p v-if="r.needs?.length" class="mt-1 flex flex-wrap items-center gap-1 text-xs muted">
              <span>{{ t('models.roles.needsTitle') }}</span>
              <span
                v-for="need in r.needs"
                :key="need"
                class="rounded-badge bg-slate-100 px-1.5 py-0.5 text-slate-700 dark:bg-slate-700 dark:text-slate-200"
              >{{ needText(need) }}</span>
            </p>
          </div>
          <div class="space-y-1">
            <select
              class="input"
              :value="r.override || ''"
              :disabled="busy || savingRole === r.role"
              :aria-label="roleText(r.role, 'name') || r.role"
              @change="setRole(r, $event.target.value)"
            >
              <option value="">{{ t('models.roles.useDefault', { model: defaultTitle }) }}</option>
              <option v-for="id in roleOptions(r)" :key="id" :value="id" :disabled="optionDisabled(r, id)">
                {{ optionText(find(id) || { id, title: id }) }}
              </option>
            </select>
            <p v-if="r.model_id" class="text-xs muted">{{ t('models.roles.nowUsed', { model: titleOf(r.model_id) }) }}</p>
            <p v-else class="text-xs text-rose-700 dark:text-rose-300">{{ t('models.roles.noModel') }}</p>
            <p v-if="r.override && r.model_id !== r.override" class="text-xs text-amber-700 dark:text-amber-300">
              {{ t('models.roles.overrideIgnored') }}
            </p>
          </div>
        </li>
      </ul>
    </section>
  </div>
</template>

<script setup>
import { apiErrorText } from '~/utils/apiErrorText.js'

const props = defineProps({
  models: { type: Array, default: () => [] },
  roles: { type: Array, default: () => [] },
  effectiveText: { type: String, default: '' },
})
const emit = defineEmits(['changed'])

const { t, te } = useI18n()
const api = useApi()
const toast = useToast()

const busy = ref(false)
const savingRole = ref('')

const textModels = computed(() => props.models.filter((m) => m.kind === 'text' && !m.removed))
const defaultText = computed(() => textModels.value.find((m) => m.is_default) || null)
const find = (id) => props.models.find((m) => m.id === id) || null
const titleOf = (id) => find(id)?.title || id
const defaultTitle = computed(() => titleOf(props.effectiveText || defaultText.value?.id || '') || '—')
const changedCount = computed(() => props.roles.filter((r) => r.override).length)

const replacedText = computed(() => {
  const d = defaultText.value
  if (!d || !props.effectiveText || props.effectiveText === d.id) return ''
  return t('models.replaced', { default: d.title || d.id, used: titleOf(props.effectiveText) })
})

function optionText(m) {
  const notes = []
  if (m.available === false) notes.push(t('models.roles.notInProject'))
  if (m.enabled === false) notes.push(t('models.roles.hidden'))
  const title = m.title || m.id
  return notes.length ? `${title} (${notes.join(', ')})` : title
}

function roleText(role, field) {
  const key = `models.roles.items.${role}.${field}`
  return te(key) ? t(key) : ''
}

function needText(need) {
  const key = `models.roles.needs.${need}`
  return te(key) ? t(key) : need
}

// The candidates (shown text models that can do the task) plus the current
// choice even when it is hidden now, so the select never shows a blank.
function roleOptions(r) {
  const ids = [...(r.candidates || [])]
  if (r.override && !ids.includes(r.override)) ids.push(r.override)
  return ids
}

function optionDisabled(r, id) {
  if (id === r.override) return false
  const m = find(id)
  return !m || m.available === false || m.enabled === false
}

async function makeDefault(id) {
  if (!id || id === defaultText.value?.id) return
  busy.value = true
  try {
    const model = await api.patch(`/api/models/${encodeURIComponent(id)}`, { is_default: true })
    toast.success(t('models.actions.madeDefault', { model: model?.title || id }))
    emit('changed')
  } catch (err) {
    toast.error(apiErrorText(err, t, te))
    emit('changed')
  } finally {
    busy.value = false
  }
}

async function setRole(r, value) {
  savingRole.value = r.role
  try {
    const res = await api.put(`/api/models/roles/${encodeURIComponent(r.role)}`, { model_id: value || null })
    const now = (res?.items || []).find((x) => x.role === r.role)
    toast.success(t('models.roles.saved', { model: now?.model_id ? titleOf(now.model_id) : '—' }))
    emit('changed', res?.items || null)
  } catch (err) {
    toast.error(apiErrorText(err, t, te))
    emit('changed', null)
  } finally {
    savingRole.value = ''
  }
}
</script>
