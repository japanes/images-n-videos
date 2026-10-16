<template>
  <!--
    The card of an avatar (module 09, kind 'avatar.card'): the first message of
    the avatar's chat. Three steps as tabs — the person (photos and the written
    description), the face (candidates to pick from), the 36 shots — and the
    full-screen grid of the shots, which closes back to this chat.
    `message.data.avatar_id` points to the avatar; its view is shared with the
    batch messages of the same chat (useAvatar).
  -->
  <div class="flex justify-start">
    <div class="w-full max-w-3xl space-y-3 rounded-card border border-slate-200 bg-white px-4 py-3 text-sm dark:border-slate-700 dark:bg-slate-900">
      <template v-if="!view">
        <AvatarsErrorLine v-if="error" :item="{ error_code: error.code, error: error.message }" />
        <div v-else class="flex items-center gap-2 muted"><Spinner :size="14" />{{ t('common.loading') }}</div>
      </template>

      <template v-else>
        <header class="flex items-start gap-3">
          <img
            v-if="view.face"
            :src="chatFileThumb(view.face)"
            alt=""
            class="h-16 w-12 shrink-0 rounded-button bg-slate-100 object-cover dark:bg-slate-800"
          >
          <span v-else class="grid h-16 w-12 shrink-0 place-items-center rounded-button bg-slate-100 muted dark:bg-slate-800">
            <AppIcon name="user" />
          </span>
          <div class="min-w-0 flex-1 space-y-1">
            <form v-if="renaming" class="flex flex-wrap items-center gap-2" @submit.prevent="saveName">
              <input
                ref="nameInput"
                v-model="nameDraft"
                class="input min-w-0 flex-1"
                :maxlength="AVATAR_LIMITS.name"
                :aria-label="t('avatars.modal.name')"
                @keydown.esc="renaming = false"
              >
              <button type="submit" class="btn-primary btn-sm" :disabled="!nameDraft.trim() || Boolean(busy)">{{ t('common.save') }}</button>
              <button type="button" class="btn-ghost btn-sm" @click="renaming = false">{{ t('common.cancel') }}</button>
            </form>
            <div v-else class="flex min-w-0 items-center gap-1">
              <p class="truncate font-semibold">{{ view.name }}</p>
              <button type="button" class="btn-ghost btn-sm px-1" :title="t('avatars.card.rename')" @click="startRename">
                <AppIcon name="edit" :size="14" />
              </button>
            </div>
            <div class="flex flex-wrap items-center gap-1.5 text-xs">
              <span class="badge" :class="stateClass">{{ t(`avatars.states.${view.state}`) }}</span>
              <span class="muted">{{ t('avatars.card.count', { done: view.counts?.done || 0, total: view.counts?.total || AVATAR_SHOT_COUNT }) }}</span>
              <span v-if="view.archived_at" class="badge bg-slate-200/70 dark:bg-slate-700">{{ t('avatars.card.archived') }}</span>
              <span v-if="view.busy || view.describing" class="inline-flex items-center gap-1 muted"><Spinner :size="10" />{{ t('avatars.card.working') }}</span>
            </div>
          </div>
          <button
            v-if="view.archived_at"
            type="button"
            class="btn-secondary btn-sm shrink-0"
            :disabled="Boolean(busy)"
            @click="archive(false)"
          >
            {{ t('avatars.card.restore') }}
          </button>
          <button
            v-else
            type="button"
            class="btn-ghost btn-sm shrink-0 px-1.5"
            :title="t('avatars.card.archive')"
            :disabled="Boolean(busy)"
            @click="archive(true)"
          >
            <AppIcon name="archive" :size="16" />
          </button>
        </header>
        <p v-if="view.archived_at" class="text-xs muted">{{ t('avatars.card.archivedText') }}</p>

        <nav class="flex gap-1 overflow-x-auto border-b border-slate-200 dark:border-slate-700" role="tablist">
          <button
            v-for="(tb, i) in AVATAR_TABS"
            :key="tb"
            type="button"
            role="tab"
            :aria-selected="current === tb"
            class="-mb-px flex shrink-0 items-center gap-1 border-b-2 px-3 py-2"
            :class="current === tb ? 'border-primary font-medium text-primary' : 'border-transparent muted'"
            @click="tab = tb"
          >
            {{ t('avatars.tabs.step', { n: i + 1, name: t(`avatars.tabs.${tb}`) }) }}
            <AppIcon v-if="stepDone(tb)" name="check" :size="12" class="text-emerald-600 dark:text-emerald-400" />
          </button>
        </nav>

        <AvatarPersonTab v-if="current === 'person'" :view="view" @tab="tab = $event" />
        <AvatarFaceTab v-else-if="current === 'face'" :view="view" @tab="tab = $event" />
        <AvatarShotsTab v-else :view="view" @tab="tab = $event" @grid="gridOpen = true" />

        <footer class="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-slate-100 pt-2 text-xs muted dark:border-slate-800">
          <span>{{ t('avatars.card.spent', { usd: formatUsd(view.cost_usd || 0) }) }}</span>
          <NuxtLink v-if="view.cost_usd > 0" :to="avatarsSpendLink('avatar', view.id)" class="underline hover:text-primary">
            {{ t('avatars.card.spendLink') }}
          </NuxtLink>
          <time class="ml-auto" :datetime="message.created_at">{{ chatTime(message.created_at, locale) }}</time>
        </footer>
      </template>
    </div>
    <AvatarGrid v-if="gridOpen && view" :view="view" @close="gridOpen = false" />
  </div>
