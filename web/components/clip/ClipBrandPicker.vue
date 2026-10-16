<template>
  <div class="space-y-2">
    <label class="block">
      <span class="label">{{ t('clip.brand.title') }}</span>
      <select class="input" :value="kitId" :disabled="busy" @change="choose($event.target.value)">
        <option value="">{{ t('clip.brand.none') }}</option>
        <option v-for="kit in kits" :key="kit.id" :value="String(kit.id)">{{ kit.name }}</option>
        <option v-if="kitMissing" :value="kitId">{{ project.brand.name }}</option>
      </select>
    </label>
    <p class="text-xs muted">{{ hint || t('clip.brand.hint') }}</p>
    <div v-if="project?.brand_changed" class="flex flex-wrap items-center gap-2 rounded-button bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:bg-amber-500/10 dark:text-amber-100">
      <span class="flex-1">{{ t('clip.brand.changed') }}</span>
      <button type="button" class="btn-secondary btn-sm" :disabled="busy" @click="refresh">{{ t('clip.brand.refresh') }}</button>
    </div>
    <p v-if="error" class="text-xs text-rose-700 dark:text-rose-300">{{ error }}</p>
  </div>
</template>

<script setup>
import { clipErrorText } from '~/utils/clipState.js'

defineProps({
  hint: { type: String, default: '' },
})
const { t, te } = useI18n()
const api = useApi()
const ed = useClipContext()
const { project } = ed

const kits = ref([])
const busy = ref(false)
const error = ref('')

const kitId = computed(() => (project.value?.brand?.kit_id ? String(project.value.brand.kit_id) : ''))
const kitMissing = computed(() => !!kitId.value && !kits.value.some((k) => String(k.id) === kitId.value))

async function loadKits() {
  try {
    kits.value = (await api.get('/api/brand/kits')).items || []
  } catch {
    kits.value = []
  }
}

async function run(body) {
  busy.value = true
  error.value = ''
  try {
    await ed.setBrand(body)
  } catch (err) {
    error.value = clipErrorText(err, t, te)
  } finally {
    busy.value = false
  }
}

const choose = (value) => run({ kit_id: value ? Number(value) : null })
const refresh = () => run({ refresh: true })

onMounted(loadKits)
</script>
