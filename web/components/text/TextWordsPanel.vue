<template>
  <!--
    «Words» tab: the blocks of words, then the steps that use them — put them on
    the picture, write them, a few variants of one line, make them sound human.
    Every paid step shows its price and what it will send.
  -->
  <div class="space-y-4 p-4 text-sm">
    <!-- the blocks -->
    <section class="space-y-3">
      <div class="flex items-center gap-2">
        <h3 class="flex-1 font-semibold">{{ t('text.words.title') }}</h3>
        <label class="flex items-center gap-1.5 text-xs">
          <span class="muted">{{ t('text.words.language') }}</span>
          <select :value="s.forms.language" class="input w-auto py-1 text-xs" @change="tool.setLanguage($event.target.value)">
            <option v-for="code in TEXT_LANGUAGES" :key="code" :value="code">{{ t(`text.languages.${code}`) }}</option>
          </select>
        </label>
      </div>
      <p v-if="!s.texts.length" class="text-xs muted">{{ t('text.words.empty') }}</p>
      <div
        v-for="block in s.texts"
        :key="block.id"
        class="space-y-2 rounded-card border border-slate-200 p-2.5 dark:border-slate-700"
      >
        <div class="flex flex-wrap items-center gap-2">
          <select :value="block.role" class="input w-auto py-1 text-xs" :aria-label="t('text.words.role')" @change="setBlock(block.id, { role: $event.target.value })">
            <option v-for="role in TEXT_ROLES" :key="role" :value="role">{{ t(`text.roles.${role}`) }}</option>
          </select>
          <select :value="block.size" class="input w-auto py-1 text-xs" :aria-label="t('text.words.size')" @change="setBlock(block.id, { size: $event.target.value })">
            <option v-for="size in TEXT_SIZES" :key="size" :value="size">{{ t(`text.sizes.${size}`) }}</option>
          </select>
          <label class="ml-auto flex items-center gap-1 text-xs" :title="t('text.words.lockedHint')">
            <input type="checkbox" :checked="block.locked" @change="setBlock(block.id, { locked: $event.target.checked })">
            {{ t('text.words.locked') }}
          </label>
          <button type="button" class="btn-ghost p-1" :title="t('text.words.remove')" :aria-label="t('text.words.remove')" @click="removeBlock(block.id)">
            <AppIcon name="trash" :size="14" />
          </button>
        </div>
        <textarea
          :value="block.text"
          class="input"
          rows="2"
          :maxlength="TEXT_MAX_TEXT"
          :placeholder="t(`text.words.placeholder.${block.role}`)"
          @input="setBlock(block.id, { text: $event.target.value })"
        />
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <button
          v-for="role in TEXT_ROLES"
          :key="role"
          type="button"
          class="btn-secondary btn-sm"
          :disabled="!textCanAddBlock(s.texts)"
          @click="addBlock(role)"
        >
          <AppIcon name="plus" :size="14" />{{ t(`text.roles.${role}`) }}
        </button>
        <span v-if="!textCanAddBlock(s.texts)" class="text-xs muted">{{ t('text.words.max', { n: TEXT_MAX_TEXTS }) }}</span>
      </div>
    </section>

    <!-- put the words on the picture -->
    <section class="space-y-2 rounded-card border border-slate-200 p-3 dark:border-slate-700">
      <h3 class="font-semibold">{{ t('text.place.title') }}</h3>
      <p class="text-xs muted">{{ t('text.place.hint') }}</p>
      <p v-if="unplaced.length" class="text-xs text-amber-800 dark:text-amber-200">
        {{ t('text.place.unplaced', { n: unplaced.length }, unplaced.length) }}
      </p>
      <ToggleSwitch v-model="s.forms.place.vision" :label="t('text.place.vision')" />
      <p class="pl-11 text-xs muted">{{ t('text.place.visionHint') }}</p>
      <p v-if="s.forms.place.vision && refusal('placement')" class="pl-11 text-xs text-rose-700 dark:text-rose-300">{{ refusal('placement') }}</p>
      <ToggleSwitch v-model="s.forms.place.replace" :label="t('text.place.replace')" />
      <p class="pl-11 text-xs muted">{{ t('text.place.replaceHint') }}</p>
      <div class="flex flex-wrap items-center gap-2 pt-1">
        <PriceButton
          :label="t('text.place.button')"
          icon="text"
          :usd="placePrice"
          :busy="Boolean(s.busy.place)"
          :disabled="!hasWords || placePrice === null"
          @click="tool.place()"
        />
        <button v-if="s.forms.place.vision" type="button" class="btn-ghost btn-sm" @click="$emit('preview', 'place')">
          <AppIcon name="eye" :size="14" />{{ t('text.preview.button') }}
        </button>
      </div>
      <p v-if="summary.length" class="text-xs muted">
        {{ t('text.place.result') }}
        <span v-for="(x, i) in summary" :key="x.source">{{ i ? ', ' : ' ' }}{{ t(`text.place.sources.${x.source}`, { n: x.n }, x.n) }}</span>
      </p>
      <TextErrorLine v-if="s.placement?.error" :item="s.placement.error" :lead="t('text.place.visionFailed')" compact />
    </section>

    <!-- write the words -->
    <section class="space-y-2 rounded-card border border-slate-200 p-3 dark:border-slate-700">
      <h3 class="font-semibold">{{ t('text.write.title') }}</h3>
      <p class="text-xs muted">{{ t('text.write.hint') }}</p>
      <ToggleSwitch v-model="s.forms.write.use_brief" :label="t('text.write.useBrief')" />
      <ToggleSwitch v-model="s.forms.write.use_tone" :label="t('text.write.useTone')" />
      <ToggleSwitch v-model="s.forms.write.use_neighbours" :label="t('text.write.useNeighbours')" />
      <label class="block">
        <span class="label">{{ t('text.write.maxChars') }}</span>
        <input v-model.number="s.forms.write.max_chars" type="number" min="0" :max="TEXT_MAX_TEXT" class="input w-32">
        <span class="mt-1 block text-xs muted">{{ t('text.write.maxCharsHint') }}</span>
      </label>
      <label class="block">
        <span class="label">{{ t('text.write.note') }}</span>
        <textarea v-model="s.forms.write.note" class="input" rows="2" :maxlength="TEXT_MAX_NOTE" :placeholder="t('text.write.notePlaceholder')" />
      </label>
      <p v-if="refusal('write')" class="text-xs text-rose-700 dark:text-rose-300">{{ refusal('write') }}</p>
      <div class="flex flex-wrap items-center gap-2">
        <PriceButton
          :label="t('text.write.button')"
          icon="sparkles"
          :usd="price('write')"
          :busy="Boolean(s.busy.write)"
          :disabled="!s.texts.length || price('write') === null"
          @click="tool.write()"
        />
        <button type="button" class="btn-ghost btn-sm" @click="$emit('preview', 'write')">
          <AppIcon name="eye" :size="14" />{{ t('text.preview.button') }}
        </button>
        <button v-if="s.undo?.what === 'write'" type="button" class="btn-ghost btn-sm" @click="tool.undo()">
          <AppIcon name="refresh" :size="14" />{{ t('text.write.undo') }}
        </button>
      </div>
      <p v-if="!s.texts.length" class="text-xs muted">{{ t('text.write.needBlocks') }}</p>
    </section>

    <!-- a few variants of one line -->
    <section class="space-y-2 rounded-card border border-slate-200 p-3 dark:border-slate-700">
      <h3 class="font-semibold">{{ t('text.variants.title') }}</h3>
      <p class="text-xs muted">{{ t('text.variants.hint') }}</p>
      <label class="block">
        <span class="label">{{ t('text.variants.block') }}</span>
        <select :value="s.forms.variants.blockId" class="input" @change="pickBlock($event.target.value)">
          <option value="">{{ t('text.variants.noBlock') }}</option>
          <option v-for="block in s.texts" :key="block.id" :value="block.id">{{ blockName(block) }}</option>
        </select>
      </label>
      <label class="block">
        <span class="label">{{ t('text.variants.note') }}</span>
        <textarea v-model="s.forms.variants.note" class="input" rows="2" :maxlength="TEXT_MAX_NOTE" :placeholder="t('text.variants.notePlaceholder')" />
      </label>
      <label class="block">
        <span class="label">{{ t('text.variants.count') }}</span>
        <select v-model.number="s.forms.variants.count" class="input w-24">
          <option v-for="n in TEXT_MAX_VARIANTS" :key="n" :value="n">{{ n }}</option>
        </select>
      </label>
      <ToggleSwitch v-model="s.forms.variants.use_system" :label="t('text.variants.useSystem')" />
      <ToggleSwitch v-model="s.forms.variants.use_rules" :label="t('text.variants.useRules')" />
      <ToggleSwitch v-model="s.forms.variants.use_language" :label="t('text.variants.useLanguage')" />
      <ToggleSwitch v-model="s.forms.variants.use_tone" :label="t('text.variants.useTone')" />
      <ToggleSwitch v-model="s.forms.variants.use_brief" :label="t('text.variants.useBrief')" />
      <label class="block">
        <span class="label">{{ t('text.write.maxChars') }}</span>
        <input v-model.number="s.forms.variants.max_chars" type="number" min="0" :max="TEXT_MAX_TEXT" class="input w-32">
      </label>
      <label class="block">
        <span class="label">{{ t('text.variants.feedback') }}</span>
        <textarea v-model="s.forms.variants.feedback" class="input" rows="2" :maxlength="TEXT_MAX_NOTE" :placeholder="t('text.variants.feedbackPlaceholder')" />
      </label>
      <p v-if="refusal('variants')" class="text-xs text-rose-700 dark:text-rose-300">{{ refusal('variants') }}</p>
      <div class="flex flex-wrap items-center gap-2">
        <PriceButton
          :label="t('text.variants.button')"
          icon="dice"
          :usd="price('variants')"
          :busy="Boolean(s.busy.variants)"
          :disabled="!textVariantsReady(s.forms) || price('variants') === null"
          @click="tool.variants(s.forms.variants.blockId)"
        />
        <button type="button" class="btn-ghost btn-sm" :disabled="!textVariantsReady(s.forms)" @click="$emit('preview', 'variants')">
          <AppIcon name="eye" :size="14" />{{ t('text.preview.button') }}
        </button>
      </div>
      <p v-if="!textVariantsReady(s.forms)" class="text-xs muted">{{ t('text.variants.needSomething') }}</p>
      <ul v-if="s.variants.items.length" class="space-y-1.5">
        <li v-for="(line, i) in s.variants.items" :key="i" class="flex items-start gap-2 rounded-card bg-slate-50 px-2.5 py-2 dark:bg-slate-900/60">
          <span class="min-w-0 flex-1 whitespace-pre-wrap break-words">{{ line }}</span>
          <button
            type="button"
            class="btn-secondary btn-sm shrink-0"
            :disabled="!variantTarget"
            :title="variantTarget ? '' : t('text.variants.pickBlock')"
            @click="putVariant(line)"
          >
            {{ t('text.variants.put') }}
          </button>
        </li>
      </ul>
      <TextErrorLine v-for="(err, i) in s.variants.errors" :key="`e${i}`" :item="err" compact />
    </section>

    <!-- make the words sound human -->
    <section class="space-y-2 rounded-card border border-slate-200 p-3 dark:border-slate-700">
      <h3 class="font-semibold">{{ t('text.humanize.title') }}</h3>
      <p class="text-xs muted">{{ t('text.humanize.hint') }}</p>
      <ToggleSwitch v-model="s.forms.humanize.use_language" :label="t('text.humanize.useLanguage')" />
      <p v-if="refusal('humanize')" class="text-xs text-rose-700 dark:text-rose-300">{{ refusal('humanize') }}</p>
      <div class="flex flex-wrap items-center gap-2">
        <PriceButton
          :label="t('text.humanize.button')"
          icon="wand"
          :usd="price('humanize')"
          :busy="Boolean(s.busy.humanize)"
          :disabled="!humanizeCount || price('humanize') === null"
          @click="humanize"
        />
        <button type="button" class="btn-ghost btn-sm" :disabled="!humanizeCount" @click="$emit('preview', 'humanize')">
          <AppIcon name="eye" :size="14" />{{ t('text.preview.button') }}
        </button>
        <button v-if="s.undo?.what === 'humanize'" type="button" class="btn-ghost btn-sm" @click="tool.undo()">
          <AppIcon name="refresh" :size="14" />{{ t('text.write.undo') }}
        </button>
      </div>
      <p v-if="!humanizeCount" class="text-xs muted">{{ t('text.humanize.nothing') }}</p>
    </section>
  </div>
