<template>
  <section class="card space-y-3 p-4" @focusin="focused = true" @focusout="onFocusOut">
    <header>
      <h2 class="text-base font-semibold">{{ t('brand.kit.colors.title') }}</h2>
      <p class="mt-1 text-sm muted">{{ t('brand.kit.colors.hint') }}</p>
    </header>

    <p v-if="!rows.length" class="text-sm muted">{{ t('brand.kit.colors.empty') }}</p>
    <ul v-else class="space-y-2">
      <li v-for="(row, i) in rows" :key="row.key" class="flex flex-wrap items-center gap-2">
        <input
          type="color"
          class="h-9 w-11 shrink-0 cursor-pointer rounded-input border border-slate-300 bg-white p-0.5 dark:border-slate-600 dark:bg-slate-950"
          :value="row.hex.toLowerCase()"
          :aria-label="t('brand.kit.colors.hexLabel')"
          @input="row.text = $event.target.value.toUpperCase()"
          @change="setHex(row, $event.target.value)"
        >
        <input
          v-model="row.text"
          type="text"
          class="input w-28 font-mono uppercase"
          maxlength="7"
          spellcheck="false"
          :aria-label="t('brand.kit.colors.hexLabel')"
          @blur="setHex(row, row.text)"
          @keydown.enter.prevent="$event.target.blur()"
        >
        <input
          v-model="row.label"
          type="text"
          class="input min-w-0 flex-1 basis-40"
          maxlength="40"
          :placeholder="t('brand.kit.colors.labelPlaceholder')"
          @blur="saveIfChanged"
          @keydown.enter.prevent="$event.target.blur()"
        >
        <button
          type="button"
          class="btn-ghost p-2"
          :disabled="i === 0 || saving"
          :title="t('brand.kit.colors.moveUp')"
          :aria-label="t('brand.kit.colors.moveUp')"
          @click="move(i)"
        >
          <AppIcon name="chevron-down" :size="16" class="rotate-180" />
        </button>
        <button
          type="button"
          class="btn-ghost p-2 text-rose-600 dark:text-rose-400"
          :disabled="saving"
          :title="t('brand.kit.colors.remove')"
          :aria-label="t('brand.kit.colors.remove')"
          @click="remove(i)"
        >
          <AppIcon name="trash" :size="16" />
        </button>
      </li>
    </ul>

    <div class="flex flex-wrap items-center gap-3">
      <button type="button" class="btn-secondary btn-sm" :disabled="rows.length >= MAX_COLORS || saving" @click="add">
        <AppIcon name="plus" :size="14" />{{ t('brand.kit.colors.add') }}
      </button>
      <span v-if="rows.length >= MAX_COLORS" class="text-xs muted">{{ t('brand.kit.colors.max', { n: MAX_COLORS }) }}</span>
    </div>
  </section>
</template>

<script setup>
import { MAX_COLORS, brandErrorText, moveItem, normalizeHex } from '~/utils/brand.js'

const props = defineProps({
  kit: { type: Object, required: true },
})
const emit = defineEmits(['updated'])
const { t, te } = useI18n()
const api = useApi()
const toast = useToast()

let seq = 0
const toRows = (colors) => (colors || []).map((c) => ({ key: ++seq, hex: c.hex, text: c.hex, label: c.label || '' }))
const rows = ref(toRows(props.kit.colors))
const focused = ref(false)
const saving = ref(false)

const payload = () => rows.value.map((r) => ({ hex: r.hex, label: r.label.trim() }))
const serverPayload = () => (props.kit.colors || []).map((c) => ({ hex: c.hex, label: c.label || '' }))

// Outside changes (another tab, a reload) replace the rows unless the person is typing here.
watch(() => props.kit.colors, (colors) => {
  if (!focused.value) rows.value = toRows(colors)
}, { deep: true })

function onFocusOut(e) {
  if (!e.currentTarget.contains(e.relatedTarget)) focused.value = false
}

async function save() {
  saving.value = true
  try {
    emit('updated', await api.patch(`/api/brand/kits/${props.kit.id}`, { colors: payload() }))
  } catch (err) {
    toast.error(brandErrorText(err, t, te))
    rows.value = toRows(props.kit.colors)
  } finally {
    saving.value = false
  }
}

function saveIfChanged() {
  if (JSON.stringify(payload()) !== JSON.stringify(serverPayload())) save()
}

function setHex(row, value) {
  const hex = normalizeHex(value)
  if (!hex) {
    toast.error(t('brand.errors.bad_color', { value: String(value || '').trim() }))
    row.text = row.hex
    return
  }
  row.hex = hex
  row.text = hex
  saveIfChanged()
}

function add() {
  if (rows.value.length >= MAX_COLORS) return
  const hex = '#000000'
  rows.value = [...rows.value, { key: ++seq, hex, text: hex, label: '' }]
  save()
}

function move(i) {
  rows.value = moveItem(rows.value, i, i - 1)
  save()
}

function remove(i) {
  rows.value = rows.value.filter((_, j) => j !== i)
  save()
}
</script>
