<template>
  <!--
    One picture of an avatar (a photo of the person, a face candidate, a shot of
    the pack) as a 3:4 tile: the picture or an empty place, a spinner while it is
    drawn (the old picture stays under it until the new one comes), a mark when
    the last try failed. `photo` is a picture of the avatar view.
  -->
  <div
    class="group relative overflow-hidden rounded-card border bg-slate-100 dark:bg-slate-800"
    :class="selected ? 'border-primary ring-2 ring-primary' : 'border-slate-200 dark:border-slate-700'"
    :style="{ aspectRatio: '3 / 4' }"
  >
    <img
      v-if="photo.file"
      :src="chatFileThumb(photo.file)"
      :alt="label"
      loading="lazy"
      class="h-full w-full object-cover"
      :class="state === 'busy' && 'opacity-40'"
    >
    <div v-else class="grid h-full w-full place-items-center muted">
      <AppIcon :name="state === 'error' ? 'alert' : 'image'" :size="small ? 18 : 24" :class="state === 'error' && 'text-rose-500'" />
    </div>

    <div v-if="state === 'busy'" class="absolute inset-0 grid place-items-center">
      <span class="flex items-center gap-1.5 rounded-badge bg-white/90 px-2 py-1 text-xs dark:bg-slate-900/90">
        <Spinner :size="12" />{{ photo.status === 'queued' ? t('avatars.tile.queued') : t('avatars.tile.drawing') }}
      </span>
    </div>

    <div class="pointer-events-none absolute left-1 top-1 flex flex-wrap gap-1">
      <span v-if="number" class="rounded-badge bg-slate-900/70 px-1.5 text-[11px] font-medium text-white">{{ number }}</span>
      <span v-if="photo.marked" class="rounded-badge bg-primary px-1 text-white" :title="t('avatars.tile.marked')">
        <AppIcon name="check" :size="11" />
      </span>
      <span v-if="photo.origin === 'upload' && photo.kind === 'shot'" class="rounded-badge bg-slate-900/70 px-1.5 text-[11px] text-white">
        {{ t('avatars.tile.own') }}
      </span>
      <span v-if="photo.custom_prompt" class="rounded-badge bg-amber-500/90 px-1 text-white" :title="t('avatars.tile.ownPrompt')">
        <AppIcon name="edit" :size="11" />
      </span>
    </div>
    <span
      v-if="!selectable && (state === 'error' || (photo.file && photo.status === 'error'))"
      class="pointer-events-none absolute right-1 top-1 rounded-badge bg-rose-600 px-1 text-white"
      :title="t('avatars.tile.failed')"
    >
      <AppIcon name="alert" :size="11" />
    </span>
    <span v-if="selectable" class="absolute right-1 top-1 grid h-5 w-5 place-items-center rounded-full border-2 border-white bg-slate-900/40" :class="selected && 'bg-primary'">
      <AppIcon v-if="selected" name="check" :size="12" class="text-white" />
    </span>

    <div v-if="title" class="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-slate-950/80 to-transparent px-1.5 pb-1 pt-4">
      <p class="truncate text-[11px] font-medium text-white">{{ title }}</p>
    </div>
  </div>
</template>

<script setup>
import { chatFileThumb } from '~/utils/chatView.js'
import { avatarsShotNumber, avatarsSlotState } from '~/utils/avatarsView.js'

const props = defineProps({
  photo: { type: Object, required: true },
  title: { type: String, default: '' },
  showNumber: { type: Boolean, default: false },
  small: { type: Boolean, default: false },
  selectable: { type: Boolean, default: false },
  selected: { type: Boolean, default: false },
})
const { t } = useI18n()

const state = computed(() => avatarsSlotState(props.photo))
const number = computed(() => (props.showNumber ? avatarsShotNumber(props.photo.shot_code) || '' : ''))
const label = computed(() => props.title || props.photo.title || props.photo.angle || '')
</script>
