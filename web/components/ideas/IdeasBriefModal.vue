<template>
  <!--
    The «Ideas» window of the chat (module 05). A brief and, on its own tab, the
    place and light of the shoot; three switches with their prices; one press
    writes the ideas and (when on) draws the first frame. The result is a card
    in the chat. What was typed and not sent stays for the next opening.
  -->
  <ModalShell open :title="t('ideas.modal.title')" size="lg" :close-on-overlay="false" body-class="p-0" @close="close">
    <div class="space-y-4 px-5 pb-5 pt-4">
      <p class="text-sm muted">{{ t('ideas.modal.text') }}</p>

      <div class="flex gap-1 border-b border-slate-200 dark:border-slate-700" role="tablist">
        <button
          v-for="tab in tabs"
          :key="tab"
          type="button"
          role="tab"
          :aria-selected="activeTab === tab"
          class="-mb-px inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-medium"
          :class="activeTab === tab ? 'border-primary text-primary' : 'border-transparent muted hover:text-slate-900 dark:hover:text-white'"
          @click="openTab(tab)"
        >
          {{ t(`ideas.tabs.${tab}`) }}
          <span v-if="tab === 'scene' && sceneCount" class="badge bg-primary/10 text-primary">{{ sceneCount }}</span>
        </button>
      </div>

      <!-- the brief -->
      <div v-show="activeTab === 'brief'" class="space-y-4 text-sm">
        <label class="block space-y-1">
          <span class="label">{{ t('ideas.fields.niche') }} *</span>
          <input v-model="form.niche" class="input" maxlength="200" :placeholder="t('ideas.fields.nichePlaceholder')">
        </label>
        <label class="block space-y-1">
          <span class="label">{{ t('ideas.fields.brand') }}</span>
          <textarea v-model="form.brand" class="input" rows="2" :placeholder="t('ideas.fields.brandPlaceholder')" />
        </label>
        <label class="block space-y-1">
          <span class="label">{{ t('ideas.fields.want') }}</span>
          <textarea v-model="form.want" class="input" rows="2" :placeholder="t('ideas.fields.wantPlaceholder')" />
        </label>
        <label class="block space-y-1">
          <span class="label">{{ t('ideas.fields.count') }}</span>
          <select v-model.number="form.count" class="input">
            <option :value="0">{{ t('ideas.fields.countAny') }}</option>
            <option v-for="n in IDEAS_MAX_COUNT" :key="n" :value="n">{{ n }}</option>
          </select>
          <span class="block text-xs muted">{{ t('ideas.fields.countHint', { max: IDEAS_MAX_COUNT }) }}</span>
        </label>
        <div class="grid gap-4 sm:grid-cols-2">
          <label class="block space-y-1">
            <span class="label">{{ t('ideas.fields.goal') }}</span>
            <input v-model="form.goal" class="input" :placeholder="t('ideas.fields.goalPlaceholder')">
          </label>
          <label class="block space-y-1">
            <span class="label">{{ t('ideas.fields.audience') }}</span>
            <input v-model="form.audience" class="input" :placeholder="t('ideas.fields.audiencePlaceholder')">
          </label>
        </div>
        <label class="block space-y-1">
          <span class="label">{{ t('ideas.fields.platform') }}</span>
          <input v-model="form.platform" class="input" list="ideas-platforms" :placeholder="t('ideas.fields.platformPlaceholder')">
          <datalist id="ideas-platforms">
            <option v-for="p in IDEAS_PLATFORMS" :key="p" :value="p" />
          </datalist>
        </label>
        <label class="block space-y-1">
          <span class="label">{{ t('ideas.fields.idea') }}</span>
          <textarea v-model="form.idea" class="input" rows="2" :placeholder="t('ideas.fields.ideaPlaceholder')" />
        </label>

        <div v-for="group in IDEAS_PICTURE_GROUPS" :key="group" class="space-y-2 rounded-card border border-slate-200 p-3 dark:border-slate-600">
          <div class="flex flex-wrap items-center gap-2">
            <div class="min-w-0 flex-1">
              <p class="font-medium">{{ t(`ideas.pictures.${group}`) }}</p>
              <p class="text-xs muted">{{ t(`ideas.pictures.${group}Hint`) }}</p>
            </div>
            <span class="text-xs muted">{{ t('ideas.pictures.count', { n: form[group].length, max: IDEAS_MAX_PICTURES }) }}</span>
          </div>
          <div class="flex flex-wrap items-center gap-2">
            <div v-for="(file, i) in form[group]" :key="file.id" class="relative h-16 w-16 overflow-hidden rounded-button bg-slate-100 dark:bg-slate-700">
              <img :src="chatFileThumb(file)" alt="" class="h-full w-full object-cover">
              <button
                type="button"
                class="absolute right-0.5 top-0.5 grid h-5 w-5 place-items-center rounded-full bg-slate-950/60 text-white hover:bg-slate-950/80"
                :title="t('ideas.pictures.remove')"
                :aria-label="t('ideas.pictures.remove')"
                @click="form[group].splice(i, 1)"
              >
                <AppIcon name="close" :size="12" />
              </button>
            </div>
            <template v-if="form[group].length < IDEAS_MAX_PICTURES">
              <button type="button" class="btn-secondary btn-sm" @click="pick(group, 'source')">
                <AppIcon name="upload" :size="14" />{{ t('ideas.pictures.upload') }}
              </button>
              <button type="button" class="btn-ghost btn-sm" @click="pick(group, 'chat')">
                <AppIcon name="image" :size="14" />{{ t('ideas.pictures.fromChat') }}
              </button>
            </template>
          </div>
          <label class="block space-y-1">
            <span class="text-xs muted">{{ t(`ideas.pictures.${group}Note`) }}</span>
            <input v-model="form[`${group}Note`]" class="input" :placeholder="t(`ideas.pictures.${group}NotePlaceholder`)">
          </label>
        </div>

        <label class="block space-y-1">
          <span class="label">{{ t('ideas.fields.requirements') }}</span>
          <textarea v-model="form.requirements" class="input" rows="2" :placeholder="t('ideas.fields.requirementsPlaceholder')" />
        </label>
        <label class="block space-y-1">
          <span class="label">{{ t('ideas.fields.language') }}</span>
          <select v-model="form.language" class="input">
            <option v-for="code in IDEAS_LANGUAGES" :key="code" :value="code">{{ t(`ideas.languages.${code}`) }}</option>
          </select>
          <span class="block text-xs muted">{{ t('ideas.fields.languageHint') }}</span>
        </label>
      </div>

      <!-- place and light -->
      <div v-show="activeTab === 'scene'" class="space-y-4 text-sm">
        <div class="flex flex-wrap items-center gap-2">
          <p class="min-w-0 flex-1 muted">{{ sceneCount ? t('ideas.scene.hintFilled') : t('ideas.scene.hint') }}</p>
          <button type="button" class="btn-secondary btn-sm" :disabled="rolling || !axes.length" @click="roll">
            <Spinner v-if="rolling" :size="14" /><AppIcon v-else name="dice" :size="14" />{{ t('ideas.scene.roll') }}
          </button>
          <button v-if="sceneCount" type="button" class="btn-ghost btn-sm" @click="form.scene = {}">{{ t('ideas.scene.clear') }}</button>
        </div>
        <p class="text-xs muted">{{ t('ideas.scene.rollHint') }}</p>
        <div v-if="sceneLoading" class="flex justify-center py-6"><Spinner /></div>
        <section v-for="axis in axes" :key="axis.id" class="space-y-1.5">
          <div class="flex flex-wrap items-baseline gap-x-2">
            <h3 class="font-semibold">{{ t(`ideas.scene.axes.${axis.id}.name`) }}</h3>
            <span v-if="axis.max > 1" class="text-xs muted">{{ t('ideas.scene.max', { n: axis.max }) }}</span>
          </div>
          <p class="text-xs muted">{{ t(`ideas.scene.axes.${axis.id}.hint`) }}</p>
          <div class="flex flex-wrap gap-1.5">
            <button
              v-for="item in axis.items"
              :key="item.id"
              type="button"
              class="rounded-full border px-2.5 py-0.5 text-xs"
              :class="picked(axis.id, item.id) ? 'border-primary bg-primary/10 text-primary' : 'border-slate-200 hover:border-slate-400 dark:border-slate-600'"
              :aria-pressed="picked(axis.id, item.id)"
              @click="form.scene = ideasSceneToggle(form.scene, axis.id, item.id, axis.max)"
            >
              {{ t(`ideas.scene.items.${item.id}`) }}
            </button>
          </div>
        </section>
      </div>

      <p v-if="error || estError" class="rounded-card bg-rose-50 px-3 py-2 text-sm text-rose-800 dark:bg-rose-500/10 dark:text-rose-200" role="alert">{{ error || estError }}</p>
    </div>

    <template #footer>
      <div class="w-full space-y-2 text-sm">
        <div class="space-y-0.5">
          <div class="flex flex-wrap items-center gap-2">
            <ToggleSwitch :model-value="researchOn" :label="t('ideas.options.research')" :disabled="Boolean(est?.research_refusal)" @update:model-value="form.research = $event" />
            <span v-if="est && !est.research_refusal" class="badge bg-slate-100 tabular-nums dark:bg-slate-700">{{ priceText(est.research_usd) }}</span>
          </div>
          <p v-if="est?.research_refusal" class="text-xs text-rose-700 dark:text-rose-300">{{ ideasReasonText(est.research_refusal, t, te) }}</p>
          <p v-else-if="est?.research_cached" class="text-xs muted">{{ t('ideas.options.researchCached', { date: formatDate(est.research_cached_at, locale) }) }}</p>
          <p v-else class="text-xs muted">{{ t('ideas.options.researchHint') }}</p>
        </div>
        <div class="space-y-0.5">
          <div class="flex flex-wrap items-center gap-2">
            <ToggleSwitch :model-value="drawOn" :label="t('ideas.options.drawFirst')" :disabled="Boolean(est?.frame_refusal)" @update:model-value="form.drawFirst = $event" />
            <span v-if="est && !est.frame_refusal" class="badge bg-slate-100 tabular-nums dark:bg-slate-700">{{ priceText(est.frame_usd) }}</span>
          </div>
          <p v-if="est?.frame_refusal" class="text-xs text-rose-700 dark:text-rose-300">{{ ideasReasonText(est.frame_refusal, t, te) }}</p>
          <p v-else class="text-xs muted">{{ t('ideas.options.drawFirstHint') }}</p>
        </div>
        <div v-if="form.product.length" class="space-y-0.5">
          <ToggleSwitch v-model="form.productToFrames" :label="t('ideas.options.productToFrames')" />
          <p class="text-xs muted">{{ t('ideas.options.productToFramesHint') }}</p>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <span class="muted">{{ t('ideas.options.ideas') }}</span>
          <span v-if="est && !est.ideas_refusal" class="badge bg-slate-100 tabular-nums dark:bg-slate-700">{{ priceText(est.ideas_usd) }}</span>
        </div>
        <p v-if="est?.ideas_refusal" class="text-xs text-rose-700 dark:text-rose-300">{{ ideasReasonText(est.ideas_refusal, t, te) }}</p>
      </div>
      <span v-if="!canSubmit" class="mr-auto text-xs muted">{{ t('ideas.modal.nicheFirst') }}</span>
      <button type="button" class="btn-secondary" @click="close">{{ t('common.cancel') }}</button>
      <PriceButton
        icon="sparkles"
        :label="t('ideas.modal.submit')"
        :usd="total"
        :disabled="!canSubmit || total === null || Boolean(est?.ideas_refusal)"
        :busy="sending"
        @click="submit"
      />
    </template>
  </ModalShell>

  <StudioSourcePicker
    :open="pickerOpen === 'source'"
    :title="t('ideas.pictures.pickTitle')"
    multiple
    :max="Math.max(1, IDEAS_MAX_PICTURES - (form[pickFor]?.length || 0))"
    @pick="onPick"
    @close="pickerOpen = ''"
  />
  <ChatPicturesPicker
    :open="pickerOpen === 'chat'"
    :room="room"
    :max="Math.max(1, IDEAS_MAX_PICTURES - (form[pickFor]?.length || 0))"
    @pick="onPick"
    @close="pickerOpen = ''"
  />
