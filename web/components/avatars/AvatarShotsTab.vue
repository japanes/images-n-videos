<template>
  <!--
    Step 3 of the avatar card: the pack of 36 shots (angles, body, scenes,
    speech, emotions, gaze). Shot 1 is the face. «Draw the rest» draws only the
    empty shots, so pressing it again never pays twice for a shot that is
    there. Each shot is opened, changed and drawn again in the full-screen grid.
  -->
  <div class="space-y-4">
    <p v-if="!view.face" class="rounded-card bg-amber-50 p-3 text-amber-900 dark:bg-amber-500/10 dark:text-amber-100">
      {{ t('avatars.pack.needFace') }}
      <button type="button" class="ml-1 underline" @click="emit('tab', 'face')">{{ t('avatars.pack.toFace') }}</button>
    </p>

    <section class="space-y-2">
      <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span class="font-semibold">{{ t('avatars.card.count', { done: c.done, total: c.total }) }}</span>
        <span v-if="c.busy" class="inline-flex items-center gap-1 text-xs muted"><Spinner :size="10" />{{ t('avatars.pack.busy', { n: c.busy }) }}</span>
        <span v-if="c.failed" class="text-xs text-rose-700 dark:text-rose-300">{{ t('avatars.pack.failed', { n: c.failed }, c.failed) }}</span>
      </div>
      <div class="h-1.5 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
        <div class="h-full bg-primary transition-all" :style="{ width: `${c.total ? Math.round((c.done / c.total) * 100) : 0}%` }" />
      </div>
    </section>

    <!-- the 36 shots, small: a click opens the grid -->
    <button
      type="button"
      class="grid w-full grid-cols-9 gap-1 rounded-card text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-primary"
      :aria-label="t('avatars.pack.openGrid')"
      @click="emit('grid')"
    >
      <AvatarTile v-for="s in slots" :key="s.id" :photo="s" small />
    </button>

    <div class="flex flex-wrap items-center gap-2">
      <PriceButton
        icon="sparkles"
        :label="t('avatars.pack.finish', { n: est?.count || c.empty }, est?.count || c.empty)"
        :usd="usd"
        :disabled="Boolean(block) || usd === null || Boolean(busy)"
        :busy="busy === 'finish'"
        @click="finish"
      />
      <button type="button" class="btn-secondary btn-sm" @click="emit('grid')">
        <AppIcon name="eye" :size="14" />{{ t('avatars.pack.openGrid') }}
      </button>
      <a
        v-if="c.done"
        :href="avatarsExportUrl(view.id)"
        class="btn-secondary btn-sm"
        download
      >
        <AppIcon name="download" :size="14" />{{ t('avatars.pack.zip') }}
      </a>
      <button v-if="view.busy" type="button" class="btn-ghost btn-sm" :disabled="Boolean(busy)" @click="stopAll">
        <AppIcon name="stop" :size="14" />{{ t('avatars.pack.stop') }}
      </button>
    </div>
    <p v-if="block && block !== 'avatar_nothing_to_draw'" class="text-xs text-amber-700 dark:text-amber-300">{{ avatarsReasonText(block, t, te) }}</p>
    <p v-else-if="block" class="text-xs muted">{{ t('avatars.pack.allDone') }}</p>
    <p v-else-if="timeText" class="text-xs muted">{{ timeText }} · {{ t('avatars.pack.twoAtOnce') }}</p>

    <!-- calling the avatar by its name in other chats -->
    <section class="space-y-1 rounded-card border border-slate-200 p-3 dark:border-slate-700">
      <ToggleSwitch
        :model-value="view.as_subject"
        :label="t('avatars.pack.asSubject', { name: view.name })"
        :disabled="Boolean(busy)"
        @update:model-value="setSubject"
      />
      <p class="text-xs muted">
        {{ !view.as_subject ? t('avatars.pack.asSubjectOff')
          : view.subject_id ? t('avatars.pack.asSubjectOn', { name: view.name }) : t('avatars.pack.asSubjectWait') }}
      </p>
    </section>
  </div>
</template>

<script setup>
import {
  AVATAR_SHOT_COUNT, avatarsExportUrl, avatarsPackBlock, avatarsReasonText, avatarsTimeText,
} from '~/utils/avatarsView.js'
import { useAvatarAction, useAvatarEstimate } from '~/composables/useAvatars.js'

const props = defineProps({
  view: { type: Object, required: true },
})
const emit = defineEmits(['tab', 'grid'])
const { t, te } = useI18n()
const api = useApi()
const toast = useToast()
const { confirm } = useConfirm()
const { busy, act } = useAvatarAction()

const base = computed(() => `/api/avatars/${props.view.id}`)
const slots = computed(() => props.view.slots || [])
const c = computed(() => ({ done: 0, total: AVATAR_SHOT_COUNT, busy: 0, failed: 0, empty: 0, ...(props.view.counts || {}) }))

const block = computed(() => avatarsPackBlock(props.view))
const { est, usd } = useAvatarEstimate(
  () => props.view.id,
  () => (block.value ? null : { action: 'finish' }),
  () => [props.view.updated_at, props.view.image_model_id, c.value.empty],
)
const timeText = computed(() => avatarsTimeText(est.value?.time, t))

async function finish() {
  const res = await act('finish', () => api.post(`${base.value}/finish`))
  const skipped = res?.skipped || []
  if (!skipped.length) return
  const reasons = [...new Set(skipped.map((s) => avatarsReasonText(s.reason, t, te)).filter(Boolean))]
  toast.info([t('avatars.pack.skipped', { n: skipped.length }, skipped.length), ...reasons].join(' '))
}

async function stopAll() {
  if (!await confirm({ message: t('avatars.pack.stopAsk'), confirmLabel: t('avatars.pack.stop'), tone: 'danger' })) return
  await act('stop', () => api.post(`${base.value}/cancel`))
}

async function setSubject(on) {
  await act('subject', () => api.patch(base.value, { as_subject: Boolean(on) }))
}
</script>
