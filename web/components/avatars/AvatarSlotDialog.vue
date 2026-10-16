<template>
  <!--
    One shot of the pack, opened from the grid: the picture big, side by side
    with the face, a photo of the person or an earlier version; its wording;
    draw it again, fix it with one phrase, put an own photo in it, take the
    picture out (the place stays). Shot 1 is the face: it is only looked at here
    and changed on the «Face» step.
  -->
  <ModalShell open size="xl" body-class="p-4 sm:p-5" @close="emit('close')">
    <template #header>
      <div class="flex min-w-0 flex-1 items-center gap-2">
        <button type="button" class="btn-ghost p-1.5" :disabled="!prevId" :aria-label="t('avatars.slot.prev')" @click="emit('open', prevId)">
          <AppIcon name="chevron-left" />
        </button>
        <h2 class="min-w-0 flex-1 truncate text-base font-semibold">
          {{ slot ? t('avatars.slot.title', { n: avatarsShotNumber(slot.shot_code), title: shotTitle }) : '' }}
        </h2>
        <button type="button" class="btn-ghost p-1.5" :disabled="!nextId" :aria-label="t('avatars.slot.next')" @click="emit('open', nextId)">
          <AppIcon name="chevron-right" />
        </button>
      </div>
    </template>

    <p v-if="!slot" class="muted">{{ t('avatars.slot.gone') }}</p>

    <div v-else class="grid gap-5 md:grid-cols-[minmax(0,1fr)_minmax(0,22rem)]">
      <!-- the picture, and what it is put side by side with -->
      <div class="space-y-3">
        <div class="grid gap-3" :class="compareWith ? 'grid-cols-2' : 'grid-cols-1'">
          <figure class="space-y-1">
            <a v-if="slot.file" :href="slot.file.url" target="_blank" rel="noopener" class="block">
              <AvatarTile :photo="slot" />
            </a>
            <AvatarTile v-else :photo="slot" />
            <figcaption v-if="compareWith" class="text-xs muted">{{ t('avatars.compare.this') }}</figcaption>
          </figure>
          <figure v-if="compareWith" class="space-y-1">
            <a :href="`/files/${compareWith.file_id}`" target="_blank" rel="noopener" class="block overflow-hidden rounded-card border border-slate-200 bg-slate-100 dark:border-slate-700 dark:bg-slate-800" :style="{ aspectRatio: '3 / 4' }">
              <img :src="avatarsThumb(compareWith.file_id, 960)" alt="" class="h-full w-full object-cover">
            </a>
            <figcaption class="text-xs muted">{{ choiceLabel(compareWith) }}</figcaption>
          </figure>
        </div>
        <label v-if="choices.length" class="flex flex-wrap items-center gap-2 text-xs">
          <span class="muted">{{ t('avatars.compare.title') }}</span>
          <select v-model="compareKey" class="input w-auto py-1 text-xs">
            <option value="">{{ t('avatars.compare.none') }}</option>
            <option v-for="ch in choices" :key="ch.key" :value="ch.key">{{ choiceLabel(ch) }}</option>
          </select>
        </label>
      </div>

      <!-- what can be done with it -->
      <div class="space-y-4 text-sm">
        <div class="flex flex-wrap items-center gap-1.5 text-xs">
          <span class="badge bg-slate-200/70 dark:bg-slate-700">{{ categoryTitle }}</span>
          <span v-if="slot.origin === 'upload' && slot.file_id" class="badge bg-slate-200/70 dark:bg-slate-700">{{ t('avatars.tile.own') }}</span>
          <span v-if="slot.marked" class="badge bg-emerald-100 text-emerald-900 dark:bg-emerald-500/15 dark:text-emerald-100">{{ t('avatars.tile.marked') }}</span>
          <span v-if="isBusy" class="inline-flex items-center gap-1 muted"><Spinner :size="10" />{{ slot.status === 'queued' ? t('avatars.tile.queued') : t('avatars.tile.drawing') }}</span>
        </div>

        <AvatarsErrorLine v-if="slot.status === 'error'" :item="slot" :spend-link="avatarsSpendLink('avatar_photo', slot.id)" />

        <p v-if="isFace" class="rounded-card bg-slate-100 p-3 text-xs dark:bg-slate-800">{{ t('avatars.slot.faceText') }}</p>

        <template v-else>
          <div v-if="isBusy" class="flex flex-wrap items-center gap-2">
            <button type="button" class="btn-secondary btn-sm" :disabled="Boolean(busy)" @click="cancel">
              <AppIcon name="stop" :size="14" />{{ t('avatars.slot.cancel') }}
            </button>
            <span class="text-xs muted">{{ t('avatars.slot.busyText') }}</span>
          </div>

          <!-- the wording -->
          <section class="space-y-1.5">
            <div class="flex items-center gap-2">
              <span class="label min-w-0 flex-1">{{ t('avatars.slot.prompt') }}</span>
              <button v-if="!editingPrompt" type="button" class="btn-ghost btn-sm" :disabled="isBusy" @click="startPrompt">
                <AppIcon name="edit" :size="14" />{{ slot.custom_prompt ? t('avatars.slot.promptEdit') : t('avatars.slot.promptOwn') }}
              </button>
            </div>
            <template v-if="editingPrompt">
              <textarea v-model="promptDraft" rows="6" class="input text-xs" :maxlength="AVATAR_LIMITS.prompt" />
              <div class="flex flex-wrap items-center gap-2">
                <button type="button" class="btn-primary btn-sm" :disabled="Boolean(busy)" @click="savePrompt">{{ t('common.save') }}</button>
                <button type="button" class="btn-ghost btn-sm" @click="editingPrompt = false">{{ t('common.cancel') }}</button>
                <span class="ml-auto text-xs muted">{{ promptDraft.length }}/{{ AVATAR_LIMITS.prompt }}</span>
              </div>
              <p class="text-xs muted">{{ t('avatars.slot.promptHint') }}</p>
            </template>
            <template v-else>
              <p class="max-h-32 overflow-y-auto whitespace-pre-line rounded-card bg-slate-50 p-2 text-xs dark:bg-slate-800/60">{{ slot.custom_prompt || slot.catalog_prompt }}</p>
              <div v-if="slot.custom_prompt" class="flex flex-wrap items-center gap-2 text-xs">
                <span class="muted">{{ t('avatars.slot.promptIsOwn') }}</span>
                <button type="button" class="underline" :disabled="Boolean(busy)" @click="resetPrompt">{{ t('avatars.slot.promptReset') }}</button>
              </div>
            </template>
          </section>

          <!-- draw again -->
          <section class="space-y-1.5">
            <PriceButton
              icon="refresh"
              :label="slot.file_id ? t('avatars.slot.redraw') : t('avatars.slot.draw')"
              :usd="redrawEst.usd.value"
              :disabled="isBusy || !view.face || redrawEst.usd.value === null || Boolean(busy)"
              :busy="busy === 'redraw'"
              @click="redraw"
            />
            <p v-if="!view.face" class="text-xs text-amber-700 dark:text-amber-300">{{ avatarsReasonText('avatar_no_face', t, te) }}</p>
            <p v-else-if="redrawError" class="text-xs text-amber-700 dark:text-amber-300">{{ avatarsReasonText(redrawError, t, te) }}</p>
            <p v-else-if="slot.file_id" class="text-xs muted">{{ t('avatars.slot.redrawText') }}</p>
          </section>

          <!-- fix with one phrase -->
          <section v-if="slot.file_id" class="space-y-1.5">
            <label class="label" :for="`fix-${slot.id}`">{{ t('avatars.slot.fix') }}</label>
            <textarea
              :id="`fix-${slot.id}`"
              v-model="fixText"
              rows="2"
              class="input"
              :maxlength="AVATAR_LIMITS.fix"
              :placeholder="t('avatars.slot.fixPlaceholder')"
              :disabled="isBusy"
            />
            <PriceButton
              icon="wand"
              :label="t('avatars.slot.fixDo')"
              :usd="fixText.trim() ? fixEst.usd.value : null"
              :disabled="isBusy || !fixText.trim() || fixEst.usd.value === null || Boolean(busy)"
              :busy="busy === 'fix'"
              variant="secondary"
              @click="fix"
            />
            <p class="text-xs muted">{{ t('avatars.slot.fixText') }}</p>
          </section>

          <!-- own photo, mark, take out -->
          <section class="space-y-2 border-t border-slate-100 pt-3 dark:border-slate-800">
            <div class="flex flex-wrap items-center gap-2">
              <label class="btn-secondary btn-sm cursor-pointer" :class="(isBusy || busy) && 'pointer-events-none opacity-50'">
                <AppIcon name="upload" :size="14" />{{ t('avatars.slot.upload') }}
                <input type="file" accept="image/*" class="sr-only" :disabled="isBusy || Boolean(busy)" @change="upload">
              </label>
              <button v-if="slot.file_id" type="button" class="btn-ghost btn-sm" :disabled="isBusy || Boolean(busy)" @click="removePicture">
                <AppIcon name="trash" :size="14" />{{ t('avatars.slot.remove') }}
              </button>
            </div>
            <ToggleSwitch
              v-if="slot.file_id"
              :model-value="Boolean(slot.marked)"
              :label="t('avatars.slot.mark')"
              :disabled="Boolean(busy)"
              @update:model-value="setMarked"
            />
            <p v-if="slot.file_id" class="text-xs muted">{{ t('avatars.slot.markText', { max: AVATAR_LIMITS.subjectPhotos }) }}</p>
          </section>
        </template>

        <!-- what it cost, what was sent -->
        <footer class="space-y-1 border-t border-slate-100 pt-3 text-xs muted dark:border-slate-800">
          <p v-if="slot.meta?.model_id">{{ t('avatars.slot.model', { model: modelTitle(slot.meta.model_id) }) }}</p>
          <p v-if="slot.meta?.fix">{{ t('avatars.slot.lastFix', { text: slot.meta.fix }) }}</p>
          <p v-if="slot.cost_usd > 0">
            {{ t('avatars.slot.spent', { usd: formatUsd(slot.cost_usd) }) }}
            <NuxtLink :to="avatarsSpendLink('avatar_photo', slot.id)" class="ml-1 underline hover:text-primary">{{ t('avatars.card.spendLink') }}</NuxtLink>
          </p>
        </footer>
      </div>
    </div>
  </ModalShell>
