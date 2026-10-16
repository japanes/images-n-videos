<template>
  <!--
    A batch of shots in the avatar chat (module 09, kind 'avatar.pack'): the
    whole pack, «draw the rest», chosen shots drawn again, one shot drawn again
    or fixed. Two pictures are drawn at once; each shot shows as it comes. A
    click on a shot opens it (the same dialog as in the grid).
  -->
  <div class="flex justify-start">
    <div class="w-full max-w-3xl space-y-3 rounded-card border border-slate-200 bg-white px-4 py-3 text-sm dark:border-slate-700 dark:bg-slate-900">
      <header class="flex items-start gap-2">
        <AppIcon :name="data.mode === 'fix' ? 'wand' : 'image'" class="mt-0.5 text-primary" />
        <div class="min-w-0 flex-1">
          <p class="font-semibold">{{ title }}</p>
          <p v-if="data.fix" class="break-words text-xs">«{{ data.fix }}»</p>
          <p class="text-xs muted">{{ t('avatars.batch.progress', { done: p.done, total: p.total || ids.length }) }}</p>
        </div>
        <button v-if="p.busy" type="button" class="btn-ghost btn-sm shrink-0 px-1.5" :disabled="Boolean(busy)" @click="stop">
          <AppIcon name="stop" :size="14" />{{ t('avatars.pack.stop') }}
        </button>
      </header>

      <div v-if="p.total > 1" class="h-1.5 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
        <div class="h-full bg-primary transition-all" :style="{ width: `${Math.round((p.done / p.total) * 100)}%` }" />
      </div>

      <AvatarsErrorLine v-if="message.status === 'error' && !photos.length" :item="message" :spend-link="spendLink" />

      <ul v-if="photos.length" class="grid gap-2" :class="photos.length > 4 ? 'grid-cols-4 sm:grid-cols-6' : 'grid-cols-2 sm:grid-cols-4'">
        <li v-for="s in photos" :key="s.id">
          <button
            type="button"
            class="block w-full rounded-card text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-primary"
            @click="openId = s.id"
          >
            <AvatarTile :photo="s" :title="avatarsShotTitle(s.shot_code, t, te, s.title)" show-number :small="photos.length > 4" />
          </button>
        </li>
      </ul>
      <p v-if="p.failed" class="text-xs text-rose-700 dark:text-rose-300">
        {{ t('avatars.pack.failed', { n: p.failed }, p.failed) }} {{ t('avatars.batch.failedHint') }}
      </p>
      <p v-if="skippedText" class="text-xs muted">{{ skippedText }}</p>

      <footer class="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-slate-100 pt-2 text-xs muted dark:border-slate-800">
        <span v-if="modelId">{{ modelTitle(modelId) }}</span>
        <span v-if="message.cost_usd > 0">{{ formatUsd(message.cost_usd) }}</span>
        <NuxtLink v-if="message.cost_usd > 0 || p.failed" :to="spendLink" class="underline hover:text-primary">
          {{ t('avatars.card.spendLink') }}
        </NuxtLink>
        <time class="ml-auto" :datetime="message.created_at">{{ chatTime(message.created_at, locale) }}</time>
      </footer>
    </div>
    <AvatarSlotDialog v-if="openId && view" :view="view" :photo-id="openId" @open="openId = $event" @close="openId = null" />
  </div>
</template>

<script setup>
import { formatUsd } from '~/utils/format.js'
import { chatTime } from '~/utils/chatView.js'
import {
  avatarsBatchPhotos, avatarsBatchProgress, avatarsReasonText, avatarsShotTitle, avatarsSlotBusy, avatarsSpendLink,
} from '~/utils/avatarsView.js'
import { avatarReload, useAvatar, useAvatarAction } from '~/composables/useAvatars.js'

const props = defineProps({
  message: { type: Object, required: true },
  room: { type: Object, required: true },
})
const { t, te, locale } = useI18n()
const api = useApi()
const { confirm } = useConfirm()
const chatModelTitle = inject('chatModelTitle', null)
const modelTitle = (id) => (chatModelTitle ? chatModelTitle(id) : id) || id

const data = computed(() => props.message.data || {})
const { view } = useAvatar(() => data.value.avatar_id)
const { busy, act } = useAvatarAction()
const openId = ref(null)

const ids = computed(() => data.value.photo_ids || [])
const photos = computed(() => avatarsBatchPhotos(view.value, ids.value))
const p = computed(() => avatarsBatchProgress(photos.value))
const spendLink = computed(() => props.message.spend_link || avatarsSpendLink('chat_message', props.message.id))
const modelId = computed(() => data.value.model_id || photos.value.find((s) => s.meta?.model_id)?.meta.model_id || '')

const title = computed(() => {
  const n = ids.value.length
  const mode = data.value.mode
  if (mode === 'fix' || mode === 'redraw') {
    const shot = photos.value[0]
    const name = shot ? avatarsShotTitle(shot.shot_code, t, te, shot.title) : ''
    return t(`avatars.batch.${mode}Title`, { title: name })
  }
  if (mode === 'finish') return t('avatars.batch.finishTitle', { n }, n)
  return t('avatars.batch.packTitle', { n }, n)
})

const skippedText = computed(() => {
  const skipped = data.value.skipped || []
  if (!skipped.length) return ''
  const reasons = [...new Set(skipped.map((s) => avatarsReasonText(s.reason, t, te)).filter(Boolean))]
  return [t('avatars.pack.skipped', { n: skipped.length }, skipped.length), ...reasons].join(' ')
})

// stop the pictures of this batch only
async function stop() {
  if (!await confirm({ message: t('avatars.batch.stopAsk'), confirmLabel: t('avatars.pack.stop'), tone: 'danger' })) return
  await act('stop', async () => {
    for (const s of photos.value.filter(avatarsSlotBusy)) await api.post(`/api/avatars/photos/${s.id}/cancel`)
    avatarReload(data.value.avatar_id, 0)
    return null
  })
}
</script>
