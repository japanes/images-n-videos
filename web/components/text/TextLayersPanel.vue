<template>
  <!--
    «Layers» tab: the brand kit, ready layouts, the list of layers (the top one
    first) and the settings of the picked one. Nothing here is paid.
  -->
  <div class="space-y-4 p-4 text-sm">
    <!-- the brand kit and the fonts -->
    <section class="space-y-2">
      <label class="block">
        <span class="label">{{ t('text.kit.title') }}</span>
        <select :value="d?.kit_id || ''" class="input" @change="tool.setKit(Number($event.target.value) || null)">
          <option value="">{{ t('text.kit.none') }}</option>
          <option v-for="kit in d?.kits || []" :key="kit.id" :value="kit.id">{{ kit.name }}</option>
        </select>
        <span class="mt-1 block text-xs muted">{{ t('text.kit.hint') }}</span>
      </label>
      <label class="block">
        <span class="label">{{ t('text.fonts.default') }}</span>
        <select :value="fontValue(d?.options?.font)" class="input" @change="tool.setDefaultFont(fontOf($event.target.value))">
          <option value="">{{ t('text.fonts.fallback', { font: d?.fallback_font || TEXT_FALLBACK_FONT }) }}</option>
          <option v-for="f in fonts" :key="f.file_id" :value="`f${f.file_id}`" :disabled="!f.renderable">{{ fontLabel(f) }}</option>
        </select>
        <span class="mt-1 block text-xs muted">{{ t('text.fonts.defaultHint') }}</span>
      </label>
      <div class="flex flex-wrap items-center gap-2">
        <button type="button" class="btn-secondary btn-sm" :disabled="!d?.kit_id" @click="fontsOpen = true">
          <AppIcon name="globe" :size="14" />{{ t('text.fonts.google') }}
        </button>
        <span v-if="!d?.kit_id" class="text-xs muted">{{ t('text.fonts.needKit') }}</span>
      </div>
    </section>

    <!-- layouts -->
    <section class="space-y-2 rounded-card border border-slate-200 p-3 dark:border-slate-700">
      <h3 class="font-semibold">{{ t('text.layouts.title') }}</h3>
      <p class="text-xs muted">{{ t('text.layouts.hint') }}</p>
      <div class="flex flex-wrap gap-1.5">
        <span v-for="layout in s.layouts" :key="layout.id" class="inline-flex items-center">
          <button
            type="button"
            class="btn-secondary btn-sm"
            :class="!layout.builtin && 'rounded-r-none'"
            :disabled="Boolean(s.busy.layout)"
            @click="applyLayout(layout)"
          >
            {{ textLayoutTitle(layout, t, te) }}
          </button>
          <button
            v-if="!layout.builtin"
            type="button"
            class="btn-secondary btn-sm rounded-l-none border-l-0 px-1.5"
            :title="t('text.layouts.remove')"
            :aria-label="t('text.layouts.remove')"
            @click="removeLayout(layout)"
          >
            <AppIcon name="close" :size="12" />
          </button>
        </span>
      </div>
      <div class="flex flex-wrap items-center gap-2 pt-1">
        <input v-model="layoutTitle" class="input min-w-0 flex-1" :maxlength="TEXT_MAX_LAYOUT_TITLE" :placeholder="t('text.layouts.namePlaceholder')">
        <button
          type="button"
          class="btn-secondary btn-sm"
          :disabled="!layoutTitle.trim() || !s.layers.length || Boolean(s.busy.saveLayout)"
          @click="saveLayout"
        >
          {{ t('text.layouts.save') }}
        </button>
      </div>
    </section>

    <!-- the layers -->
    <section class="space-y-2">
      <div class="flex flex-wrap items-center gap-1.5">
        <h3 class="mr-auto font-semibold">{{ t('text.layers.title') }}</h3>
        <button type="button" class="btn-secondary btn-sm" :disabled="!canAdd" @click="addText">
          <AppIcon name="text" :size="14" />{{ t('text.layers.addText') }}
        </button>
        <button type="button" class="btn-secondary btn-sm" :disabled="!canAdd || !d?.logos?.length" :title="d?.logos?.length ? '' : t('text.layers.noLogos')" @click="addLogo">
          <AppIcon name="brand" :size="14" />{{ t('text.layers.logo') }}
        </button>
        <button type="button" class="btn-secondary btn-sm" :disabled="!canAdd" @click="addShape('rect')">{{ t('text.layers.rect') }}</button>
        <button type="button" class="btn-secondary btn-sm" :disabled="!canAdd" @click="addShape('ellipse')">{{ t('text.layers.ellipse') }}</button>
      </div>
      <p v-if="!s.layers.length" class="text-xs muted">{{ t('text.layers.empty') }}</p>
      <ul class="space-y-1">
        <li
          v-for="(layer, i) in topFirst"
          :key="layer.id"
          class="flex items-center gap-1 rounded-card border px-2 py-1"
          :class="layer.id === s.selectedId ? 'border-primary bg-primary/5' : 'border-slate-200 dark:border-slate-700'"
        >
          <button type="button" class="min-w-0 flex-1 truncate py-0.5 text-left" :class="layer.visible === false && 'line-through opacity-50'" @click="s.selectedId = layer.id">
            {{ textLayerLabel(layer, t) }}
          </button>
          <button type="button" class="btn-ghost p-1" :class="layer.visible === false && 'opacity-40'" :title="t(layer.visible === false ? 'text.layers.show' : 'text.layers.hide')" :aria-label="t(layer.visible === false ? 'text.layers.show' : 'text.layers.hide')" @click="patch(layer.id, { visible: layer.visible === false })">
            <AppIcon name="eye" :size="14" />
          </button>
          <button type="button" class="btn-ghost p-1" :disabled="i === 0" :title="t('text.layers.up')" :aria-label="t('text.layers.up')" @click="move(layer.id, 1)">
            <AppIcon name="chevron-down" :size="14" class="rotate-180" />
          </button>
          <button type="button" class="btn-ghost p-1" :disabled="i === topFirst.length - 1" :title="t('text.layers.down')" :aria-label="t('text.layers.down')" @click="move(layer.id, -1)">
            <AppIcon name="chevron-down" :size="14" />
          </button>
          <button type="button" class="btn-ghost p-1" :title="t('text.layers.remove')" :aria-label="t('text.layers.remove')" @click="remove(layer.id)">
            <AppIcon name="trash" :size="14" />
          </button>
        </li>
      </ul>
      <p v-if="!canAdd" class="text-xs muted">{{ t('text.layers.max', { n: TEXT_MAX_LAYERS }) }}</p>
    </section>

    <!-- the picked layer -->
    <section v-if="layer" class="space-y-3 rounded-card border border-slate-200 p-3 dark:border-slate-700">
      <h3 class="font-semibold">{{ t('text.props.title') }}</h3>

      <template v-if="layer.type === 'text'">
        <label class="block">
          <span class="label">{{ t('text.props.block') }}</span>
          <select :value="layer.block_id || ''" class="input" @change="setBlock($event.target.value)">
            <option value="">{{ t('text.props.ownWords') }}</option>
            <option v-for="block in s.texts" :key="block.id" :value="block.id">{{ blockName(block) }}</option>
          </select>
        </label>
        <label v-if="!layer.block_id" class="block">
          <span class="label">{{ t('text.props.words') }}</span>
          <textarea :value="layer.text" class="input" rows="2" :maxlength="TEXT_MAX_TEXT" @input="patch(layer.id, { text: $event.target.value })" />
        </label>
        <label class="block">
          <span class="label">{{ t('text.props.font') }}</span>
          <select :value="fontValue(layer.font)" class="input" @change="patch(layer.id, { font: fontOf($event.target.value) })">
            <option value="">{{ t('text.fonts.fallback', { font: d?.fallback_font || TEXT_FALLBACK_FONT }) }}</option>
            <option v-for="f in fonts" :key="f.file_id" :value="`f${f.file_id}`" :disabled="!f.renderable">{{ fontLabel(f) }}</option>
          </select>
        </label>
        <div class="grid grid-cols-2 gap-2">
          <label class="block">
            <span class="label">{{ t('text.props.size') }}</span>
            <select :value="layer.font_size ? 'exact' : layer.size" class="input" @change="setSize($event.target.value)">
              <option v-for="size in TEXT_SIZES" :key="size" :value="size">{{ t(`text.sizes.${size}`) }}</option>
              <option value="exact">{{ t('text.props.exact') }}</option>
            </select>
          </label>
          <label class="block">
            <span class="label">{{ t('text.props.vertical') }}</span>
            <select :value="layer.vertical" class="input" @change="patch(layer.id, { vertical: $event.target.value })">
              <option v-for="v in TEXT_VERTICALS" :key="v" :value="v">{{ t(`text.verticals.${v}`) }}</option>
            </select>
          </label>
        </div>
        <label v-if="layer.font_size" class="block">
          <span class="label">{{ t('text.props.exactSize', { p: Math.round(layer.font_size * 1000) / 10 }) }}</span>
          <input :value="layer.font_size" type="range" min="0.012" max="0.3" step="0.002" class="w-full" @change="patch(layer.id, { font_size: Number($event.target.value) })">
        </label>
        <div class="flex flex-wrap items-center gap-1">
          <span class="label mb-0 mr-1">{{ t('text.props.align') }}</span>
          <button
            v-for="a in TEXT_ALIGNS"
            :key="a"
            type="button"
            class="btn-sm"
            :class="layer.align === a ? 'btn-primary' : 'btn-secondary'"
            @click="patch(layer.id, { align: a })"
          >
            {{ t(`text.aligns.${a}`) }}
          </button>
        </div>
        <div class="space-y-1">
          <span class="label">{{ t('text.props.color') }}</span>
          <div class="flex flex-wrap items-center gap-1.5">
            <input :value="layer.color" type="color" class="h-8 w-10 cursor-pointer rounded border border-slate-300 dark:border-slate-600" @change="patch(layer.id, { color: $event.target.value.toUpperCase() })">
            <button
              v-for="c in swatches"
              :key="c.hex"
              type="button"
              class="h-6 w-6 rounded-full border border-slate-300 dark:border-slate-600"
              :class="c.hex === layer.color && 'ring-2 ring-primary ring-offset-1'"
              :style="{ background: c.hex }"
              :title="c.label || c.hex"
              :aria-label="c.label || c.hex"
              @click="patch(layer.id, { color: c.hex })"
            />
          </div>
        </div>
        <div class="grid grid-cols-2 gap-2">
          <ToggleSwitch :model-value="layer.bold" :label="t('text.props.bold')" @update:model-value="patch(layer.id, { bold: $event })" />
          <ToggleSwitch :model-value="layer.uppercase" :label="t('text.props.uppercase')" @update:model-value="patch(layer.id, { uppercase: $event })" />
          <ToggleSwitch :model-value="layer.scrim" :label="t('text.props.scrim')" @update:model-value="patch(layer.id, { scrim: $event })" />
          <ToggleSwitch :model-value="layer.shadow" :label="t('text.props.shadow')" @update:model-value="patch(layer.id, { shadow: $event })" />
        </div>
        <p class="text-xs muted">{{ t('text.props.scrimHint') }}</p>
        <label class="block">
          <span class="label">{{ t('text.props.lineHeight', { v: Number(layer.line_height || 1.28).toFixed(2) }) }}</span>
          <input :value="layer.line_height" type="range" min="0.8" max="2.5" step="0.02" class="w-full" @change="patch(layer.id, { line_height: Number($event.target.value) })">
        </label>
      </template>

      <template v-else-if="layer.type === 'logo'">
        <label class="block">
          <span class="label">{{ t('text.props.logo') }}</span>
          <select :value="layer.file_id || ''" class="input" @change="patch(layer.id, { file_id: Number($event.target.value) || null })">
            <option value="">{{ t('text.props.firstLogo') }}</option>
            <option v-for="logo in d?.logos || []" :key="logo.file_id" :value="logo.file_id">{{ logo.name || `#${logo.file_id}` }}</option>
          </select>
        </label>
      </template>

      <template v-else>
        <label class="block">
          <span class="label">{{ t('text.props.shape') }}</span>
          <select :value="layer.shape" class="input" @change="patch(layer.id, { shape: $event.target.value })">
            <option v-for="shape in TEXT_SHAPES" :key="shape" :value="shape">{{ t(`text.layers.${shape}`) }}</option>
          </select>
        </label>
        <div class="space-y-1">
          <span class="label">{{ t('text.props.fill') }}</span>
          <div class="flex flex-wrap items-center gap-1.5">
            <input :value="layer.fill" type="color" class="h-8 w-10 cursor-pointer rounded border border-slate-300 dark:border-slate-600" @change="patch(layer.id, { fill: $event.target.value.toUpperCase() })">
            <button
              v-for="c in swatches"
              :key="c.hex"
              type="button"
              class="h-6 w-6 rounded-full border border-slate-300 dark:border-slate-600"
              :class="c.hex === layer.fill && 'ring-2 ring-primary ring-offset-1'"
              :style="{ background: c.hex }"
              :title="c.label || c.hex"
              :aria-label="c.label || c.hex"
              @click="patch(layer.id, { fill: c.hex })"
            />
          </div>
        </div>
        <label v-if="layer.shape === 'rect'" class="block">
          <span class="label">{{ t('text.props.radius') }}</span>
          <input :value="layer.radius" type="range" min="0" max="0.5" step="0.01" class="w-full" @change="patch(layer.id, { radius: Number($event.target.value) })">
        </label>
      </template>

      <label class="block">
        <span class="label">{{ t('text.props.opacity', { p: Math.round((layer.opacity ?? 1) * 100) }) }}</span>
        <input :value="layer.opacity ?? 1" type="range" min="0" max="1" step="0.05" class="w-full" @change="patch(layer.id, { opacity: Number($event.target.value) })">
      </label>
    </section>
    <p v-else-if="s.layers.length" class="text-xs muted">{{ t('text.props.pick') }}</p>

    <TextGoogleFontsModal v-if="fontsOpen" :kit-id="d?.kit_id" :cyrillic-first="s.forms.language !== 'en'" @close="fontsOpen = false" @added="onFontAdded" />
  </div>