</template>

<script setup>
import {
  TEXT_LANGUAGES, TEXT_MAX_NOTE, TEXT_MAX_TEXT, TEXT_MAX_TEXTS, TEXT_MAX_VARIANTS, TEXT_ROLES, TEXT_SIZES,
  textCanAddBlock, textHumanizeBody, textNewBlock, textPlacePrice, textPlaceSummary, textPrice, textPutVariant,
  textReasonText, textRemoveBlock, textUnplaced, textVariantsReady,
} from '~/utils/textView.js'

defineEmits(['preview'])
const tool = inject('textTool')
const s = tool.state
const { t, te } = useI18n()
const toast = useToast()

const price = (key) => textPrice(s.est?.[key])
const refusal = (key) => textReasonText(s.est?.[key]?.refusal, t, te)
const placePrice = computed(() => textPlacePrice(s.est, s.forms))
const hasWords = computed(() => s.texts.some((x) => String(x.text || '').trim()))
const unplaced = computed(() => textUnplaced(s.texts, s.layers))
const summary = computed(() => textPlaceSummary(s.placement))
const humanizeCount = computed(() => textHumanizeBody(s.forms, s.texts).text_ids.length)
const variantTarget = computed(() => s.texts.find((x) => x.id === s.variants.blockId) || null)

