<template>
  <!--
    Step 1 of the avatar card: who the person is. The way the person is made
    (from photos, from a written brief, or invented), the photos of the person,
    and the written description (the identity) that every picture is drawn
    from. «Describe» asks Google to write it (paid); it can also be typed or
    corrected by hand, and locked so nothing changes it by accident.
  -->
  <div class="space-y-4">
    <!-- how the person is made -->
    <section class="space-y-2">
      <label class="block space-y-1">
        <span class="label">{{ t('avatars.modes.label') }}</span>
        <select class="input" :value="view.init_mode" :disabled="Boolean(busy) || view.describing" @change="saveMode($event.target.value)">
          <option v-for="m in AVATAR_MODES" :key="m" :value="m">{{ t(`avatars.modes.${m}.name`) }}</option>
        </select>
      </label>
      <p class="text-xs muted">{{ t(`avatars.modes.${view.init_mode}.text`) }}</p>
      <label class="block space-y-1">
        <span class="label">{{ t('avatars.person.brief') }}</span>
        <textarea
          v-model="brief"
          class="input"
          rows="3"
          :maxlength="AVATAR_LIMITS.brief"
          :placeholder="t('avatars.person.briefPlaceholder')"
          :disabled="view.describing"
        />
      </label>
      <div class="flex flex-wrap items-center gap-2">
        <p class="min-w-0 flex-1 text-xs muted">
          {{ view.init_mode === 'description' ? t('avatars.person.briefNeeded') : t('avatars.person.briefOptional') }}
        </p>
        <template v-if="briefDirty">
          <button type="button" class="btn-ghost btn-sm" @click="brief = view.brief || ''">{{ t('common.cancel') }}</button>
          <button type="button" class="btn-primary btn-sm" :disabled="Boolean(busy)" @click="saveBrief">
            <Spinner v-if="busy === 'brief'" :size="14" />{{ t('common.save') }}
          </button>
        </template>
      </div>
    </section>

    <!-- photos of the person -->
    <section class="space-y-2">
      <div class="flex flex-wrap items-center gap-2">
        <h4 class="min-w-0 flex-1 font-semibold">{{ t('avatars.photos.title', { n: sources.length, max: AVATAR_LIMITS.photos }) }}</h4>
        <label class="btn-secondary btn-sm cursor-pointer" :class="(!left || Boolean(busy)) && 'pointer-events-none opacity-50'">
          <Spinner v-if="busy === 'upload'" :size="14" /><AppIcon v-else name="upload" :size="14" />{{ t('avatars.photos.upload') }}
          <input type="file" class="sr-only" accept="image/png,image/jpeg,image/webp" multiple :disabled="!left || Boolean(busy)" @change="onFiles">
        </label>
        <button type="button" class="btn-secondary btn-sm" :disabled="!left || Boolean(busy)" @click="pickerOpen = true">
          <AppIcon name="library" :size="14" />{{ t('avatars.photos.library') }}
        </button>
      </div>
      <p class="text-xs muted">{{ view.init_mode === 'reference' ? t('avatars.photos.textReference', { n: AVATAR_LIMITS.describePhotos }) : t('avatars.photos.textOther') }}</p>
      <p class="text-xs muted">{{ t('avatars.photos.marked', { n: AVATAR_LIMITS.subjectPhotos }) }}</p>

      <p v-if="!sources.length" class="rounded-card border border-dashed border-slate-300 px-3 py-6 text-center muted dark:border-slate-600">
        {{ t('avatars.photos.empty') }}
      </p>
      <ul v-else class="grid grid-cols-3 gap-2 sm:grid-cols-4">
        <li v-for="(p, i) in sources" :key="p.id" class="space-y-1">
          <AvatarTile :photo="p" small />
          <input
            class="input px-1.5 py-1 text-xs"
            :value="p.angle"
            :maxlength="AVATAR_LIMITS.angle"
            :placeholder="t('avatars.photos.angle')"
            :aria-label="t('avatars.photos.angle')"
            @change="saveAngle(p, $event.target.value)"
          >
          <div class="flex flex-wrap items-center gap-0.5">
            <button
              type="button"
              class="btn-ghost btn-sm px-1"
              :class="p.marked && 'text-primary'"
              :title="p.marked ? t('avatars.photos.unmark') : t('avatars.photos.mark')"
              :aria-pressed="p.marked"
              :disabled="Boolean(busy)"
              @click="mark(p)"
            >
              <AppIcon name="check" :size="14" />
            </button>
            <button
              type="button"
              class="btn-ghost btn-sm px-1"
              :title="t('avatars.photos.makeFace')"
              :disabled="Boolean(busy) || !hasIdentity || !p.file_id || view.face?.id === p.file_id"
              @click="makeFace(p)"
            >
              <AppIcon name="user" :size="14" />
            </button>
            <button type="button" class="btn-ghost btn-sm px-1" :title="t('avatars.photos.left')" :disabled="Boolean(busy) || i === 0" @click="move(i, -1)">
              <AppIcon name="chevron-left" :size="14" />
            </button>
            <button
              type="button"
              class="btn-ghost btn-sm px-1"
              :title="t('avatars.photos.right')"
              :disabled="Boolean(busy) || i === sources.length - 1"
              @click="move(i, 1)"
            >
              <AppIcon name="chevron-right" :size="14" />
            </button>
            <button type="button" class="btn-ghost btn-sm ml-auto px-1" :title="t('avatars.photos.remove')" :disabled="Boolean(busy)" @click="remove(p)">
              <AppIcon name="trash" :size="14" />
            </button>
          </div>
        </li>
      </ul>
    </section>

    <!-- the written description -->
    <section class="space-y-2">
      <div class="flex flex-wrap items-center gap-2">
        <h4 class="min-w-0 flex-1 font-semibold">{{ t('avatars.identity.title') }}</h4>
        <span v-if="view.identity_locked" class="badge bg-slate-200/70 dark:bg-slate-700">{{ t('avatars.identity.locked') }}</span>
        <span v-else-if="view.identity_source" class="text-xs muted">{{ t(`avatars.identity.source.${view.identity_source}`) }}</span>
      </div>
      <p class="text-xs muted">{{ t('avatars.identity.text') }}</p>

      <div v-if="view.describing" class="flex flex-wrap items-center gap-2 rounded-card bg-slate-50 p-3 dark:bg-slate-800/60">
        <Spinner :size="14" />
        <span class="min-w-0 flex-1">{{ t('avatars.identity.writing') }}</span>
        <button type="button" class="btn-ghost btn-sm" :disabled="Boolean(busy)" @click="stopDescribe">
          <AppIcon name="stop" :size="14" />{{ t('avatars.identity.stop') }}
        </button>
      </div>

      <template v-if="editing">
        <textarea v-model="identityDraft" class="input font-mono text-xs" rows="12" :maxlength="AVATAR_LIMITS.identity" />
        <div class="flex flex-wrap items-center gap-2">
          <span class="min-w-0 flex-1 text-xs" :class="draftProblem && identityDraft.trim() ? 'text-amber-700 dark:text-amber-300' : 'muted'">
            {{ t('avatars.identity.length', { n: identityDraft.trim().length, min: AVATAR_LIMITS.identityMin, max: AVATAR_LIMITS.identity }) }}
            <template v-if="draftProblem === 'short'"> · {{ t('avatars.errors.short', { min: AVATAR_LIMITS.identityMin }) }}</template>
          </span>
          <button type="button" class="btn-ghost btn-sm" @click="editing = false">{{ t('common.cancel') }}</button>
          <button type="button" class="btn-primary btn-sm" :disabled="Boolean(busy) || draftProblem === 'avatar_identity_too_long'" @click="saveIdentity">
            <Spinner v-if="busy === 'identity'" :size="14" />{{ t('common.save') }}
          </button>
        </div>
        <p v-if="draftProblem === 'short' || draftProblem === 'avatar_identity_empty'" class="text-xs muted">{{ t('avatars.identity.shortHint') }}</p>
      </template>
      <template v-else>
        <p v-if="hasIdentity" class="max-h-64 overflow-y-auto whitespace-pre-wrap break-words rounded-card bg-slate-50 p-3 text-xs dark:bg-slate-800/60">{{ view.identity }}</p>
        <p v-else class="muted">{{ t('avatars.identity.empty') }}</p>
        <div class="flex flex-wrap items-center gap-2">
          <PriceButton
            icon="sparkles"
            :label="hasIdentity ? t('avatars.identity.again') : t('avatars.identity.describe')"
            :usd="describeUsd"
            :disabled="Boolean(describeBlock) || describeUsd === null || Boolean(busy)"
            :busy="busy === 'describe'"
            @click="describe"
          />
          <button v-if="!view.identity_locked" type="button" class="btn-secondary btn-sm" :disabled="Boolean(busy) || view.describing" @click="startEdit">
            <AppIcon name="edit" :size="14" />{{ hasIdentity ? t('avatars.identity.edit') : t('avatars.identity.write') }}
          </button>
          <button v-if="hasIdentity && !view.identity_locked" type="button" class="btn-ghost btn-sm" :disabled="Boolean(busy)" @click="lock">
            {{ t('avatars.identity.lock') }}
          </button>
          <button v-if="view.identity_locked" type="button" class="btn-ghost btn-sm" :disabled="Boolean(busy)" @click="unlock">
            {{ t('avatars.identity.unlock') }}
          </button>
        </div>
        <p v-if="describeBlock && !view.describing" class="text-xs text-amber-700 dark:text-amber-300">{{ avatarsReasonText(describeBlock, t, te) }}</p>
        <p v-else-if="describeEst" class="text-xs muted">
          {{ view.init_mode === 'reference' ? t('avatars.identity.sends', { n: describeEst.photos || 0 }, describeEst.photos || 0) : t('avatars.identity.sendsText') }}
        </p>
        <p v-if="view.identity_locked" class="text-xs muted">{{ t('avatars.identity.lockedText') }}</p>
        <button v-if="hasIdentity && !view.face" type="button" class="btn-ghost btn-sm" @click="emit('tab', 'face')">
          {{ t('avatars.identity.next') }}<AppIcon name="chevron-right" :size="14" />
        </button>
      </template>
    </section>

    <StudioSourcePicker
      :open="pickerOpen"
      :title="t('avatars.photos.library')"
      multiple
      :max="Math.max(1, left)"
      @pick="onPick"
      @close="pickerOpen = false"
    />
  </div>