</template>

<script setup>
import { useDebounceFn } from '@vueuse/core'
import { formatDate, formatUsd } from '~/utils/format.js'
import { chatFileThumb } from '~/utils/chatView.js'
import {
  IDEAS_ESTIMATE_MS, IDEAS_LANGUAGES, IDEAS_MAX_COUNT, IDEAS_MAX_PICTURES, IDEAS_PICTURE_GROUPS, IDEAS_PLATFORMS,
  ideasAddPictures, ideasCanSubmit, ideasDraftKeep, ideasDraftTake, ideasEmptyForm, ideasErrorText, ideasPrefill,
  ideasReasonText, ideasSceneCount, ideasSceneToggle, ideasStartBody, ideasTotal,
} from '~/utils/ideasView.js'

const props = defineProps({
  room: { type: Object, required: true },
  text: { type: String, default: '' }, // what is typed in the composer: the niche when the window has none
})
const emit = defineEmits(['close'])
const { t, te, locale } = useI18n()
const api = useApi()

const chatId = computed(() => props.room.chatId)
const form = reactive(ideasPrefill(ideasDraftTake(chatId.value) || ideasEmptyForm(locale.value), props.text))
const tabs = ['brief', 'scene']
const activeTab = ref('brief')
const error = ref('')
const sending = ref(false)
let sent = false

