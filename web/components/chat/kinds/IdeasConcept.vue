<template>
  <!--
    A set of shot ideas in the chat (module 05, kind 'ideas.concept'): the concept,
    what Google found about the niche (with its sources), and one card per frame
    with its prompt. A prompt can be changed (free), replaced by a new idea (paid)
    and drawn with the chat's picture settings (paid); the picture comes as its
    own message in the chat. `message.data` is the set as GET /api/ideas/sets/:id gives it.
  -->
  <div class="flex justify-start">
    <div class="w-full max-w-3xl space-y-3 rounded-card border border-slate-200 bg-white px-4 py-3 text-sm dark:border-slate-700 dark:bg-slate-900">
      <header class="flex items-start gap-2">
        <AppIcon name="sparkles" class="mt-0.5 text-primary" />
        <div class="min-w-0 flex-1">
          <p class="break-words font-semibold">{{ view.concept?.name || view.brief?.niche || message.text }}</p>
          <p v-if="view.concept?.name && view.brief?.niche" class="break-words text-xs muted">{{ view.brief.niche }}</p>
        </div>
      </header>

      <div v-if="state === 'researching' || state === 'writing'" class="flex flex-wrap items-center gap-2 muted">
        <Spinner :size="14" />
        <span class="min-w-0 flex-1">{{ state === 'researching' ? t('ideas.card.researching') : t('ideas.card.writing') }}</span>
        <button type="button" class="btn-ghost btn-sm px-1.5" :disabled="Boolean(busyKey)" @click="stop">
          <AppIcon name="stop" :size="14" />{{ t('ideas.card.stop') }}
        </button>
      </div>
      <IdeasErrorLine v-else-if="state === 'error'" :item="view" :spend-link="view.spend_link" />
      <p v-else-if="state === 'cancelled'" class="muted">{{ t('ideas.card.cancelled') }}</p>

      <p v-if="view.concept?.direction" class="whitespace-pre-wrap break-words">{{ view.concept.direction }}</p>

      <!-- what Google found about the niche -->
      <section v-if="research?.done" class="space-y-1.5 rounded-card bg-slate-50 p-3 dark:bg-slate-800/60">
        <div class="flex flex-wrap items-center gap-2">
          <AppIcon name="globe" :size="16" class="muted" />
          <span class="font-medium">{{ t('ideas.card.research') }}</span>
          <span v-if="research.cached && research.created_at" class="badge bg-slate-200/70 dark:bg-slate-700">
            {{ t('ideas.card.researchCached', { date: formatDate(research.created_at, locale) }) }}
          </span>
        </div>
        <template v-if="research.error_code">
          <p class="muted">{{ t('ideas.card.researchFailed') }}</p>
          <IdeasErrorLine compact :item="research" />
        </template>
        <template v-else>
          <template v-if="research.summary">
            <p class="whitespace-pre-wrap break-words text-xs">{{ research.summary }}</p>
            <p class="text-xs muted">{{ t('ideas.card.researchEnglish') }}</p>
          </template>
          <div v-if="sources.length" class="space-y-0.5">
            <p class="text-xs font-medium muted">{{ t('ideas.card.sources') }}</p>
            <ul class="space-y-0.5 text-xs">
              <li v-for="(s, i) in sources" :key="i" class="flex min-w-0 items-center gap-1">
                <AppIcon name="external" :size="12" class="shrink-0 muted" />
                <a :href="s.url" target="_blank" rel="noopener noreferrer" class="truncate text-primary underline-offset-2 hover:underline">
                  {{ s.title || ideasSourceHost(s.url) }}
                </a>
                <span v-if="s.title" class="shrink-0 muted">· {{ ideasSourceHost(s.url) }}</span>
              </li>
            </ul>
          </div>
        </template>
      </section>

      <IdeasErrorLine
        v-if="view.draw_error_code"
        compact
        :lead="t('ideas.card.drawFailed')"
        :item="{ error_code: view.draw_error_code, error: view.draw_error }"
        :spend-link="view.spend_link"
      />

      <!-- the frames -->
      <section v-if="cards.length" class="space-y-2">
        <h4 class="font-semibold">{{ t('ideas.card.frames') }}</h4>
        <article v-for="card in cards" :key="card.n" class="space-y-1.5 rounded-card border border-slate-200 p-3 dark:border-slate-700">
          <div class="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span class="font-medium">{{ t('ideas.card.frame', { n: card.n }) }}</span>
            <span v-if="card.title" class="min-w-0 break-words">· {{ card.title }}</span>
            <span v-if="card.edited" class="badge bg-amber-100 text-amber-900 dark:bg-amber-500/15 dark:text-amber-100">{{ t('ideas.card.edited') }}</span>
            <span v-if="card.message_id" class="badge bg-emerald-100 text-emerald-900 dark:bg-emerald-500/15 dark:text-emerald-100">{{ t('ideas.card.drawn') }}</span>
          </div>

          <template v-if="editing === card.n">
            <textarea v-model="draftPrompt" class="input" rows="5" :placeholder="t('ideas.card.promptPlaceholder')" />
            <div class="flex flex-wrap justify-end gap-2">
              <button type="button" class="btn-secondary btn-sm" @click="editing = null">{{ t('common.cancel') }}</button>
              <button type="button" class="btn-primary btn-sm" :disabled="!draftPrompt.trim() || Boolean(busyKey)" @click="save(card)">
                <Spinner v-if="busyKey === `save:${card.n}`" :size="14" />{{ t('common.save') }}
              </button>
            </div>
          </template>
          <template v-else>
            <p class="whitespace-pre-wrap break-words text-slate-700 dark:text-slate-300">{{ card.prompt }}</p>
            <div class="flex flex-wrap items-center gap-1.5">
              <PriceButton
                class="btn-sm"
                variant="secondary"
                icon="image"
                :label="t('ideas.card.draw')"
                :usd="framePrice"
                :disabled="!canAct || framePrice === null || !card.prompt"
                :busy="busyKey === `draw:${card.n}`"
                @click="draw([card.n])"
              />
              <button type="button" class="btn-ghost btn-sm px-1.5" :disabled="!canAct" @click="edit(card)">
                <AppIcon name="edit" :size="14" />{{ t('common.edit') }}
              </button>
              <PriceButton
                class="btn-sm"
                variant="ghost"
                icon="dice"
                :label="t('ideas.card.reroll')"
                :usd="rerollPrice"
                :disabled="!canAct || rerollPrice === null"
                :busy="busyKey === `reroll:${card.n}`"
                @click="reroll(card)"
              />
              <button v-if="card.message_id" type="button" class="btn-ghost btn-sm px-1.5" @click="show(card.message_id)">
                <AppIcon name="eye" :size="14" />{{ t('ideas.card.show') }}
              </button>
            </div>
          </template>
        </article>

        <p v-if="drawRefusal" class="text-xs text-rose-700 dark:text-rose-300">{{ ideasReasonText(drawRefusal, t, te) }}</p>
        <div v-if="drawable.length >= 2" class="flex flex-wrap items-center gap-2">
          <PriceButton
            icon="image"
            :label="t('ideas.card.drawAll')"
            :usd="framePrice"
            :disabled="!canAct || framePrice === null"
            :busy="busyKey === 'draw:all'"
            @click="draw('all')"
          />
          <span v-if="drawEst?.usd_all != null" class="min-w-0 flex-1 text-xs muted">
            {{ t('ideas.card.drawAllHint', { usd: formatUsd(drawEst.usd_all, { approx: true }) }) }}
          </span>
        </div>
      </section>

      <div class="flex flex-wrap items-center gap-x-1 gap-y-1 text-xs muted">
        <span v-if="view.model_id" class="px-1">{{ modelTitle(view.model_id) }}</span>
        <span v-if="view.cost_usd > 0" class="px-1">{{ formatUsd(view.cost_usd) }}</span>
        <time :datetime="message.created_at" class="px-1">{{ chatTime(message.created_at, locale) }}</time>
      </div>

      <!-- everything that went to the model, as it was sent -->
      <details class="text-xs">
        <summary class="cursor-pointer select-none muted">{{ t('ideas.card.sent') }}</summary>
        <dl class="mt-2 space-y-1.5">
          <div v-for="[field, value] in sentFields" :key="field">
            <dt class="muted">{{ t(`ideas.fields.${field}`) }}</dt>
            <dd class="whitespace-pre-wrap break-words">{{ value }}</dd>
          </div>
          <div>
            <dt class="muted">{{ t('ideas.fields.count') }}</dt>
            <dd>{{ view.brief?.count || t('ideas.fields.countAny') }}</dd>
          </div>
          <div v-if="view.brief?.language">
            <dt class="muted">{{ t('ideas.fields.language') }}</dt>
            <dd>{{ te(`ideas.languages.${view.brief.language}`) ? t(`ideas.languages.${view.brief.language}`) : view.brief.language }}</dd>
          </div>
          <div v-for="group in pictureGroups" :key="group.role">
            <dt class="muted">{{ t(`ideas.pictures.${group.role}`) }}</dt>
            <dd class="mt-1 flex flex-wrap gap-1.5">
              <img
                v-for="p in group.items"
                :key="p.file_id"
                :src="chatFileThumb(p.file)"
                alt=""
                loading="lazy"
                class="h-12 w-12 rounded-button bg-slate-100 object-cover dark:bg-slate-800"
              >
            </dd>
            <dd v-if="group.note" class="mt-1 whitespace-pre-wrap break-words">{{ group.note }}</dd>
          </div>
          <div>
            <dt class="muted">{{ t('ideas.tabs.scene') }}</dt>
            <dd v-if="sceneRows.length" class="space-y-0.5">
              <p v-for="row in sceneRows" :key="row.axis">
                <span class="muted">{{ t(`ideas.scene.axes.${row.axis}.name`) }}:</span>
                {{ row.items.map((id) => t(`ideas.scene.items.${id}`)).join(', ') }}
              </p>
            </dd>
            <dd v-else>{{ t('ideas.card.sceneEmpty') }}</dd>
          </div>
          <div>
            <dt class="muted">{{ t('ideas.card.researchOn') }}</dt>
            <dd>{{ view.research ? t('common.on') : t('common.off') }}</dd>
          </div>
          <div v-if="view.prompt">
            <dd class="font-mono muted">{{ view.prompt.code }} · v{{ view.prompt.version }}</dd>
          </div>
        </dl>
      </details>
    </div>
  </div>
