<template>
  <section class="card p-4">
    <h2 class="text-sm font-semibold">{{ t('connection.caps.title') }}</h2>
    <ul class="mt-3 space-y-3">
      <li v-for="cap in caps" :key="cap.id" class="flex gap-3">
        <span class="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full" :class="TONE[capabilityTone(cap.state)]">
          <AppIcon :name="ICON[capabilityTone(cap.state)]" :size="14" />
        </span>
        <div class="min-w-0 flex-1">
          <div class="flex flex-wrap items-baseline gap-x-2">
            <span class="text-sm font-medium">{{ t(`connection.caps.names.${cap.id}`) }}</span>
            <span class="text-xs muted">{{ t(`connection.caps.state.${cap.state}`) }}</span>
            <span v-if="cap.preview" class="badge bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-200">{{ t('connection.caps.preview') }}</span>
          </div>
          <p v-if="cap.model_title" class="truncate text-xs muted" :title="cap.model_id">{{ cap.model_title }} · {{ cap.region }}</p>
          <ConnectionErrorHelp
            v-if="cap.state === 'error'"
            class="mt-1.5"
            :error="cap.error"
            :project-id="projectId"
            @step="$emit('step', $event)"
          />
          <p v-else class="mt-0.5 text-xs muted">{{ hint(cap) }}</p>
        </div>
      </li>
    </ul>

    <div class="mt-4 space-y-3 border-t border-slate-100 pt-4 dark:border-slate-700/60">
      <div class="flex flex-wrap items-center gap-3">
        <PriceButton
          :label="t('connection.caps.imageRun')"
          icon="image"
          variant="secondary"
          :estimate="imageEstimate"
          :busy="busy === 'image'"
          :disabled="!!busy || !state?.key || !byId.images?.model_id"
          @click="$emit('image')"
        />
        <span class="min-w-0 flex-1 text-xs muted">{{ t('connection.caps.imageHint') }}</span>
      </div>
      <figure v-if="state?.test_image" class="space-y-1">
        <a :href="state.test_image.url" target="_blank" rel="noopener">
          <img
            :src="state.test_image.thumb_url || state.test_image.url"
            :alt="t('connection.caps.imageResult')"
            class="h-32 w-32 rounded-card border border-slate-200 object-cover dark:border-slate-700"
          >
        </a>
        <figcaption class="text-xs muted">{{ t('connection.caps.imageResult') }}</figcaption>
      </figure>

      <div class="flex flex-wrap items-center gap-3">
        <PriceButton
          :label="t('connection.caps.omniRun')"
          icon="video"
          variant="secondary"
          :estimate="omniEstimate"
          :busy="busy === 'omni'"
          :disabled="!!busy || !state?.key || !state?.omni_check_available || !byId.omni?.model_id"
          @click="$emit('omni')"
        />
        <span class="min-w-0 flex-1 text-xs muted">
          {{ state?.omni_check_available ? t('connection.caps.omniHint', { seconds: omniSeconds }) : t('connection.caps.omniUnavailable') }}
        </span>
      </div>
    </div>
  </section>
</template>

<script setup>
// The four ticks (pictures, text, Veo, Omni) and the two paid live tests.
import { capabilityTone } from '~/utils/connectionView.js'

const props = defineProps({
  state: { type: Object, default: null },
  busy: { type: String, default: '' },
})
defineEmits(['image', 'omni', 'step'])

const { t } = useI18n()

const TONE = {
  ok: 'bg-emerald-500 text-white',
  good: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-300',
  bad: 'bg-rose-500 text-white',
  warn: 'bg-amber-100 text-amber-700 dark:bg-amber-500/20 dark:text-amber-300',
  idle: 'bg-slate-100 text-slate-400 dark:bg-slate-700',
}
const ICON = { ok: 'check', good: 'check', bad: 'alert', warn: 'info', idle: 'more' }

const caps = computed(() => props.state?.capabilities || [])
const byId = computed(() => Object.fromEntries(caps.value.map((c) => [c.id, c])))
const projectId = computed(() => props.state?.key?.project_id || '')
const omniSeconds = computed(() => byId.value.omni?.check_seconds || 3)

const imageEstimate = computed(() => (byId.value.images?.model_id
  ? { kind: 'image', model_id: byId.value.images.model_id, purpose: 'connection_check' }
  : null))
const omniEstimate = computed(() => (byId.value.omni?.model_id
  ? { kind: 'video', model_id: byId.value.omni.model_id, seconds: omniSeconds.value, resolution: '720p' }
  : null))

function hint(cap) {
  if (cap.state === 'unknown' && cap.id === 'omni') return t('connection.caps.hint.unknownOmni')
  return t(`connection.caps.hint.${cap.state}`)
}
</script>
