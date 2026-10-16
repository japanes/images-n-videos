<template>
  <!--
    A small dropdown of actions. The list is put on top of the page (teleported),
    so it is never cut by a scrolling feed or a rounded tile.
    Items: { id, icon, label, onClick?, to?, href?, download?, disabled?, title?, tone? }.
  -->
  <span class="inline-flex">
    <button
      ref="button"
      type="button"
      :class="buttonClass"
      :title="label"
      :aria-label="label"
      aria-haspopup="menu"
      :aria-expanded="open"
      :disabled="disabled"
      @click.stop="toggle"
    >
      <slot name="button"><AppIcon :name="icon" :size="16" /></slot>
    </button>
    <Teleport to="body">
      <div
        v-if="open"
        ref="menu"
        role="menu"
        class="fixed z-[90] w-56 overflow-hidden rounded-card border border-slate-200 bg-white py-1 text-sm shadow-modal dark:border-slate-700 dark:bg-slate-800"
        :style="style"
        @keydown.escape="close"
      >
        <template v-for="item in items" :key="item.id">
          <NuxtLink v-if="item.to" :to="item.to" role="menuitem" :class="rowClass(item)" @click="close">
            <AppIcon :name="item.icon || 'chevron-right'" :size="16" /><span class="min-w-0 flex-1 truncate">{{ item.label }}</span>
          </NuxtLink>
          <a
            v-else-if="item.href"
            :href="item.href"
            :download="item.download || undefined"
            role="menuitem"
            :class="rowClass(item)"
            @click="close"
          >
            <AppIcon :name="item.icon || 'download'" :size="16" /><span class="min-w-0 flex-1 truncate">{{ item.label }}</span>
          </a>
          <button
            v-else
            type="button"
            role="menuitem"
            :class="rowClass(item)"
            :disabled="item.disabled"
            :title="item.title || undefined"
            @click="pick(item)"
          >
            <AppIcon :name="item.icon || 'chevron-right'" :size="16" /><span class="min-w-0 flex-1 truncate text-left">{{ item.label }}</span>
          </button>
        </template>
      </div>
    </Teleport>
  </span>
</template>

<script setup>
import { onClickOutside, useEventListener } from '@vueuse/core'

const props = defineProps({
  items: { type: Array, default: () => [] },
  label: { type: String, default: '' },
  icon: { type: String, default: 'more' },
  disabled: { type: Boolean, default: false },
  buttonClass: { type: [String, Array, Object], default: 'btn-ghost btn-sm px-1.5' },
})
const emit = defineEmits(['open'])

const open = ref(false)
const button = ref(null)
const menu = ref(null)
const style = ref({})
const WIDTH = 224 // w-56
const GAP = 6

function place() {
  const r = button.value?.getBoundingClientRect()
  if (!r) return
  const height = menu.value?.offsetHeight || 0
  const left = Math.max(GAP, Math.min(r.right - WIDTH, window.innerWidth - WIDTH - GAP))
  const below = window.innerHeight - r.bottom
  const top = below < height + GAP && r.top > height + GAP ? r.top - height - GAP : r.bottom + GAP
  style.value = { left: `${left}px`, top: `${Math.max(GAP, top)}px` }
}

async function toggle() {
  if (open.value) return close()
  open.value = true
  emit('open')
  style.value = { visibility: 'hidden' }
  await nextTick()
  place()
}

function close() {
  open.value = false
}

function pick(item) {
  if (item.disabled) return
  close()
  item.onClick?.()
}

function rowClass(item) {
  return [
    'flex w-full items-center gap-2.5 px-3 py-2 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50 dark:hover:bg-slate-700/60',
    item.tone === 'danger' ? 'text-rose-600 dark:text-rose-400' : '',
  ]
}

onClickOutside(menu, close, { ignore: [button] })
useEventListener(window, 'resize', close)
useEventListener(window, 'scroll', () => { if (open.value) close() }, { capture: true, passive: true })
watch(() => props.disabled, (v) => { if (v) close() })

defineExpose({ close })
</script>
