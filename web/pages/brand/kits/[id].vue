<template>
  <section class="space-y-5">
    <NuxtLink to="/brand" class="btn-ghost btn-sm -ml-2">
      <AppIcon name="chevron-left" :size="14" />{{ t('brand.kit.back') }}
    </NuxtLink>

    <p v-if="error" class="rounded-button bg-rose-50 px-3 py-2 text-sm text-rose-800 dark:bg-rose-500/10 dark:text-rose-200">{{ error }}</p>
    <div v-if="loading && !kit" class="flex justify-center py-12"><Spinner :size="24" /></div>

    <template v-if="kit">
      <div class="card flex flex-wrap items-end gap-3 p-4">
        <label class="min-w-0 flex-1 basis-64">
          <span class="label">{{ t('brand.kit.nameLabel') }}</span>
          <BrandTextField
            :model-value="kit.name"
            :maxlength="80"
            :aria-label="t('brand.kit.nameLabel')"
            input-class="input text-base font-semibold"
            @save="(v) => patch({ name: v })"
          />
        </label>
        <button type="button" class="btn-ghost text-rose-600 dark:text-rose-400" :disabled="deleting" @click="removeKit">
          <AppIcon name="trash" :size="16" />{{ t('brand.kits.delete') }}
        </button>
      </div>

      <BrandColorsEditor :kit="kit" @updated="apply" />

      <section class="card space-y-3 p-4">
        <header>
          <h2 class="text-base font-semibold">{{ t('brand.kit.tone.title') }}</h2>
          <p class="mt-1 text-sm muted">{{ t('brand.kit.tone.hint') }}</p>
        </header>
        <BrandTextField
          :model-value="kit.tone"
          multiline
          :rows="4"
          :maxlength="2000"
          :placeholder="t('brand.kit.tone.placeholder')"
          :aria-label="t('brand.kit.tone.title')"
          @save="(v) => patch({ tone: v })"
        />
      </section>

      <BrandFontList :kit="kit" @changed="reloadSoon" />

      <BrandAssetManager
        :kit="kit"
        :kinds="ELEMENT_KINDS"
        :title="t('brand.kit.elements.title')"
        :hint="t('brand.kit.elements.hint')"
        :upload-label="t('brand.kit.elements.upload')"
        :empty-text="t('brand.kit.elements.empty')"
        @changed="reloadSoon"
      />

      <BrandAssetManager
        :kit="kit"
        :kinds="['reference']"
        :title="t('brand.kit.references.title')"
        :hint="t('brand.kit.references.hint')"
        :upload-label="t('brand.kit.references.upload')"
        :empty-text="t('brand.kit.references.empty')"
        @changed="reloadSoon"
      />
    </template>
  </section>
</template>

<script setup>
import { useDebounceFn } from '@vueuse/core'
import { ELEMENT_KINDS, brandErrorText } from '~/utils/brand.js'

const { t, te } = useI18n()
const api = useApi()
const route = useRoute()
const router = useRouter()
const toast = useToast()
const { confirm } = useConfirm()
const { on } = useEvents()

const kitId = computed(() => Number(route.params.id))
const kit = ref(null)
const loading = ref(false)
const error = ref('')
const deleting = ref(false)

async function load() {
  if (!kitId.value) return
  loading.value = true
  try {
    kit.value = await api.get(`/api/brand/kits/${kitId.value}`)
    error.value = ''
  } catch (err) {
    if (err.status === 404) {
      router.replace('/brand')
      return
    }
    error.value = brandErrorText(err, t, te)
  } finally {
    loading.value = false
  }
}

const reloadSoon = useDebounceFn(load, 250)

function apply(updated) {
  if (updated && updated.id === kitId.value) kit.value = updated
}

async function patch(body) {
  try {
    apply(await api.patch(`/api/brand/kits/${kitId.value}`, body))
  } catch (err) {
    toast.error(brandErrorText(err, t, te))
    reloadSoon()
  }
}

async function removeKit() {
  const ok = await confirm({ message: t('brand.kits.deleteConfirm', { name: kit.value.name }), confirmLabel: t('common.delete'), tone: 'danger' })
  if (!ok) return
  deleting.value = true
  try {
    await api.del(`/api/brand/kits/${kitId.value}`)
    toast.success(t('brand.kits.deleted'))
    router.replace('/brand')
  } catch (err) {
    toast.error(brandErrorText(err, t, te))
  } finally {
    deleting.value = false
  }
}

on('brand.updated', (data) => {
  if (Number(data?.kit_id) !== kitId.value) return
  if (data.what === 'kit_deleted') router.replace('/brand')
  else reloadSoon()
})
on('reconnect', reloadSoon)

watch(kitId, () => { kit.value = null; load() })
onMounted(load)
</script>
