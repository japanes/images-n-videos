<template>
  <article class="group card flex flex-col overflow-hidden">
    <div class="brand-checker relative grid aspect-square place-items-center overflow-hidden">
      <img
        v-if="asset.file"
        :src="asset.file.thumb_url || asset.file.url"
        :alt="asset.name"
        class="max-h-full max-w-full object-contain"
        loading="lazy"
        draggable="false"
      >
      <button
        v-if="reorderable"
        type="button"
        class="absolute left-1.5 top-1.5 cursor-grab rounded-button bg-white/90 p-1 text-slate-600 shadow-card active:cursor-grabbing dark:bg-slate-900/90 dark:text-slate-300"
        :title="t('brand.kit.reorder')"
        :aria-label="t('brand.kit.reorder')"
        @mousedown="$emit('arm')"
        @keydown.left.prevent="$emit('nudge', -1)"
        @keydown.up.prevent="$emit('nudge', -1)"
        @keydown.right.prevent="$emit('nudge', 1)"
        @keydown.down.prevent="$emit('nudge', 1)"
      >
        <AppIcon name="menu" :size="14" />
      </button>
    </div>
    <div class="flex flex-1 flex-col gap-1 p-2">
      <p class="truncate text-sm font-medium" :title="asset.name">{{ asset.name || t('brand.kit.asset.untitled') }}</p>
      <p v-if="asset.position_hint" class="truncate text-xs muted" :title="asset.position_hint">{{ asset.position_hint }}</p>
      <p v-if="asset.note" class="line-clamp-2 text-xs muted" :title="asset.note">{{ asset.note }}</p>
      <div class="mt-auto flex items-center justify-end gap-1 pt-1">
        <button type="button" class="btn-ghost p-1.5" :disabled="busy" :title="t('brand.kit.asset.edit')" :aria-label="t('brand.kit.asset.edit')" @click="openEdit">
          <AppIcon name="edit" :size="14" />
        </button>
        <button
          type="button"
          class="btn-ghost p-1.5 text-rose-600 dark:text-rose-400"
          :disabled="busy"
          :title="t('brand.kit.asset.remove')"
          :aria-label="t('brand.kit.asset.remove')"
          @click="remove"
        >
          <AppIcon name="trash" :size="14" />
        </button>
      </div>
    </div>

    <ModalShell :open="editOpen" :title="t('brand.kit.asset.editTitle')" @close="editOpen = false">
      <form :id="formId" class="space-y-3" @submit.prevent="save">
        <label class="block">
          <span class="label">{{ t('brand.kit.asset.name') }}</span>
          <input v-model="form.name" type="text" class="input" maxlength="120" :placeholder="t('brand.kit.asset.namePlaceholder')">
        </label>
        <label class="block">
          <span class="label">{{ t('brand.kit.asset.kind') }}</span>
          <select v-model="form.kind" class="input">
            <option v-for="k in ELEMENT_KINDS" :key="k" :value="k">{{ t(`brand.kit.elements.kinds.${k}`) }}</option>
            <option value="reference">{{ t('brand.kit.references.title') }}</option>
          </select>
        </label>
        <label v-if="form.kind !== 'reference'" class="block">
          <span class="label">{{ t('brand.kit.asset.positionHint') }}</span>
          <input v-model="form.position_hint" type="text" class="input" maxlength="300" :placeholder="t('brand.kit.asset.positionHintPlaceholder')">
        </label>
        <label class="block">
          <span class="label">{{ t('brand.kit.asset.note') }}</span>
          <textarea v-model="form.note" class="input" rows="3" maxlength="1000" :placeholder="t('brand.kit.asset.notePlaceholder')" />
        </label>
        <p v-if="editError" class="text-sm text-rose-600 dark:text-rose-400">{{ editError }}</p>
      </form>
      <template #footer>
        <button type="button" class="btn-secondary" @click="editOpen = false">{{ t('common.cancel') }}</button>
        <button type="submit" :form="formId" class="btn-primary" :disabled="busy">
          <Spinner v-if="busy" :size="14" />{{ t('common.save') }}
        </button>
      </template>
    </ModalShell>
  </article>
</template>

<script setup>
import { ELEMENT_KINDS, brandErrorText } from '~/utils/brand.js'

const props = defineProps({
  asset: { type: Object, required: true },
  reorderable: { type: Boolean, default: false },
})
const emit = defineEmits(['changed', 'arm', 'nudge'])
const { t, te } = useI18n()
const api = useApi()
const toast = useToast()
const { confirm } = useConfirm()

const busy = ref(false)
const editOpen = ref(false)
const editError = ref('')
const form = ref({ name: '', kind: '', position_hint: '', note: '' })
const formId = computed(() => `brand-asset-${props.asset.id}`)

function openEdit() {
  const a = props.asset
  form.value = { name: a.name || '', kind: a.kind, position_hint: a.position_hint || '', note: a.note || '' }
  editError.value = ''
  editOpen.value = true
}

async function save() {
  busy.value = true
  try {
    const body = { name: form.value.name, note: form.value.note, kind: form.value.kind }
    if (form.value.kind !== 'reference') body.position_hint = form.value.position_hint
    await api.patch(`/api/brand/assets/${props.asset.id}`, body)
    editOpen.value = false
    emit('changed')
  } catch (err) {
    editError.value = brandErrorText(err, t, te)
  } finally {
    busy.value = false
  }
}

async function remove() {
  const name = props.asset.name || t('brand.kit.asset.untitled')
  const ok = await confirm({ message: t('brand.kit.asset.removeConfirm', { name }), confirmLabel: t('common.delete'), tone: 'danger' })
  if (!ok) return
  busy.value = true
  try {
    await api.del(`/api/brand/assets/${props.asset.id}`)
    emit('changed')
  } catch (err) {
    toast.error(brandErrorText(err, t, te))
  } finally {
    busy.value = false
  }
}
</script>