</template>

<script setup>
import {
  AVATAR_LIMITS, AVATAR_MODES, avatarsDescribeBlock, avatarsErrorText, avatarsIdentityCheck, avatarsPhotosLeft, avatarsReasonText,
  avatarsShrinkPhoto,
} from '~/utils/avatarsView.js'
import { avatarReload, useAvatarAction, useAvatarEstimate } from '~/composables/useAvatars.js'

const props = defineProps({
  view: { type: Object, required: true },
})
const emit = defineEmits(['tab'])
const { t, te } = useI18n()
const api = useApi()
const toast = useToast()
const { confirm } = useConfirm()
const { busy, act } = useAvatarAction()

const base = computed(() => `/api/avatars/${props.view.id}`)
const sources = computed(() => props.view.sources || [])
const left = computed(() => avatarsPhotosLeft(props.view))
const hasIdentity = computed(() => Boolean(String(props.view.identity || '').trim()))

// ── the way and the brief ──

const brief = ref(props.view.brief || '')
const briefDirty = computed(() => brief.value !== (props.view.brief || ''))
watch(() => props.view.brief, (next, prev) => {
  // somebody else changed it (another tab, «Describe» with a brief): follow unless typing
  if (brief.value === (prev || '')) brief.value = next || ''
})

async function saveMode(mode) {
  if (mode === props.view.init_mode) return
  await act('mode', () => api.patch(base.value, { mode }))
}