</template>

<script setup>
import {
  TEXT_ALIGNS, TEXT_FALLBACK_FONT, TEXT_MAX_LAYERS, TEXT_MAX_LAYOUT_TITLE, TEXT_MAX_TEXT, TEXT_SHAPES, TEXT_SIZES,
  TEXT_VERTICALS, textCanAddLayer, textFontShare, textLayerLabel, textLayoutTitle, textMoveLayer, textNewLogoLayer,
  textNewShapeLayer, textNewTextLayer, textPatchLayer, textRemoveLayer, textUnplaced,
} from '~/utils/textView.js'

const tool = inject('textTool')
const s = tool.state
const { t, te } = useI18n()
const { confirm } = useConfirm()
const toast = useToast()

const d = computed(() => s.design)
const fonts = computed(() => d.value?.fonts || [])
const layer = computed(() => s.layers.find((l) => l.id === s.selectedId) || null)
const topFirst = computed(() => [...s.layers].reverse())
const canAdd = computed(() => textCanAddLayer(s.layers))
const swatches = computed(() => {
  const base = [{ hex: '#FFFFFF', label: '' }, { hex: '#111111', label: '' }]
  const kit = (d.value?.colors || []).filter((c) => c?.hex)
  const seen = new Set()
  return [...kit, ...base].filter((c) => (seen.has(c.hex) ? false : seen.add(c.hex)))
})

