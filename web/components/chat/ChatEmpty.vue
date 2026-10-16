<template>
  <!-- A chat with nothing in it yet: what to type, and a few examples that fill the composer (nothing is sent). -->
  <div class="mx-auto flex max-w-xl flex-col items-center gap-4 px-4 py-10 text-center sm:py-16">
    <span class="grid h-12 w-12 place-items-center rounded-2xl bg-primary/10 text-primary">
      <AppIcon :name="mode === 'video' ? 'video' : 'image'" :size="22" />
    </span>
    <h2 class="text-lg font-semibold">{{ t('chat.empty.title') }}</h2>
    <p class="text-sm muted">{{ mode === 'video' ? t('chat.empty.videoText') : t('chat.empty.imageText') }}</p>
    <div class="flex w-full flex-col gap-2 pt-2">
      <button
        v-for="key in examples"
        :key="key"
        type="button"
        class="rounded-card border border-slate-200 px-4 py-2.5 text-left text-sm text-slate-700 hover:border-primary/50 hover:bg-primary/5 dark:border-slate-700 dark:text-slate-200"
        @click="$emit('example', t(key))"
      >
        {{ t(key) }}
      </button>
    </div>
    <p class="text-xs muted">{{ t('chat.empty.hint') }}</p>
  </div>
</template>

<script setup>
const props = defineProps({
  mode: { type: String, default: 'image' },
})
defineEmits(['example'])
const { t } = useI18n()

const examples = computed(() => (props.mode === 'video'
  ? ['chat.empty.videoExample1', 'chat.empty.videoExample2']
  : ['chat.empty.imageExample1', 'chat.empty.imageExample2', 'chat.empty.imageExample3']))
</script>
