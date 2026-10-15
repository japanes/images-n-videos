<template>
  <div class="page space-y-4">
    <header class="flex flex-wrap items-start gap-3">
      <div class="min-w-0 flex-1">
        <h1 class="page-title">{{ t('models.title') }}</h1>
        <p class="mt-1 text-sm muted">{{ t('models.subtitle') }}</p>
      </div>
      <div class="flex flex-col items-end gap-1">
        <PriceButton
          :label="t('models.check.button')"
          icon="refresh"
          :usd="0"
          :busy="checking"
          :disabled="!m.loaded.value"
          @click="check"
        />
        <p class="text-right text-xs muted" :title="t('models.check.hint')">
          {{ checkedText }}
          <button
            v-if="m.overview.value.checked_at"
            type="button"
            class="ml-1 text-primary hover:underline"
            :disabled="forgetting"
            @click="forget"
          >
            {{ t('models.check.forget') }}
          </button>
        </p>
      </div>
    </header>

    <p v-if="!m.overview.value.checked_at && m.loaded.value" class="text-sm muted">{{ t('models.check.hint') }}</p>

    <div v-if="!m.loaded.value && m.loading.value" class="flex justify-center py-12"><Spinner :size="24" /></div>

    <EmptyState v-else-if="!m.loaded.value && m.error.value" icon="alert" :title="t('models.loadFailed')" :text="errorText">
      <button type="button" class="btn-secondary" @click="m.load()">{{ t('common.retry') }}</button>
    </EmptyState>

    <template v-else-if="m.loaded.value">
      <div class="flex flex-wrap items-center gap-1 border-b border-slate-200 dark:border-slate-700" role="tablist">
        <button
          v-for="name in MODEL_TABS"
          :key="name"
          type="button"
          role="tab"
          :aria-selected="tab === name"
          class="-mb-px flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm"
          :class="tab === name ? 'border-primary font-medium text-primary' : 'border-transparent muted hover:text-slate-700 dark:hover:text-slate-200'"
          @click="setTab(name)"
        >
          {{ t(`models.tabs.${name}`) }}
          <span v-if="name !== 'roles'" class="rounded-badge bg-slate-100 px-1.5 text-xs tabular-nums dark:bg-slate-700">
            {{ m.byKind(name).length }}
          </span>
        </button>
      </div>

      <ModelRolesPanel
        v-if="tab === 'roles'"
        :models="m.items.value"
        :roles="m.roles.value"
        :effective-text="m.effective.value.text || ''"
        @changed="m.load()"
      />

      <template v-else>
        <p
          v-if="replacedText"
          class="flex gap-2 rounded-card bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:bg-amber-500/10 dark:text-amber-200"
        >
          <AppIcon name="alert" :size="16" class="mt-0.5 shrink-0" />{{ replacedText }}
        </p>
        <p
          v-else-if="kindModels.length && !m.effective.value[tab]"
          class="flex gap-2 rounded-card bg-rose-50 px-4 py-3 text-sm text-rose-800 dark:bg-rose-500/10 dark:text-rose-200"
        >
          <AppIcon name="alert" :size="16" class="mt-0.5 shrink-0" />{{ t('models.noUsable') }}
        </p>

        <EmptyState v-if="!kindModels.length" icon="models" :title="t('models.empty')" />
        <div v-else class="grid gap-4 md:grid-cols-2">
          <ModelCard
            v-for="model in kindModels"
            :key="model.id"
            :model="model"
            :in-use="m.effective.value[tab] === model.id"
            :busy="busy.has(model.id)"
            @toggle="toggle(model, $event)"
            @make-default="makeDefault(model)"
            @edit-price="priceModel = model"
          />
        </div>
      </template>
    </template>

    <ModelPriceModal :open="!!priceModel" :model="priceModel" @close="priceModel = null" @saved="onPriceSaved" />
  </div>
</template>

<script setup>
import { apiErrorText } from '~/utils/apiErrorText.js'
import { formatDateTime } from '~/utils/format.js'
import { MODEL_TABS } from '~/utils/modelsView.js'

const { t, te, locale } = useI18n()
const api = useApi()
const route = useRoute()
const router = useRouter()
const toast = useToast()
const { confirm } = useConfirm()

const m = useModels()
const checking = ref(false)
const forgetting = ref(false)
const busy = ref(new Set())
const priceModel = ref(null)

const tab = computed(() => (MODEL_TABS.includes(route.query.tab) ? route.query.tab : MODEL_TABS[0]))
const setTab = (name) => router.replace({ query: { ...route.query, tab: name } })

const kindModels = computed(() => m.byKind(tab.value))
const errorText = computed(() => (m.error.value ? apiErrorText(m.error.value, t, te) : ''))

const checkedText = computed(() => {
  const at = m.overview.value.checked_at
  return at ? t('models.check.last', { time: formatDateTime(at, locale.value) }) : t('models.check.never')
})

// The default of this kind is not in the project, so another model stands in.
const replacedText = computed(() => {
  const kind = tab.value
  const def = kindModels.value.find((x) => x.is_default)
  const used = m.effective.value[kind]
  if (!def || !used || used === def.id) return ''
  return t('models.replaced', { default: def.title || def.id, used: m.find(used)?.title || used })
})

function setBusy(id, on) {
  const next = new Set(busy.value)
  if (on) next.add(id)
  else next.delete(id)
  busy.value = next
}

async function check() {
  checking.value = true
  try {
    const res = await api.post('/api/models/check')
    if (res?.checked) {
      const found = (res.items || []).filter((x) => x.available).length
      toast.success(t('models.check.done', { found, total: (res.items || []).length }))
    } else {
      toast.info(t('models.check.inconclusive'))
    }
    await m.load()
  } catch (err) {
    toast.error(apiErrorText(err, t, te))
  } finally {
    checking.value = false
  }
}

async function forget() {
  const ok = await confirm({
    message: t('models.check.forgetAsk'),
    confirmLabel: t('models.check.forget'),
  })
  if (!ok) return
  forgetting.value = true
  try {
    await api.del('/api/models/check')
    toast.success(t('models.check.forgotten'))
    await m.load()
  } catch (err) {
    toast.error(apiErrorText(err, t, te))
  } finally {
    forgetting.value = false
  }
}

async function toggle(model, enabled) {
  setBusy(model.id, true)
  try {
    const next = await api.patch(`/api/models/${encodeURIComponent(model.id)}`, { enabled })
    m.replace(next)
    const title = next?.title || model.id
    toast.success(enabled ? t('models.actions.shown', { model: title }) : t('models.actions.hidden', { model: title }))
    await m.load()
  } catch (err) {
    toast.error(apiErrorText(err, t, te))
  } finally {
    setBusy(model.id, false)
  }
}

async function makeDefault(model) {
  setBusy(model.id, true)
  try {
    const next = await api.patch(`/api/models/${encodeURIComponent(model.id)}`, { is_default: true })
    toast.success(t('models.actions.madeDefault', { model: next?.title || model.id }))
    await m.load()
  } catch (err) {
    toast.error(apiErrorText(err, t, te))
  } finally {
    setBusy(model.id, false)
  }
}

function onPriceSaved(model) {
  m.replace(model)
}

onMounted(() => m.load())
</script>