</template>

<script setup>
import { formatDate, formatUsd } from '~/utils/format.js'
import { chatFileThumb, chatTime } from '~/utils/chatView.js'
import {
  ideasCardState, ideasDrawable, ideasErrorText, ideasReasonText, ideasSafeUrl, ideasSentFields, ideasSourceHost,
} from '~/utils/ideasView.js'

const props = defineProps({
  message: { type: Object, required: true },
  room: { type: Object, required: true },
})
const { t, te, locale } = useI18n()
const api = useApi()
const toast = useToast()
const { confirm } = useConfirm()
const modelTitle = inject('chatModelTitle', (id) => id)

const view = computed(() => props.message.data || {})
const base = computed(() => `/api/ideas/sets/${view.value.id}`)
const state = computed(() => ideasCardState(view.value))
const research = computed(() => view.value.research || null)
const sources = computed(() => (research.value?.sources || [])
  .map((s) => ({ title: String(s?.title || '').trim(), url: ideasSafeUrl(s?.url) }))
  .filter((s) => s.url))
const cards = computed(() => view.value.images || [])
const drawable = computed(() => ideasDrawable(view.value))
const sentFields = computed(() => ideasSentFields(view.value.brief))
const pictureGroups = computed(() => ['product', 'visual']
  .map((role) => ({
    role,
    items: (view.value.pictures || []).filter((p) => p.role === role),
    note: String(view.value.brief?.[`${role}_note`] || '').trim(),
  }))
  .filter((g) => g.items.length || g.note))