</template>

<script setup>
import { formatUsd } from '~/utils/format.js'
import {
  AVATAR_FACE_CODE, AVATAR_LIMITS, avatarsCategory, avatarsCompareChoices, avatarsReasonText, avatarsShotNumber,
  avatarsShotTitle, avatarsShrinkPhoto, avatarsSlotBusy, avatarsSpendLink, avatarsThumb,
} from '~/utils/avatarsView.js'
import { avatarReload, useAvatarAction, useAvatarEstimate } from '~/composables/useAvatars.js'

const props = defineProps({
  view: { type: Object, required: true },
  photoId: { type: Number, required: true },
})
const emit = defineEmits(['open', 'close'])
const { t, te } = useI18n()
const api = useApi()
const { confirm } = useConfirm()
const { busy, act } = useAvatarAction()
const chatModelTitle = inject('chatModelTitle', null)

const slots = computed(() => props.view.slots || [])
const index = computed(() => slots.value.findIndex((s) => s.id === props.photoId))
const slot = computed(() => slots.value[index.value] || null)
const prevId = computed(() => (index.value > 0 ? slots.value[index.value - 1].id : null))
const nextId = computed(() => (index.value >= 0 && index.value < slots.value.length - 1 ? slots.value[index.value + 1].id : null))

const isFace = computed(() => slot.value?.shot_code === AVATAR_FACE_CODE)
const isBusy = computed(() => avatarsSlotBusy(slot.value))
const shotTitle = computed(() => avatarsShotTitle(slot.value?.shot_code, t, te, slot.value?.title))
const categoryTitle = computed(() => {
  const cat = avatarsCategory(slot.value?.category)
  return cat && te(`avatars.categories.${cat}`) ? t(`avatars.categories.${cat}`) : cat
})
const modelTitle = (id) => (chatModelTitle ? chatModelTitle(id) : id) || id

