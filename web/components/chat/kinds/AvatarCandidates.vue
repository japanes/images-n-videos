<template>
  <!--
    A batch of face candidates in the avatar chat (module 09, kind
    'avatar.candidates'): the faces Google draws from the description, one of
    them is picked as the face of the avatar. The pictures are the avatar's
    (useAvatar), so a face picked or removed on the card shows here too.
  -->
  <div class="flex justify-start">
    <div class="w-full max-w-3xl space-y-3 rounded-card border border-slate-200 bg-white px-4 py-3 text-sm dark:border-slate-700 dark:bg-slate-900">
      <header class="flex items-start gap-2">
        <AppIcon name="user" class="mt-0.5 text-primary" />
        <div class="min-w-0 flex-1">
          <p class="font-semibold">{{ t('avatars.batch.candidatesTitle', { n: count }, count) }}</p>
          <p class="text-xs muted">{{ progressText }}</p>
        </div>
        <button v-if="p.busy" type="button" class="btn-ghost btn-sm shrink-0 px-1.5" :disabled="Boolean(busy)" @click="stop">
          <AppIcon name="stop" :size="14" />{{ t('avatars.pack.stop') }}
        </button>
      </header>

      <AvatarsErrorLine v-if="message.status === 'error' && !photos.length" :item="message" :spend-link="spendLink" />

      <ul v-if="photos.length" class="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <li v-for="c in photos" :key="c.id" class="space-y-1.5">
          <a v-if="c.file" :href="c.file.url" target="_blank" rel="noopener" class="block">
            <AvatarTile :photo="c" />
          </a>
          <AvatarTile v-else :photo="c" />
          <div class="flex flex-wrap items-center gap-1">
            <span v-if="isFace(c)" class="badge bg-emerald-100 text-emerald-900 dark:bg-emerald-500/15 dark:text-emerald-100">{{ t('avatars.candidates.isFace') }}</span>
            <span v-else-if="c.meta?.picked" class="badge bg-slate-200/70 dark:bg-slate-700">{{ t('avatars.candidates.wasFace') }}</span>
            <button
              v-if="c.file_id && !isFace(c) && !avatarsSlotBusy(c) && !view?.archived_at"
              type="button"
              class="btn-primary btn-sm"
              :disabled="Boolean(busy)"
              @click="pick(c)"
            >
              {{ t('avatars.candidates.pick') }}
            </button>
          </div>
          <AvatarsErrorLine v-if="c.status === 'error'" compact :item="c" :spend-link="avatarsSpendLink('avatar_photo', c.id)" />
        </li>
      </ul>
      <p v-else-if="view && message.status !== 'error'" class="text-xs muted">{{ t('avatars.batch.gone') }}</p>

      <footer class="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-slate-100 pt-2 text-xs muted dark:border-slate-800">
        <span v-if="data.model_id">{{ modelTitle(data.model_id) }}</span>
        <span v-if="data.photo_ids?.length && data.mode === 'reference'">{{ t('avatars.batch.withPhotos') }}</span>
        <span v-if="message.cost_usd > 0">{{ formatUsd(message.cost_usd) }}</span>
        <NuxtLink v-if="message.cost_usd > 0 || p.failed" :to="spendLink" class="underline hover:text-primary">
          {{ t('avatars.card.spendLink') }}
        </NuxtLink>
        <time class="ml-auto" :datetime="message.created_at">{{ chatTime(message.created_at, locale) }}</time>
      </footer>
    </div>
  </div>
</template>

<script setup>
import { formatUsd } from '~/utils/format.js'
import { chatTime } from '~/utils/chatView.js'
import {
  avatarsBatchPhotos, avatarsBatchProgress, avatarsSlotBusy, avatarsSpendLink,
} from '~/utils/avatarsView.js'
import { avatarReload, useAvatar, useAvatarAction } from '~/composables/useAvatars.js'

const props = defineProps({
  message: { type: Object, required: true },
  room: { type: Object, required: true },
})
const { t, locale } = useI18n()
const api = useApi()
const { confirm } = useConfirm()
const chatModelTitle = inject('chatModelTitle', null)
const modelTitle = (id) => (chatModelTitle ? chatModelTitle(id) : id) || id

const data = computed(() => props.message.data || {})
const { view } = useAvatar(() => data.value.avatar_id)
const { busy, act } = useAvatarAction()

// the batch lists its candidates by id; they are found among the avatar's pictures
const photos = computed(() => avatarsBatchPhotos(view.value, data.value.photo_ids))
const count = computed(() => data.value.count || (data.value.photo_ids || []).length)
const p = computed(() => avatarsBatchProgress(photos.value))
const spendLink = computed(() => props.message.spend_link || avatarsSpendLink('chat_message', props.message.id))
const progressText = computed(() => t('avatars.batch.progress', { done: p.value.done, total: p.value.total || count.value }))

const isFace = (c) => Boolean(c.file_id) && c.file_id === view.value?.face?.id

async function pick(c) {
  const msg = view.value?.face ? t('avatars.candidates.replaceAsk') : t('avatars.candidates.pickAsk')
  if (!await confirm({ message: msg, confirmLabel: t('avatars.candidates.pick') })) return
  await act(`pick:${c.id}`, () => api.post(`/api/avatars/${data.value.avatar_id}/face`, { photo_id: c.id }))
}

// stop the pictures of this batch only
async function stop() {
  if (!await confirm({ message: t('avatars.batch.stopAsk'), confirmLabel: t('avatars.pack.stop'), tone: 'danger' })) return
  await act('stop', async () => {
    for (const c of photos.value.filter(avatarsSlotBusy)) await api.post(`/api/avatars/photos/${c.id}/cancel`)
    avatarReload(data.value.avatar_id, 0)
    return null
  })
}
</script>