const sceneRows = computed(() => Object.entries(view.value.scene || {})
  .filter(([, items]) => items?.length)
  .map(([axis, items]) => ({ axis, items })))

const busyKey = ref('')
const canAct = computed(() => state.value === 'done' && !busyKey.value)

// ── prices (the chat's picture settings can change them) ──

const drawEst = ref(null)
const rerollPrice = ref(null)
const framePrice = computed(() => (drawEst.value && !drawEst.value.refusal ? drawEst.value.usd : null))
const drawRefusal = computed(() => drawEst.value?.refusal || '')
const priceKey = computed(() => (state.value === 'done' && cards.value.length
  ? `${view.value.id}|${view.value.updated_at}|${JSON.stringify(props.room.chat?.image_settings || {})}`
  : ''))

let seq = 0
async function loadPrices() {
  const mine = ++seq
  if (!priceKey.value) return
  const first = cards.value[0]?.n
  try {
    const [d, r] = await Promise.all([
      api.post(`${base.value}/draw/estimate`, { numbers: 'all' }),
      api.get(`${base.value}/images/${first}/reroll/estimate`),
    ])
    if (mine !== seq) return
    drawEst.value = d
    rerollPrice.value = typeof r?.usd === 'number' ? r.usd : null
  } catch {
    if (mine !== seq) return
    drawEst.value = null
    rerollPrice.value = null
  }
}
watch(priceKey, loadPrices, { immediate: true })

