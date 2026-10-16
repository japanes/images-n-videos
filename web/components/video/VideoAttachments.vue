<template>
  <!--
    Pictures that go with the take: the opening frame, the closing frame and
    reference pictures. v-model is { first_frame_id, last_frame_id, references }.
    What the chosen model cannot use is said here, before any money.
  -->
  <div class="space-y-3 text-sm">
    <div class="grid grid-cols-2 gap-3">
      <div v-for="slot in slots" :key="slot.key" class="space-y-1">
        <span class="label">{{ t(`video.attach.${slot.key}.title`) }}</span>
        <div v-if="value[slot.field]" class="group relative aspect-square w-full overflow-hidden rounded-card border border-slate-200 dark:border-slate-600">
          <img :src="videoThumbUrl(value[slot.field], 320)" alt="" loading="lazy" class="h-full w-full object-cover">
          <button
            type="button"
            class="absolute right-1 top-1 inline-flex h-6 w-6 items-center justify-center rounded bg-slate-900/70 text-white hover:bg-rose-600"
            :disabled="disabled"
            :title="t('video.attach.remove')"
            :aria-label="t('video.attach.remove')"
            @click="set({ [slot.field]: null })"
          >
            <AppIcon name="close" :size="14" />
          </button>
        </div>
        <button
          v-else
          type="button"
          class="flex aspect-square w-full flex-col items-center justify-center gap-1 rounded-card border-2 border-dashed border-slate-300 px-2 text-center text-xs hover:border-primary disabled:opacity-50 dark:border-slate-600"
          :disabled="disabled || !slot.allowed"
          @click="picking = slot.field"
        >
          <AppIcon name="image" :size="18" />
          <span>{{ slot.allowed ? t(`video.attach.${slot.key}.hint`) : t(`video.attach.${slot.key}.unsupported`) }}</span>
        </button>
      </div>
    </div>

    <p v-if="value.last_frame_id && !value.first_frame_id" class="text-xs text-amber-700 dark:text-amber-300">
      {{ t('video.errors.video_last_frame_needs_first') }}
    </p>
    <p v-if="value.last_frame_id && model && !model.last_frame" class="text-xs text-amber-700 dark:text-amber-300">
      {{ t('video.attach.last.dropped') }}
    </p>

    <div class="space-y-1">
      <span class="label">{{ t('video.attach.references.title') }}</span>
      <p v-if="maxRefs === 0" class="muted text-xs">{{ t('video.attach.references.unsupported') }}</p>
      <template v-else>
        <StudioPictureList
          :ids="value.references || []"
          :max="maxRefs"
          :disabled="disabled"
          :picker-title="t('video.attach.references.title')"
          @update="set({ references: $event })"
        />
        <p class="muted text-xs">{{ t('video.attach.references.hint', { max: maxRefs }) }}</p>
      </template>
      <p v-if="tooMany" class="text-xs text-amber-700 dark:text-amber-300">
        {{ t('video.errors.video_too_many_references', { max: maxRefs, count: (value.references || []).length }) }}
      </p>
    </div>

    <div
      v-for="w in shownWarnings"
      :key="w"
      class="rounded-card bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:bg-amber-500/10 dark:text-amber-100"
    >
      {{ te(`video.warnings.${w}`) ? t(`video.warnings.${w}`) : w }}
    </div>

    <StudioSourcePicker
      :open="Boolean(picking)"
      :title="picking === 'last_frame_id' ? t('video.attach.last.title') : t('video.attach.first.title')"
      @pick="pick"
      @close="picking = null"
    />
  </div>
</template>

<script setup>
import { videoAttachWarnings, videoThumbUrl } from '~/utils/videoView.js'

const props = defineProps({
  modelValue: { type: Object, required: true },
  model: { type: Object, default: null },
  // take.warnings from the server; the form also works them out itself for the moment between saves.
  warnings: { type: Array, default: () => [] },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue'])
const { t, te } = useI18n()
const picking = ref(null)

const value = computed(() => props.modelValue || {})
const maxRefs = computed(() => Number(props.model?.max_references ?? 0))
const tooMany = computed(() => (value.value.references || []).length > maxRefs.value)
const slots = computed(() => [
  { key: 'first', field: 'first_frame_id', allowed: props.model ? props.model.first_frame !== false : true },
  { key: 'last', field: 'last_frame_id', allowed: Boolean(props.model?.last_frame) },
])
const shownWarnings = computed(() => {
  const all = new Set([...(props.warnings || []), ...videoAttachWarnings(props.model, value.value)])
  return [...all]
})

function set(fields) {
  emit('update:modelValue', { ...value.value, ...fields })
}

function pick(files) {
  const field = picking.value
  picking.value = null
  const file = (files || [])[0]
  if (field && file?.id) set({ [field]: file.id })
}
</script>
