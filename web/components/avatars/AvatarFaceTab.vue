<template>
  <!--
    Step 2 of the avatar card: the face. Google draws a few faces from the
    written description (and the real photos of the person, when there are
    any); the person picks one. The picked face becomes shot 1 and the base of
    every other shot, and the description is locked so the face and the text
    stay one person. A real photo can be the face too (step 1, «Make face»).
  -->
  <div class="space-y-4">
    <section class="flex flex-wrap items-start gap-3">
      <div class="w-28 shrink-0">
        <AvatarTile v-if="facePhoto" :photo="facePhoto" small />
        <div v-else class="grid place-items-center rounded-card border border-dashed border-slate-300 muted dark:border-slate-600" :style="{ aspectRatio: '3 / 4' }">
          <AppIcon name="user" :size="24" />
        </div>
      </div>
      <div class="min-w-0 flex-1 space-y-1">
        <p class="font-semibold">{{ view.face ? t('avatars.candidates.current') : t('avatars.candidates.none') }}</p>
        <p class="text-xs muted">{{ t('avatars.candidates.text') }}</p>
        <button v-if="view.face" type="button" class="btn-ghost btn-sm" @click="emit('tab', 'shots')">
          {{ t('avatars.candidates.next') }}<AppIcon name="chevron-right" :size="14" />
        </button>
      </div>
    </section>

    <p v-if="!hasIdentity" class="rounded-card bg-amber-50 p-3 text-amber-900 dark:bg-amber-500/10 dark:text-amber-100">
      {{ t('avatars.candidates.needIdentity') }}
      <button type="button" class="ml-1 underline" @click="emit('tab', 'person')">{{ t('avatars.candidates.toPerson') }}</button>
    </p>

    <!-- what to draw -->
    <section class="space-y-3 rounded-card border border-slate-200 p-3 dark:border-slate-700">
      <div class="space-y-1">
        <span class="label">{{ t('avatars.candidates.count') }}</span>
        <div class="flex flex-wrap gap-1">
          <button
            v-for="n in counts"
            :key="n"
            type="button"
            class="btn-sm min-w-9"
            :class="view.candidate_count === n ? 'btn-primary' : 'btn-secondary'"
            :aria-pressed="view.candidate_count === n"
            :disabled="Boolean(busy)"
            @click="setCount(n)"
          >
            {{ n }}
          </button>
        </div>
      </div>
      <label class="block space-y-1">
        <span class="label">{{ t('avatars.candidates.model') }}</span>
        <select class="input" :value="view.image_model_id || ''" :disabled="Boolean(busy)" @change="setModel($event.target.value)">
          <option value="">{{ t('avatars.candidates.modelDefault') }}</option>
          <option v-for="m in modelChoices" :key="m.id" :value="m.id">{{ m.title || m.id }}</option>
          <option v-if="view.image_model_id && !modelChoices.some((m) => m.id === view.image_model_id)" :value="view.image_model_id">
            {{ view.image_model_id }}
          </option>
        </select>
        <span class="block text-xs muted">{{ t('avatars.candidates.modelText') }}</span>
      </label>
      <div class="flex flex-wrap items-center gap-2">
        <PriceButton
          icon="sparkles"
          :label="t('avatars.candidates.draw', { n: view.candidate_count }, view.candidate_count)"
          :usd="usd"
          :disabled="Boolean(block) || usd === null || Boolean(busy)"
          :busy="busy === 'draw'"
          @click="draw"
        />
        <span v-if="timeText" class="text-xs muted">{{ timeText }}</span>
      </div>
      <p v-if="block" class="text-xs text-amber-700 dark:text-amber-300">{{ avatarsReasonText(block, t, te) }}</p>
      <p v-else-if="est?.items?.[0]?.input_images" class="text-xs muted">
        {{ t('avatars.candidates.sends', { n: est.items[0].input_images }, est.items[0].input_images) }}
      </p>
    </section>

    <!-- the faces drawn -->
    <section v-if="candidates.length" class="space-y-2">
      <div class="flex flex-wrap items-center gap-2">
        <h4 class="min-w-0 flex-1 font-semibold">{{ t('avatars.candidates.title', { n: candidates.length }) }}</h4>
        <button v-if="anyBusy" type="button" class="btn-ghost btn-sm" :disabled="Boolean(busy)" @click="stopAll">
          <AppIcon name="stop" :size="14" />{{ t('avatars.pack.stop') }}
        </button>
      </div>
      <ul class="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <li v-for="c in candidates" :key="c.id" class="space-y-1.5">
          <a v-if="c.file" :href="c.file.url" target="_blank" rel="noopener" class="block">
            <AvatarTile :photo="c" />
          </a>
          <AvatarTile v-else :photo="c" />
          <div class="flex flex-wrap items-center gap-1">
            <span v-if="isFace(c)" class="badge bg-emerald-100 text-emerald-900 dark:bg-emerald-500/15 dark:text-emerald-100">{{ t('avatars.candidates.isFace') }}</span>
            <span v-else-if="c.meta?.picked" class="badge bg-slate-200/70 dark:bg-slate-700">{{ t('avatars.candidates.wasFace') }}</span>
            <button
              v-if="c.file_id && !isFace(c) && !avatarsSlotBusy(c)"
              type="button"
              class="btn-primary btn-sm"
              :disabled="Boolean(busy)"
              @click="pick(c)"
            >
              {{ t('avatars.candidates.pick') }}
            </button>
            <button v-if="avatarsSlotBusy(c)" type="button" class="btn-ghost btn-sm" :disabled="Boolean(busy)" @click="cancel(c)">
              <AppIcon name="stop" :size="14" />{{ t('avatars.slot.cancel') }}
            </button>
            <button
              v-else
              type="button"
              class="btn-ghost btn-sm ml-auto px-1"
              :title="t('avatars.candidates.remove')"
              :disabled="Boolean(busy)"
              @click="remove(c)"
            >
              <AppIcon name="trash" :size="14" />
            </button>
          </div>
          <AvatarsErrorLine v-if="c.status === 'error'" compact :item="c" :spend-link="avatarsSpendLink('avatar_photo', c.id)" />
        </li>
      </ul>
    </section>
  </div>