// ── side by side ──

const choices = computed(() => avatarsCompareChoices(slot.value, props.view))
const compareKey = ref('')
const compareWith = computed(() => choices.value.find((ch) => ch.key === compareKey.value) || null)
function choiceLabel(ch) {
  if (ch.kind === 'face') return t('avatars.compare.face')
  if (ch.kind === 'photo') return t('avatars.compare.photo', { n: ch.n })
  return t('avatars.compare.previous', { n: ch.n })
}

// another shot opened: start clean
watch(() => props.photoId, () => {
  compareKey.value = ''
  editingPrompt.value = false
  fixText.value = ''
})

// ── the wording ──

const editingPrompt = ref(false)
const promptDraft = ref('')

function startPrompt() {
  promptDraft.value = slot.value.custom_prompt || slot.value.catalog_prompt || ''
  editingPrompt.value = true
}

async function savePrompt() {
  const text = promptDraft.value.trim()
  // the catalog wording typed back unchanged is not an own wording
  const value = text && text !== String(slot.value.catalog_prompt || '').trim() ? text : null
  const res = await act('prompt', () => api.patch(`/api/avatars/photos/${slot.value.id}`, { custom_prompt: value }))
  if (res) {
    editingPrompt.value = false
    avatarReloadSoon()
  }
}