// ── actions ──

async function act(key, fn) {
  if (busyKey.value) return null
  busyKey.value = key
  try {
    return await fn()
  } catch (err) {
    toast.error(ideasErrorText(err, t, te))
    return null
  } finally {
    busyKey.value = ''
  }
}

const refresh = () => props.room.refreshMessage(props.message.id)

async function stop() {
  if (!await confirm({ message: t('ideas.card.stopAsk'), confirmLabel: t('ideas.card.stop'), tone: 'danger' })) return
  await act('cancel', async () => {
    await api.post(`${base.value}/cancel`)
    await refresh()
  })
}

const editing = ref(null)
const draftPrompt = ref('')

function edit(card) {
  editing.value = card.n
  draftPrompt.value = card.prompt || ''
}

async function save(card) {
  const prompt = draftPrompt.value.trim()
  if (!prompt) return
  await act(`save:${card.n}`, async () => {
    await api.patch(`${base.value}/images/${card.n}`, { prompt })
    editing.value = null
    await refresh()
  })
}

async function reroll(card) {
  if (card.edited && !await confirm({
    message: t('ideas.card.rerollAsk', { n: card.n }), confirmLabel: t('ideas.card.rerollYes'), tone: 'danger',
  })) return
  await act(`reroll:${card.n}`, async () => {
    await api.post(`${base.value}/images/${card.n}/reroll`)
    await refresh()
  })
}

async function draw(numbers) {
  const key = numbers === 'all' ? 'draw:all' : `draw:${numbers[0]}`
  await act(key, async () => {
    const res = await api.post(`${base.value}/draw`, { numbers })
    props.room.put(res?.message)
    await refresh()
    if (res?.message?.id) await show(res.message.id)
  })
}

async function show(messageId) {
  await props.room.loadUntil(messageId)
  await nextTick()
  document.getElementById(`chat-msg-${messageId}`)?.scrollIntoView({ block: 'center', behavior: 'smooth' })
}
</script>