</template>

<script setup>
import { studioModelChoices } from '~/utils/studioView.js'
import {
  AVATAR_LIMITS, avatarsCandidatesBlock, avatarsReasonText, avatarsSlotBusy, avatarsSpendLink, avatarsTimeText,
} from '~/utils/avatarsView.js'
import { useAvatarAction, useAvatarEstimate } from '~/composables/useAvatars.js'

const props = defineProps({
  view: { type: Object, required: true },
})
const emit = defineEmits(['tab'])
const { t, te } = useI18n()
const api = useApi()
const { confirm } = useConfirm()
const { busy, act } = useAvatarAction()

const base = computed(() => `/api/avatars/${props.view.id}`)
const hasIdentity = computed(() => Boolean(String(props.view.identity || '').trim()))
const facePhoto = computed(() => props.view.face_photo || (props.view.face ? { id: 0, file: props.view.face, file_id: props.view.face.id, status: 'done' } : null))
const candidates = computed(() => [...(props.view.candidates || [])].reverse()) // the newest first
const anyBusy = computed(() => candidates.value.some(avatarsSlotBusy))
const counts = Array.from({ length: AVATAR_LIMITS.candidatesMax - AVATAR_LIMITS.candidatesMin + 1 }, (_, i) => i + AVATAR_LIMITS.candidatesMin)

// the models: the chat gives its list; on its own the tab asks for one
const chatModels = inject('chatModels', null)
const models = chatModels || useModels()
if (!chatModels) models.load()
const modelChoices = computed(() => studioModelChoices(models.items.value))

const isFace = (c) => Boolean(c.file_id) && c.file_id === props.view.face?.id

// ── the price ──

const block = computed(() => avatarsCandidatesBlock(props.view) || est.value?.error || '')
const { est, usd } = useAvatarEstimate(
  () => props.view.id,
  () => (avatarsCandidatesBlock(props.view) ? null : { action: 'candidates' }),
  () => [props.view.updated_at, props.view.candidate_count, props.view.image_model_id],
)
const timeText = computed(() => avatarsTimeText(est.value?.time, t))

// ── actions ──

async function setCount(n) {
  if (n === props.view.candidate_count) return
  await act('count', () => api.patch(base.value, { candidate_count: n }))
}

async function setModel(id) {
  await act('model', () => api.patch(base.value, { image_model_id: id || null }))
}

async function draw() {
  await act('draw', () => api.post(`${base.value}/candidates`, {}))
}

async function pick(c) {
  const msg = props.view.face ? t('avatars.candidates.replaceAsk') : t('avatars.candidates.pickAsk')
  if (!await confirm({ message: msg, confirmLabel: t('avatars.candidates.pick') })) return
  await act(`pick:${c.id}`, () => api.post(`${base.value}/face`, { photo_id: c.id }))
}

async function cancel(c) {
  await act(`cancel:${c.id}`, () => api.post(`/api/avatars/photos/${c.id}/cancel`))
}

async function stopAll() {
  if (!await confirm({ message: t('avatars.pack.stopAsk'), confirmLabel: t('avatars.pack.stop'), tone: 'danger' })) return
  await act('stop', () => api.post(`${base.value}/cancel`))
}

async function remove(c) {
  if (!await confirm({ message: t('avatars.candidates.removeAsk'), confirmLabel: t('avatars.candidates.remove'), tone: 'danger' })) return
  await act(`remove:${c.id}`, () => api.del(`/api/avatars/photos/${c.id}`))
}
</script>