</template>

<script setup>
import { formatUsd } from '~/utils/format.js'
import { chatFileThumb, chatTime } from '~/utils/chatView.js'
import {
  AVATAR_LIMITS, AVATAR_SHOT_COUNT, AVATAR_TABS, avatarsDefaultTab, avatarsSpendLink,
} from '~/utils/avatarsView.js'
import { useAvatar, useAvatarAction } from '~/composables/useAvatars.js'

const props = defineProps({
  message: { type: Object, required: true },
  room: { type: Object, required: true },
})
const { t, locale } = useI18n()
const api = useApi()
const { confirm } = useConfirm()

const { view, error } = useAvatar(() => props.message.data?.avatar_id)
const { busy, act } = useAvatarAction()

// the card opens on the step the avatar is at; a click on a tab keeps it there
const tab = ref(null)
const current = computed(() => tab.value || avatarsDefaultTab(view.value))
const gridOpen = ref(false)

function stepDone(step) {
  const v = view.value
  if (!v) return false
  if (step === 'person') return Boolean(String(v.identity || '').trim())
  if (step === 'face') return Boolean(v.face)
  return v.state === 'ready'
}

const stateClass = computed(() => {
  const s = view.value?.state
  if (s === 'ready') return 'bg-emerald-100 text-emerald-900 dark:bg-emerald-500/15 dark:text-emerald-100'
  if (s === 'no_identity' || s === 'no_face') return 'bg-amber-100 text-amber-900 dark:bg-amber-500/15 dark:text-amber-100'
  return 'bg-slate-200/70 dark:bg-slate-700'
})

// ── the name ──

const renaming = ref(false)
const nameDraft = ref('')
const nameInput = ref(null)

async function startRename() {
  nameDraft.value = view.value?.name || ''
  renaming.value = true
  await nextTick()
  nameInput.value?.focus()
}

async function saveName() {
  const name = nameDraft.value.trim()
  if (!name) return
  const res = await act('name', () => api.patch(`/api/avatars/${view.value.id}`, { name }))
  if (res) renaming.value = false
}

// ── the archive ──

async function archive(on) {
  if (on && !await confirm({ message: t('avatars.card.archiveAsk', { name: view.value.name }), confirmLabel: t('avatars.card.archive') })) return
  await act('archive', () => api.post(`/api/avatars/${view.value.id}/archive`, { archived: on }))
}
</script>
