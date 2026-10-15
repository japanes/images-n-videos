<template>
  <article class="card flex flex-col overflow-hidden">
    <NuxtLink :to="`/brand/kits/${kit.id}`" class="flex flex-1 flex-col gap-3 p-4 hover:bg-slate-50 dark:hover:bg-slate-700/40">
      <div class="flex items-center gap-3">
        <span class="brand-checker grid h-14 w-14 shrink-0 place-items-center overflow-hidden rounded-button border border-slate-200 dark:border-slate-700">
          <img v-if="kit.logo" :src="kit.logo.thumb_url || kit.logo.url" alt="" class="max-h-full max-w-full object-contain">
          <span v-else class="text-lg font-semibold muted">{{ initials }}</span>
        </span>
        <h2 class="min-w-0 flex-1 truncate text-base font-semibold">{{ kit.name }}</h2>
      </div>

      <div v-if="kit.colors.length" class="flex flex-wrap gap-1">
        <span
          v-for="(c, i) in kit.colors"
          :key="i"
          class="h-6 w-6 rounded-full border border-black/10 dark:border-white/20"
          :style="{ backgroundColor: c.hex }"
          :title="c.label ? `${c.hex} — ${c.label}` : c.hex"
        />
      </div>
      <p v-else class="text-xs muted">{{ t('brand.kits.noColors') }}</p>

      <p class="flex flex-wrap gap-x-3 gap-y-1 text-xs muted">
        <span>{{ t('brand.kits.fonts', { n: kit.fonts.length }) }}</span>
        <span>{{ t('brand.kits.elements', { n: elementCount }) }}</span>
        <span>{{ t('brand.kits.references', { n: kit.counts.reference || 0 }) }}</span>
      </p>
    </NuxtLink>
    <footer class="flex items-center justify-end gap-1 border-t border-slate-200 px-2 py-1.5 dark:border-slate-700">
      <button type="button" class="btn-ghost btn-sm text-rose-600 dark:text-rose-400" :disabled="busy" @click="$emit('delete', kit)">
        <AppIcon name="trash" :size="14" />{{ t('brand.kits.delete') }}
      </button>
    </footer>
  </article>
</template>

<script setup>
import { ELEMENT_KINDS } from '~/utils/brand.js'

const props = defineProps({
  kit: { type: Object, required: true },
  busy: { type: Boolean, default: false },
})
defineEmits(['delete'])
const { t } = useI18n()

const initials = computed(() => (props.kit.name || '?').trim().slice(0, 2).toUpperCase())
const elementCount = computed(() => ELEMENT_KINDS.reduce((sum, k) => sum + (props.kit.counts[k] || 0), 0))
</script>

<style>
/* Light checkerboard behind pictures so transparent logos stay visible. */
.brand-checker {
  background-color: #fff;
  background-image:
    linear-gradient(45deg, #e2e8f0 25%, transparent 25%),
    linear-gradient(-45deg, #e2e8f0 25%, transparent 25%),
    linear-gradient(45deg, transparent 75%, #e2e8f0 75%),
    linear-gradient(-45deg, transparent 75%, #e2e8f0 75%);
  background-size: 16px 16px;
  background-position: 0 0, 0 8px, 8px -8px, -8px 0;
}
</style>
