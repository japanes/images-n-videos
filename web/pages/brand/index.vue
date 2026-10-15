<template>
  <section class="space-y-4">
    <div v-if="kits.length" class="flex flex-wrap items-center gap-3">
      <p class="min-w-0 flex-1 text-sm muted">{{ t('brand.kits.emptyText') }}</p>
      <button type="button" class="btn-primary" @click="openCreate">
        <AppIcon name="plus" :size="16" />{{ t('brand.kits.newKit') }}
      </button>
    </div>

    <p v-if="error" class="rounded-button bg-rose-50 px-3 py-2 text-sm text-rose-800 dark:bg-rose-500/10 dark:text-rose-200">{{ error }}</p>

    <div v-if="loading && !kits.length" class="flex justify-center py-12"><Spinner :size="24" /></div>
    <EmptyState
      v-else-if="!kits.length && !error"
      icon="brand"
      :title="t('brand.kits.emptyTitle')"
      :text="t('brand.kits.emptyText')"
    >
      <button type="button" class="btn-primary" @click="openCreate">
        <AppIcon name="plus" :size="16" />{{ t('brand.kits.newKit') }}
      </button>
    </EmptyState>
    <div v-else class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <BrandKitCard v-for="kit in kits" :key="kit.id" :kit="kit" :busy="busyId === kit.id" @delete="remove" />
    </div>

    <ModalShell :open="createOpen" :title="t('brand.kits.createTitle')" size="sm" @close="createOpen = false">
      <form id="brand-kit-create" class="space-y-2" @submit.prevent="create">
        <label class="block">
          <span class="label">{{ t('brand.kits.nameLabel') }}</span>
          <input ref="nameInput" v-model="newName" type="text" class="input" maxlength="80" :placeholder="t('brand.kits.namePlaceholder')">
        </label>
        <p v-if="createError" class="text-sm text-rose-600 dark:text-rose-400">{{ createError }}</p>
      </form>
      <template #footer>
        <button type="button" class="btn-secondary" @click="createOpen = false">{{ t('common.cancel') }}</button>
        <button type="submit" form="brand-kit-create" class="btn-primary" :disabled="creating || !newName.trim()">
          <Spinner v-if="creating" :size="14" />{{ t('brand.kits.create') }}
        </button>
      </template>
    </ModalShell>
  </section>
</template>

<script setup>
import { useDebounceFn } from '@vueuse/core'
import { brandErrorText } from '~/utils/brand.js'

const { t, te } = useI18n()
const api = useApi()
const router = useRouter()
const toast = useToast()
const { confirm } = useConfirm()
const { on } = useEvents()

const kits = ref([])
const loading = ref(false)
const error = ref('')
const busyId = ref(null)

const createOpen = ref(false)
const newName = ref('')
const creating = ref(false)
const createError = ref('')
const nameInput = ref(null)

async function load() {
  loading.value = true
  try {
    kits.value = (await api.get('/api/brand/kits')).items
    error.value = ''
  } catch (err) {
    error.value = brandErrorText(err, t, te)
  } finally {
    loading.value = false
  }
}

function openCreate() {
  newName.value = ''
  createError.value = ''
  createOpen.value = true
  nextTick(() => setTimeout(() => nameInput.value?.focus(), 50))
}

async function create() {
  if (!newName.value.trim() || creating.value) return
  creating.value = true
  try {
    const kit = await api.post('/api/brand/kits', { name: newName.value })
    createOpen.value = false
    router.push(`/brand/kits/${kit.id}`)
  } catch (err) {
    createError.value = brandErrorText(err, t, te)
  } finally {
    creating.value = false
  }
}

async function remove(kit) {
  const ok = await confirm({ message: t('brand.kits.deleteConfirm', { name: kit.name }), confirmLabel: t('common.delete'), tone: 'danger' })
  if (!ok) return
  busyId.value = kit.id
  try {
    await api.del(`/api/brand/kits/${kit.id}`)
    kits.value = kits.value.filter((k) => k.id !== kit.id)
    toast.success(t('brand.kits.deleted'))
  } catch (err) {
    toast.error(brandErrorText(err, t, te))
  } finally {
    busyId.value = null
  }
}

const reloadSoon = useDebounceFn(load, 300)
on('brand.updated', (data) => {
  if (['kit', 'kit_deleted', 'asset', 'asset_deleted', 'asset_order'].includes(data?.what)) reloadSoon()
})
on('reconnect', reloadSoon)

onMounted(load)
</script>