const sceneCount = computed(() => ideasSceneCount(form.scene))
const canSubmit = computed(() => ideasCanSubmit(form))

// ── place and light ──

const axes = ref([])
const sceneLoading = ref(false)
const rolling = ref(false)

async function loadScene() {
  if (axes.value.length || sceneLoading.value) return
  sceneLoading.value = true
  try {
    axes.value = (await api.get('/api/ideas/scene'))?.axes || []
  } catch (err) {
    error.value = ideasErrorText(err, t, te)
  } finally {
    sceneLoading.value = false
  }
}

function openTab(tab) {
  activeTab.value = tab
  if (tab === 'scene') loadScene()
}

const picked = (axisId, itemId) => (form.scene[axisId] || []).includes(itemId)

async function roll() {
  rolling.value = true
  try {
    const res = await api.get('/api/ideas/scene', { roll: true })
    if (res?.axes?.length) axes.value = res.axes
    form.scene = res?.scene || {}
  } catch (err) {
    error.value = ideasErrorText(err, t, te)
  } finally {
    rolling.value = false
  }
}

// ── pictures ──

const pickFor = ref('product')
const pickerOpen = ref('')

function pick(group, where) {
  pickFor.value = group
  pickerOpen.value = where
}

function onPick(files) {
  pickerOpen.value = ''
  form[pickFor.value] = ideasAddPictures(form[pickFor.value], files, IDEAS_MAX_PICTURES)
}