// ── fonts: `f<file_id>` in the selects, '' for the fallback ──

function fontValue(font) {
  return font?.file_id ? `f${font.file_id}` : ''
}

function fontOf(value) {
  const id = Number(String(value || '').slice(1)) || null
  const f = id ? fonts.value.find((x) => x.file_id === id) : null
  return f ? { file_id: f.file_id, family: f.family } : null
}

function fontLabel(f) {
  const name = f.name || f.family
  return f.renderable ? name : `${name} — ${t('text.fonts.broken')}`
}

const fontsOpen = ref(false)
async function onFontAdded() {
  await tool.reload()
}

// ── layers ──

const patch = (id, values) => tool.edit({ layers: textPatchLayer(s.layers, id, values) })
const move = (id, dir) => tool.edit({ layers: textMoveLayer(s.layers, id, dir) })

function add(newLayer) {
  tool.edit({ layers: [...s.layers, newLayer] })
  s.selectedId = newLayer.id
}

/** A new text layer shows the first block not on the picture yet. */
function addText() {
  const block = textUnplaced(s.texts, s.layers)[0] || null
  add(textNewTextLayer(s.layers, block, d.value?.options?.font || null))
}

const addLogo = () => add(textNewLogoLayer(s.layers, null))
const addShape = (shape) => add(textNewShapeLayer(s.layers, shape))