async function saveBrief() {
  await act('brief', () => api.patch(base.value, { brief: brief.value.trim() }))
}

// ── photos ──

const pickerOpen = ref(false)

async function onFiles(e) {
  const list = [...(e.target.files || [])].slice(0, left.value)
  e.target.value = ''
  if (!list.length) return
  await act('upload', async () => {
    for (const file of list) {
      try {
        await api.upload(`${base.value}/photos`, await avatarsShrinkPhoto(file), { angle: '' })
      } catch (err) {
        toast.error(`${file.name}: ${avatarsErrorText(err, t, te)}`)
      }
    }
    avatarReload(props.view.id, 0)
  })
}

async function onPick(files) {
  pickerOpen.value = false
  const ids = (files || []).map((f) => f.id).filter(Boolean).slice(0, left.value)
  if (!ids.length) return
  await act('library', () => api.post(`${base.value}/photos/from-files`, { file_ids: ids }))
}

async function saveAngle(p, value) {
  if (value.trim() === (p.angle || '')) return
  await act(`angle:${p.id}`, () => api.patch(`/api/avatars/photos/${p.id}`, { angle: value.trim() }))
  avatarReload(props.view.id, 0)
}

async function mark(p) {
  await act(`mark:${p.id}`, () => api.patch(`/api/avatars/photos/${p.id}`, { marked: !p.marked }))
  avatarReload(props.view.id, 0)
}

