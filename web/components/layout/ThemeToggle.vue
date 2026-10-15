<template>
  <button type="button" class="btn-ghost p-1.5" :title="t('common.theme')" :aria-label="t('common.theme')" @click="toggle()">
    <AppIcon :name="isDark ? 'sun' : 'moon'" :size="16" />
  </button>
</template>

<script setup>
import { useDark, useToggle } from '@vueuse/core'

const { t } = useI18n()
const isDark = useDark({ storageKey: 'vf_theme' })
const toggle = useToggle(isDark)
</script>
