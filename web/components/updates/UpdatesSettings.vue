<template>
  <section class="card space-y-4 p-5">
    <div>
      <h2 class="text-base font-semibold">{{ t('updates.settings.title') }}</h2>
      <p v-if="disabled" class="text-sm muted">{{ t('updates.settings.devNote') }}</p>
    </div>

    <ToggleSwitch v-model="draft.auto" :disabled="disabled || saving" :label="t('updates.settings.auto')" />

    <div class="grid gap-4 sm:grid-cols-3">
      <div>
        <label class="label" for="vf-update-time">{{ t('updates.settings.time') }}</label>
        <input
          id="vf-update-time"
          v-model="draft.time"
          type="time"
          class="input"
          required
          :disabled="disabled || saving || !draft.auto"
        >
      </div>
      <div class="sm:col-span-2">
        <label class="label" for="vf-update-tz">{{ t('updates.settings.tz') }}</label>
        <select id="vf-update-tz" v-model="draft.tz" class="input" :disabled="disabled || saving || !draft.auto">
          <option v-for="tz in zones" :key="tz" :value="tz">{{ tz }}</option>
        </select>
      </div>
    </div>
    <p class="-mt-2 text-xs muted">{{ t('updates.settings.timeHint') }}</p>

    <p
      v-if="tzMismatch"
      class="flex flex-wrap items-center gap-2 rounded-card bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:bg-amber-500/10 dark:text-amber-100"
    >
      <AppIcon name="info" :size="16" class="shrink-0" />
      <span class="min-w-0 flex-1">{{ t('updates.settings.tzMismatch', { saved: draft.tz, local: localTz }) }}</span>
      <button type="button" class="btn-secondary btn-sm" :disabled="disabled || saving" @click="draft.tz = localTz">
        {{ t('updates.settings.useLocalTz', { local: localTz }) }}
      </button>
    </p>

    <div>
      <label class="label" for="vf-update-channel">{{ t('updates.settings.channel') }}</label>
      <select id="vf-update-channel" v-model="draft.channel" class="input sm:max-w-xs" :disabled="disabled || saving">
        <option v-for="c in UPDATE_CHANNELS" :key="c" :value="c">{{ t(`updates.channel.${c}`) }}</option>
      </select>
      <p class="mt-1 text-xs muted">{{ draft.channel === 'beta' ? t('updates.settings.betaHint') : t('updates.settings.stableHint') }}</p>
    </div>

    <div class="flex flex-wrap items-center justify-end gap-2">
      <button v-if="dirty" type="button" class="btn-ghost" :disabled="saving" @click="reset">{{ t('common.cancel') }}</button>
      <button type="button" class="btn-primary" :disabled="disabled || saving || !dirty || !validTime" @click="save">
        <Spinner v-if="saving" :size="16" />{{ t('common.save') }}
      </button>
    </div>
  </section>
</template>

<script setup>
import { UPDATE_CHANNELS, draftFrom, localTimeZone, settingsDiff, timeZones, updatesErrorText } from '~/utils/updatesView.js'

const props = defineProps({
  status: { type: Object, required: true },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['saved'])
const { t, te } = useI18n()
const toast = useToast()

const draft = ref(draftFrom(props.status))
const saving = ref(false)
const localTz = localTimeZone()

const changes = computed(() => settingsDiff(props.status, draft.value))
const dirty = computed(() => Object.keys(changes.value).length > 0)
const validTime = computed(() => /^(?:[01]\d|2[0-3]):[0-5]\d$/.test(draft.value.time || ''))
const zones = computed(() => timeZones(draft.value.tz))
const tzMismatch = computed(() => draft.value.auto && draft.value.tz !== localTz && draft.value.tz === 'UTC')

function reset() {
  draft.value = draftFrom(props.status)
}

// New data from the updater replaces the form unless the human is editing it.
watch(() => [props.status.auto, props.status.time, props.status.tz, props.status.channel], () => {
  if (!dirty.value || saving.value) reset()
})

async function save() {
  if (!dirty.value) return
  saving.value = true
  try {
    const next = await useApi().post('/api/updates/settings', changes.value)
    emit('saved', next)
    draft.value = draftFrom(next?.updater || { ...props.status, ...changes.value })
    toast.success(t('updates.settings.saved'))
  } catch (err) {
    toast.error(updatesErrorText(err, t, te))
  } finally {
    saving.value = false
  }
}
</script>