async function resetPrompt() {
  if (!await confirm({ message: t('avatars.slot.promptResetAsk'), confirmLabel: t('avatars.slot.promptReset') })) return
  const res = await act('prompt', () => api.patch(`/api/avatars/photos/${slot.value.id}`, { custom_prompt: null }))
  if (res) avatarReloadSoon()
}

// ── draw again, fix ──

const deps = () => [props.view.updated_at, props.view.image_model_id, slot.value?.status, slot.value?.custom_prompt]
const redrawEst = useAvatarEstimate(
  () => props.view.id,
  () => (slot.value && !isFace.value && !isBusy.value && props.view.face ? { action: 'redraw', photo_id: slot.value.id } : null),
  deps,
)
const redrawError = computed(() => redrawEst.est.value?.items?.[0]?.error || '')

const fixText = ref('')
const fixEst = useAvatarEstimate(
  () => props.view.id,
  () => (slot.value?.file_id && !isFace.value && !isBusy.value && fixText.value.trim()
    ? { action: 'fix', photo_id: slot.value.id, text: fixText.value.trim() }
    : null),
  () => [...deps(), slot.value?.file_id],
)

async function redraw() {
  await act('redraw', () => api.post(`/api/avatars/photos/${slot.value.id}/redraw`))
}

async function fix() {
  const res = await act('fix', () => api.post(`/api/avatars/photos/${slot.value.id}/fix`, { text: fixText.value.trim() }))
  if (res) fixText.value = ''
}

async function cancel() {
  const res = await act('cancel', () => api.post(`/api/avatars/photos/${slot.value.id}/cancel`))
  if (res) avatarReloadSoon()
}

// ── own photo, mark, take out ──

async function upload(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  const res = await act('upload', async () => api.upload(`/api/avatars/photos/${slot.value.id}/upload`, await avatarsShrinkPhoto(file)))
  if (res) avatarReloadSoon()
}

async function setMarked(on) {
  const res = await act('mark', () => api.patch(`/api/avatars/photos/${slot.value.id}`, { marked: Boolean(on) }))
  if (res) avatarReloadSoon()
}

async function removePicture() {
  if (!await confirm({ message: t('avatars.slot.removeAsk'), confirmLabel: t('avatars.slot.remove'), tone: 'danger' })) return
  await act('remove', () => api.del(`/api/avatars/photos/${slot.value.id}`))
}

// the actions on one picture answer with the picture, not the avatar: read the avatar again
function avatarReloadSoon() {
  avatarReload(props.view.id, 0)
}
</script>
