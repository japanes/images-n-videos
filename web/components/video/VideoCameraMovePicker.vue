<template>
  <!-- The camera move: a button with the current choice that opens a grid of moves by group. -->
  <div>
    <button
      type="button"
      class="input flex items-center gap-2 text-left"
      :disabled="disabled"
      @click="open = true"
    >
      <AppIcon name="video" :size="16" class="shrink-0 opacity-70" />
      <span class="min-w-0 flex-1 truncate">{{ currentLabel }}</span>
      <AppIcon name="more" :size="16" class="shrink-0 opacity-60" />
    </button>

    <ModalShell :open="open" :title="t('video.cameraMove.title')" size="xl" @close="open = false">
      <p class="muted mb-3 text-sm">{{ t('video.cameraMove.pickHint') }}</p>
      <p v-if="!groups.length" class="muted py-6 text-center text-sm">{{ t('video.cameraMove.empty') }}</p>
      <div class="space-y-5">
        <button
          type="button"
          class="w-full rounded-card border px-3 py-2 text-left text-sm"
          :class="!modelValue ? 'border-primary text-primary' : 'border-slate-200 dark:border-slate-600'"
          @click="choose('')"
        >
          {{ t('video.cameraMove.none') }}
        </button>
        <section v-for="g in groups" :key="g.name" class="space-y-2">
          <h3 class="text-sm font-semibold">{{ groupLabel(g.name) }}</h3>
          <div class="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
            <button
              v-for="code in g.codes"
              :key="code"
              type="button"
              class="rounded-card border px-3 py-2 text-left text-sm"
              :class="code === modelValue ? 'border-primary text-primary' : 'border-slate-200 hover:border-primary dark:border-slate-600'"
              :aria-pressed="code === modelValue"
              @click="choose(code)"
            >
              {{ moveLabel(code) }}
            </button>
          </div>
        </section>
      </div>
    </ModalShell>
  </div>
</template>

<script setup>
import { videoCameraGroups } from '~/utils/videoView.js'

const props = defineProps({
  modelValue: { type: String, default: '' },
  moves: { type: Array, default: () => [] },
  categories: { type: Array, default: () => [] },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue'])
const { t, te } = useI18n()
const open = ref(false)

const groups = computed(() => videoCameraGroups(props.moves, props.categories.length ? props.categories : undefined))
const moveLabel = (code) => (te(`video.cameraMove.moves.${code}`) ? t(`video.cameraMove.moves.${code}`) : code)
const groupLabel = (name) => (te(`video.cameraMove.groups.${name}`) ? t(`video.cameraMove.groups.${name}`) : name)
const currentLabel = computed(() => (props.modelValue ? moveLabel(props.modelValue) : t('video.cameraMove.none')))

function choose(code) {
  open.value = false
  if (code !== props.modelValue) emit('update:modelValue', code)
}
</script>
