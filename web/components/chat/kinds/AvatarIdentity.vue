<template>
  <!--
    «Describe» of an avatar in its chat (module 09, kind 'avatar.identity'): Google
    reads the photos of the person (or the brief) and writes the description the
    avatar is drawn from. Running: a spinner and «Stop». Done: the text written,
    what it was written from. When the description was locked meanwhile, the
    text is kept here but not put in the avatar.
  -->
  <div class="flex justify-start">
    <div class="w-full max-w-3xl space-y-3 rounded-card border border-slate-200 bg-white px-4 py-3 text-sm dark:border-slate-700 dark:bg-slate-900">
      <header class="flex items-start gap-2">
        <AppIcon name="text" class="mt-0.5 text-primary" />
        <div class="min-w-0 flex-1">
          <p class="font-semibold">{{ t('avatars.batch.identityTitle', { name: view?.name || message.text }) }}</p>
          <p class="text-xs muted">{{ fromText }}</p>
        </div>
      </header>

      <div v-if="message.status === 'running'" class="flex flex-wrap items-center gap-2 muted">
        <Spinner :size="14" />
        <span class="min-w-0 flex-1">{{ t('avatars.identity.writing') }}</span>
        <button type="button" class="btn-ghost btn-sm px-1.5" :disabled="Boolean(busy)" @click="stop">
          <AppIcon name="stop" :size="14" />{{ t('avatars.identity.stop') }}
        </button>
      </div>
      <p v-else-if="message.status === 'cancelled'" class="muted">{{ t('avatars.batch.cancelled') }}</p>
      <AvatarsErrorLine
        v-else-if="message.status === 'error'"
        :item="message"
        :lead="data.identity && data.applied === false ? t('avatars.batch.notApplied') : ''"
        :spend-link="spendLink"
      />

      <ul v-if="photos.length" class="flex flex-wrap gap-2">
        <li v-for="p in photos" :key="p.id" class="w-14">
          <AvatarTile :photo="p" small />
        </li>
      </ul>

      <p v-if="data.brief" class="whitespace-pre-wrap break-words rounded-card bg-slate-50 p-2 text-xs dark:bg-slate-800/60">
        <span class="font-medium">{{ t('avatars.person.brief') }}:</span> {{ data.brief }}
      </p>

      <details v-if="data.identity" class="rounded-card border border-slate-200 p-2 dark:border-slate-700" :open="!isOld">
        <summary class="cursor-pointer text-xs font-medium">
          {{ t('avatars.batch.identityText', { n: data.identity.length }) }}
        </summary>
        <p class="mt-2 whitespace-pre-wrap break-words text-xs">{{ data.identity }}</p>
        <p class="mt-1 text-xs muted">{{ t('avatars.batch.identityEnglish') }}</p>
      </details>
      <p v-if="data.identity && isOld" class="text-xs muted">{{ t('avatars.batch.identityOld') }}</p>

      <footer class="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-slate-100 pt-2 text-xs muted dark:border-slate-800">
        <span v-if="data.model_id">{{ modelTitle(data.model_id) }}</span>
        <span v-if="message.cost_usd > 0">{{ formatUsd(message.cost_usd) }}</span>
        <NuxtLink v-if="message.cost_usd > 0 || message.status === 'error'" :to="spendLink" class="underline hover:text-primary">
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
import { avatarsBatchPhotos, avatarsSpendLink } from '~/utils/avatarsView.js'
import { useAvatar, useAvatarAction } from '~/composables/useAvatars.js'

const props = defineProps({
  message: { type: Object, required: true },
  room: { type: Object, required: true },
})
const { t, locale } = useI18n()
const api = useApi()
const chatModelTitle = inject('chatModelTitle', null)
const modelTitle = (id) => (chatModelTitle ? chatModelTitle(id) : id) || id

const data = computed(() => props.message.data || {})
const { view } = useAvatar(() => data.value.avatar_id)
const { busy, act } = useAvatarAction()

const photos = computed(() => avatarsBatchPhotos(view.value, data.value.photo_ids))
const spendLink = computed(() => props.message.spend_link || avatarsSpendLink('chat_message', props.message.id))
// the avatar has another description now (written by hand or by a later «Describe»)
const isOld = computed(() => Boolean(view.value && data.value.identity
  && String(view.value.identity || '').trim() !== String(data.value.identity).trim()))

const fromText = computed(() => {
  const mode = data.value.mode
  const n = data.value.photos_used ?? (data.value.photo_ids || []).length
  if (mode === 'reference' && n) return t('avatars.batch.fromPhotos', { n }, n)
  if (mode === 'auto' && !data.value.brief) return t('avatars.batch.fromNothing')
  return t('avatars.batch.fromBrief')
})

async function stop() {
  await act('stop', () => api.post(`/api/avatars/${data.value.avatar_id}/describe/cancel`))
}
</script>