async function makeFace(p) {
  const msg = props.view.face ? t('avatars.candidates.replaceAsk') : t('avatars.candidates.pickAsk')
  if (!await confirm({ message: msg, confirmLabel: t('avatars.photos.makeFace') })) return
  await act(`face:${p.id}`, () => api.post(`${base.value}/face`, { photo_id: p.id }))
}

async function move(i, step) {
  const ids = sources.value.map((p) => p.id)
  const j = i + step
  if (j < 0 || j >= ids.length) return
  ;[ids[i], ids[j]] = [ids[j], ids[i]]
  await act('order', () => api.post(`${base.value}/photos/order`, { ids }))
}

async function remove(p) {
  if (!await confirm({ message: t('avatars.photos.removeAsk'), confirmLabel: t('avatars.photos.remove'), tone: 'danger' })) return
  await act(`remove:${p.id}`, () => api.del(`/api/avatars/photos/${p.id}`))
}

// ── the description ──

const describeBlock = computed(() => avatarsDescribeBlock(props.view))
const { est: describeEst, usd: describeUsd } = useAvatarEstimate(
  () => props.view.id,
  () => (describeBlock.value ? null : { action: 'describe' }),
  () => [props.view.updated_at, props.view.init_mode, sources.value.length],
)

async function describe() {
  const force = hasIdentity.value
  if (force && !await confirm({ message: t('avatars.identity.replaceAsk'), confirmLabel: t('avatars.identity.again') })) return
  await act('describe', () => api.post(`${base.value}/describe`, { force }))
}

async function stopDescribe() {
  await act('stop', () => api.post(`${base.value}/describe/cancel`))
}

const editing = ref(false)
const identityDraft = ref('')
const draftProblem = computed(() => avatarsIdentityCheck(identityDraft.value))

function startEdit() {
  identityDraft.value = props.view.identity || ''
  editing.value = true
}

async function saveIdentity() {
  const res = await act('identity', () => api.put(`${base.value}/identity`, { identity: identityDraft.value }))
  if (res) editing.value = false
}

async function lock() {
  await act('lock', () => api.post(`${base.value}/identity/lock`))
}

async function unlock() {
  if (!await confirm({ message: t('avatars.identity.unlockAsk'), confirmLabel: t('avatars.identity.unlock') })) return
  await act('unlock', () => api.post(`${base.value}/identity/unlock`))
}
</script>
