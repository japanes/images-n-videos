<template>
  <!--
    A paid repeat asks first, right where the button was: what it will do, the
    price, «Go» and «Cancel». Nothing is spent until «Go».
  -->
  <div class="flex flex-wrap items-center gap-2 rounded-card border border-primary/30 bg-primary/5 px-3 py-2 text-sm">
    <span class="min-w-0 flex-1">{{ question }}</span>
    <Spinner v-if="loading" :size="14" />
    <span v-else-if="refusal" class="w-full text-xs text-rose-600 dark:text-rose-400 sm:w-auto">{{ refusal }}</span>
    <PriceButton
      class="btn-sm"
      icon="refresh"
      :label="t('chat.repeat.go')"
      :usd="usd"
      :disabled="loading || usd === null"
      :busy="busy"
      @click="go"
    />
    <button type="button" class="btn-ghost btn-sm" :disabled="busy" @click="$emit('cancel')">{{ t('common.cancel') }}</button>
  </div>
</template>

<script setup>
import { chatReasonText } from '~/utils/chatView.js'

const props = defineProps({
  room: { type: Object, required: true },
  messageId: { type: Number, required: true }, // the request message
  original: { type: Boolean, default: false }, // «Send as I wrote»
  question: { type: String, required: true },
})
const emit = defineEmits(['done', 'cancel'])
const { t, te } = useI18n()

const estimate = ref(null)
const loading = ref(true)
const usd = computed(() => (
  estimate.value && !estimate.value.refusal && !estimate.value.failed ? Number(estimate.value.usd ?? 0) : null
))
const refusal = computed(() => {
  if (estimate.value?.failed) return t('chat.repeat.noPrice')
  return estimate.value?.refusal ? chatReasonText(estimate.value.refusal, t, te, estimate.value.refusal_details) : ''
})
const busy = computed(() => props.room.isPending(`repeat:${props.messageId}`))

onMounted(async () => {
  estimate.value = await props.room.repeatEstimate(props.messageId, props.original)
  if (!estimate.value) estimate.value = { failed: true }
  loading.value = false
})

async function go() {
  const res = await props.room.repeat(props.messageId, props.original)
  if (res) emit('done', res)
}
</script>