// ── blocks ──

function setBlock(id, patch) {
  tool.edit({ texts: s.texts.map((x) => (x.id === id ? { ...x, ...patch } : x)) })
}

function addBlock(role) {
  if (!textCanAddBlock(s.texts)) return
  tool.edit({ texts: [...s.texts, textNewBlock(s.texts, role)] })
}

function removeBlock(id) {
  tool.edit(textRemoveBlock(s.texts, s.layers, id))
  if (s.forms.variants.blockId === id) s.forms.variants.blockId = ''
}

function blockName(block) {
  const words = String(block.text || '').replace(/\s+/g, ' ').trim()
  const role = t(`text.roles.${block.role}`)
  return words ? `${role}: ${words.length > 40 ? `${words.slice(0, 39)}…` : words}` : role
}

// ── variants ──

/** Picking a block puts its line into the request, to be changed or kept. */
function pickBlock(id) {
  s.forms.variants.blockId = id
  const block = s.texts.find((x) => x.id === id)
  if (block && String(block.text || '').trim()) s.forms.variants.note = block.text
}

function putVariant(line) {
  if (!variantTarget.value) return
  tool.edit({ texts: textPutVariant(s.texts, variantTarget.value.id, line) })
  toast.success(t('text.variants.done'))
}

// ── humanize ──

async function humanize() {
  const res = await tool.humanize()
  if (!res) return
  if (res.replaced) toast.success(t('text.humanize.done', { n: res.replaced }, res.replaced))
  else toast.info(t('text.humanize.same'))
}
</script>