function remove(id) {
  tool.edit({ layers: textRemoveLayer(s.layers, id) })
  if (s.selectedId === id) s.selectedId = ''
}

function setBlock(blockId) {
  const block = s.texts.find((x) => x.id === blockId)
  patch(layer.value.id, block ? { block_id: block.id, text: block.text, role: block.role } : { block_id: null })
}

function setSize(value) {
  if (value === 'exact') patch(layer.value.id, { font_size: Math.round(textFontShare(layer.value) * 1000) / 1000 })
  else patch(layer.value.id, { size: value, font_size: null })
}

function blockName(block) {
  const words = String(block.text || '').replace(/\s+/g, ' ').trim()
  const role = t(`text.roles.${block.role}`)
  return words ? `${role}: ${words.length > 40 ? `${words.slice(0, 39)}…` : words}` : role
}

// ── layouts ──

const layoutTitle = ref('')

async function applyLayout(layout) {
  if (s.layers.length) {
    const ok = await confirm({ message: t('text.layouts.replaceAsk'), confirmLabel: t('text.layouts.apply') })
    if (!ok) return
  }
  await tool.applyLayout(layout.id)
}

async function saveLayout() {
  const title = layoutTitle.value.trim()
  if (!title) return
  if (await tool.saveLayout(title)) {
    layoutTitle.value = ''
    toast.success(t('text.layouts.saved'))
  }
}

async function removeLayout(layout) {
  const ok = await confirm({
    message: t('text.layouts.removeAsk', { title: textLayoutTitle(layout, t, te) }),
    confirmLabel: t('text.layouts.remove'),
    tone: 'danger',
  })
  if (ok) await tool.deleteLayout(layout.id)
}
</script>
