<template>
  <!-- Words of a frame: a headline, body text, an accent. Saved when a field loses focus. -->
  <div class="space-y-2">
    <div v-for="(row, i) in rows" :key="row.key" class="flex items-start gap-2">
      <select
        v-model="row.role"
        class="input w-32 shrink-0 py-1 text-xs"
        :aria-label="t('studio.text.role')"
        :disabled="disabled"
        @change="save"
      >
        <option v-for="r in STUDIO_TEXT_ROLES" :key="r" :value="r">{{ t(`studio.textRoles.${r}`) }}</option>
      </select>
      <textarea
        v-model="row.text"
        rows="2"
        class="input min-w-0 flex-1 text-sm"
        :maxlength="STUDIO_LIMITS.words"
        :placeholder="t('studio.text.placeholder')"
        :disabled="disabled"
        @blur="save"
      />
      <button
        type="button"
        class="btn-ghost p-2 text-rose-600 dark:text-rose-400"
        :disabled="disabled"
        :title="t('studio.text.remove')"
        :aria-label="t('studio.text.remove')"
        @click="removeRow(i)"
      >
        <AppIcon name="trash" :size="16" />
      </button>
    </div>
    <button
      v-if="rows.length < STUDIO_MAX_TEXT_BLOCKS"
      type="button"
      class="btn-secondary btn-sm"
      :disabled="disabled"
      @click="addRow"
    >
      <AppIcon name="plus" :size="14" />{{ t('studio.text.add') }}
    </button>
    <p v-else class="muted text-xs">{{ t('studio.text.limit', { max: STUDIO_MAX_TEXT_BLOCKS }) }}</p>
  </div>
</template>

<script setup>
import { STUDIO_LIMITS, STUDIO_MAX_TEXT_BLOCKS, STUDIO_TEXT_ROLES } from '~/utils/studioView.js'

const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['save'])
const { t } = useI18n()

let keySeq = 0
const toRows = (list) => (list || []).map((b) => ({ key: ++keySeq, role: b.role || 'body', text: b.text || '' }))
const rows = ref(toRows(props.modelValue))
let lastSent = JSON.stringify(props.modelValue || [])

watch(() => props.modelValue, (v) => {
  const incoming = JSON.stringify(v || [])
  if (incoming === lastSent) return
  lastSent = incoming
  rows.value = toRows(v)
})

const clean = () => rows.value
  .map((r) => ({ role: r.role, text: r.text.trim() }))
  .filter((r) => r.text)

function save() {
  const out = clean()
  const text = JSON.stringify(out)
  if (text === lastSent) return
  lastSent = text
  emit('save', out)
}

function addRow() {
  rows.value = [...rows.value, { key: ++keySeq, role: rows.value.length ? 'body' : 'headline', text: '' }]
}

function removeRow(i) {
  rows.value = rows.value.filter((_, j) => j !== i)
  save()
}
</script>
