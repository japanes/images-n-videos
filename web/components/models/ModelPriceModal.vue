<template>
  <ModalShell :open="open" :title="model ? t('models.priceModal.title', { model: model.title || model.id }) : ''" @close="$emit('close')">
    <form id="model-price" class="space-y-4" @submit.prevent="save">
      <p class="text-sm muted">{{ t('models.priceModal.intro') }}</p>
      <p v-if="!fields.length" class="text-sm muted">{{ t('models.price.none') }}</p>
      <label v-for="f in fields" :key="f.path" class="block">
        <span class="label">{{ fieldLabel(f) }}</span>
        <input
          v-model="values[f.path]"
          type="text"
          inputmode="decimal"
          class="input tabular-nums"
          :class="badPath === f.path && 'border-rose-500'"
          :aria-invalid="badPath === f.path"
        >
        <span v-if="badPath === f.path" class="mt-1 block text-xs text-rose-700 dark:text-rose-300">{{ t('models.priceModal.bad') }}</span>
        <span v-else class="mt-1 block text-xs muted">{{ t('models.priceModal.registry', { usd: priceText(f.seed) }) }}</span>
      </label>
      <p v-if="error" class="text-sm text-rose-700 dark:text-rose-300">{{ error }}</p>
    </form>
    <template #footer>
      <button v-if="model?.user_price" type="button" class="btn-ghost mr-auto" :disabled="saving" @click="useRegistry">
        {{ t('models.priceModal.useRegistry') }}
      </button>
      <button type="button" class="btn-ghost" @click="$emit('close')">{{ t('common.cancel') }}</button>
      <button type="submit" form="model-price" class="btn-primary" :disabled="saving || !fields.length">
        <Spinner v-if="saving" :size="14" />{{ t('common.save') }}
      </button>
    </template>
  </ModalShell>
</template>

<script setup>
import { apiErrorText } from '~/utils/apiErrorText.js'
import { modelPriceBody, modelPriceFields, priceInputText, priceText } from '~/utils/modelsView.js'

const props = defineProps({
  open: { type: Boolean, default: false },
  model: { type: Object, default: null },
})
const emit = defineEmits(['close', 'saved'])

const { t, te } = useI18n()
const api = useApi()
const toast = useToast()

const values = ref({})
const badPath = ref('')
const error = ref('')
const saving = ref(false)

const fields = computed(() => (props.model ? modelPriceFields(props.model) : []))

function fieldLabel(f) {
  if (f.res) return t('models.priceModal.fields.per_second', { res: f.res })
  const key = `models.priceModal.fields.${f.path}`
  return te(key) ? t(key) : f.path
}

watch(() => [props.open, props.model?.id], ([isOpen]) => {
  if (!isOpen) return
  values.value = Object.fromEntries(fields.value.map((f) => [f.path, priceInputText(f.value)]))
  badPath.value = ''
  error.value = ''
}, { immediate: true })

async function send(price) {
  saving.value = true
  error.value = ''
  try {
    const model = await api.put(`/api/models/${encodeURIComponent(props.model.id)}/price`, { price })
    toast.success(price ? t('models.priceModal.saved') : t('models.priceModal.reset'))
    emit('saved', model)
    emit('close')
  } catch (err) {
    if (err?.code === 'bad_price' && err.details?.field) badPath.value = String(err.details.field)
    error.value = apiErrorText(err, t, te)
  } finally {
    saving.value = false
  }
}

function save() {
  const body = modelPriceBody(fields.value, values.value)
  if (body.error) {
    badPath.value = body.error
    return
  }
  badPath.value = ''
  if (!body.price && !props.model.user_price) {
    emit('close')
    return
  }
  send(body.price)
}

const useRegistry = () => send(null)
</script>