// ── prices ──

const est = ref(null)
const estError = ref('')
let seq = 0
const imageSettings = computed(() => JSON.stringify(props.room.chat?.image_settings || {}))
const estimateKey = computed(() => JSON.stringify(ideasStartBody(form, chatId.value)) + imageSettings.value)

const fetchEstimate = useDebounceFn(async () => {
  const mine = ++seq
  try {
    const res = await api.post('/api/ideas/estimate', ideasStartBody(form, chatId.value))
    if (mine === seq) {
      est.value = res
      estError.value = ''
    }
  } catch (err) {
    if (mine === seq) {
      est.value = null
      estError.value = ideasErrorText(err, t, te)
    }
  }
}, IDEAS_ESTIMATE_MS)

watch(estimateKey, () => fetchEstimate(), { immediate: true })

const off = computed(() => ({ research: Boolean(est.value?.research_refusal), drawFirst: Boolean(est.value?.frame_refusal) }))
const researchOn = computed(() => form.research && !off.value.research)
const drawOn = computed(() => form.drawFirst && !off.value.drawFirst)
const total = computed(() => ideasTotal(est.value, form))
const priceText = (usd) => (usd ? formatUsd(usd, { approx: true }) : t('common.free'))

// ── send / close ──

async function submit() {
  if (!canSubmit.value || sending.value) return
  sending.value = true
  error.value = ''
  try {
    const res = await api.post('/api/ideas/sets', ideasStartBody(form, chatId.value, off.value))
    props.room.put(res?.message)
    sent = true
    emit('close')
  } catch (err) {
    error.value = ideasErrorText(err, t, te)
  } finally {
    sending.value = false
  }
}

function close() {
  emit('close')
}

onBeforeUnmount(() => {
  if (!sent) ideasDraftKeep(chatId.value, form)
})
</script>
