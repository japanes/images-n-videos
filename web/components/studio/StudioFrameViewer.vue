<template>
  <!--
    One frame up close: the big picture, finding objects, editing a part,
    versions, the frame's own settings and what was sent to the model.
  -->
  <ModalShell :open="Boolean(frame)" :title="title" size="full" @close="$emit('close')">
    <template #header>
      <div class="flex min-w-0 flex-1 items-center gap-2">
        <h2 class="truncate text-base font-semibold">{{ title }}</h2>
        <span v-if="frame?.is_pilot" class="badge bg-primary/10 text-primary">{{ t('studio.frame.pilot') }}</span>
        <span class="ml-auto flex items-center">
          <button
            type="button"
            class="btn-ghost p-1.5"
            :disabled="!prevId"
            :title="t('studio.viewer.prev')"
            :aria-label="t('studio.viewer.prev')"
            @click="$emit('open', prevId)"
          ><AppIcon name="chevron-left" :size="18" /></button>
          <button
            type="button"
            class="btn-ghost p-1.5"
            :disabled="!nextId"
            :title="t('studio.viewer.next')"
            :aria-label="t('studio.viewer.next')"
            @click="$emit('open', nextId)"
          ><AppIcon name="chevron-right" :size="18" /></button>
        </span>
      </div>
    </template>

    <div v-if="frame" class="grid gap-6 lg:grid-cols-[minmax(0,1fr)_400px]">
      <!-- The picture -->
      <div class="min-w-0 space-y-4">
        <div class="relative flex justify-center rounded-card bg-slate-100 p-2 dark:bg-slate-900">
          <StudioRegionPicker
            v-if="frame.file"
            v-model="region"
            :src="frame.file.url"
            :objects="objectItems"
            :disabled="busy"
          />
          <div
            v-else
            class="flex w-full max-w-md flex-col items-center justify-center gap-2 text-sm muted"
            :style="{ aspectRatio: studioAspectRatio(aspect) }"
          >
            <AppIcon name="image" :size="40" />{{ t('studio.viewer.noPicture') }}
          </div>
          <div v-if="busy" class="absolute inset-0 flex flex-col items-center justify-center gap-3 rounded-card bg-slate-900/55 text-white">
            <Spinner :size="28" />
            <span class="text-sm">{{ state === 'waiting' ? t('studio.frame.waiting') : t(`studio.statuses.${state}`) }}</span>
            <button type="button" class="btn-secondary btn-sm" :disabled="studio.isPending(`cancel:${frame.id}`)" @click="studio.cancelFrame(frame.id)">
              <AppIcon name="stop" :size="14" />{{ t('studio.frame.cancel') }}
            </button>
          </div>
        </div>

        <p v-if="frame.status === 'error'" class="flex items-start gap-1.5 text-sm text-rose-600 dark:text-rose-400">
          <AppIcon name="alert" :size="16" class="mt-0.5 shrink-0" />
          <span>
            {{ frameError.text }}
            <span v-if="frameError.detail" class="mt-0.5 block whitespace-pre-wrap break-words text-xs opacity-80">{{ frameError.detail }}</span>
          </span>
        </p>

        <template v-if="frame.file">
          <!-- Find objects -->
          <div class="space-y-2">
            <div class="flex flex-wrap gap-2">
              <input
                v-model="focus"
                type="text"
                class="input min-w-0 flex-1"
                :maxlength="STUDIO_LIMITS.focus"
                :placeholder="t('studio.viewer.focusPlaceholder')"
                :aria-label="t('studio.viewer.focus')"
                :disabled="busy"
              >
              <PriceButton
                variant="secondary"
                icon="search"
                :label="t('studio.viewer.findObjects')"
                :usd="objectsPrice.usd.value"
                :busy="studio.isPending(`objects:${frame.id}`)"
                :disabled="busy || objectsPrice.usd.value === null"
                @click="findObjects"
              />
            </div>
            <p class="muted text-xs">
              {{ objectItems.length ? t('studio.viewer.pickHint') : t('studio.viewer.drawHint') }}
            </p>
            <div v-if="region" class="flex items-center gap-2 text-sm">
              <span class="badge bg-fuchsia-100 text-fuchsia-800 dark:bg-fuchsia-500/15 dark:text-fuchsia-200">
                {{ regionLabel }}
              </span>
              <button type="button" class="btn-ghost btn-sm" @click="region = null">{{ t('studio.viewer.wholePicture') }}</button>
            </div>
          </div>

          <!-- Edit -->
          <div class="space-y-2">
            <label class="label" :for="`studio-edit-${frame.id}`">
              {{ region ? t('studio.viewer.editPart') : t('studio.viewer.editWhole') }}
            </label>
            <textarea
              :id="`studio-edit-${frame.id}`"
              v-model="editText"
              rows="2"
              class="input"
              :maxlength="STUDIO_LIMITS.edit"
              :placeholder="t('studio.viewer.editPlaceholder')"
              :disabled="busy"
            />
            <div class="flex justify-end">
              <PriceButton
                icon="wand"
                :label="t('studio.viewer.edit')"
                :usd="editUsd"
                :busy="studio.isPending(`draw:${frame.id}`)"
                :disabled="busy || !editText.trim() || editUsd === null"
                @click="edit"
              />
            </div>
          </div>
        </template>

        <!-- Versions -->
        <section v-if="frame.versions?.length" class="space-y-2">
          <h3 class="text-sm font-semibold">{{ t('studio.viewer.versions') }}</h3>
          <div class="flex gap-3 overflow-x-auto pb-1">
            <div v-for="v in versionsNewestFirst" :key="v.index" class="w-32 shrink-0 space-y-1 text-xs">
              <div
                class="aspect-square overflow-hidden rounded-button border-2 bg-slate-100 dark:bg-slate-900"
                :class="v.current ? 'border-primary' : 'border-transparent'"
              >
                <img v-if="v.file" :src="v.file.thumb_url || v.file.url" alt="" loading="lazy" class="h-full w-full object-cover">
                <span v-else class="flex h-full items-center justify-center muted">{{ t('studio.viewer.versionGone') }}</span>
              </div>
              <div class="truncate">{{ t(`studio.versionModes.${v.mode || 'full'}`) }} · {{ t(`studio.sources.${v.source || 'generated'}`) }}</div>
              <div class="muted">{{ formatDateTime(v.at, locale) }}<template v-if="v.cost_usd"> · {{ formatUsd(v.cost_usd) }}</template></div>
              <span v-if="v.current" class="badge bg-primary/10 text-primary">{{ t('studio.viewer.current') }}</span>
              <button
                v-else-if="v.file"
                type="button"
                class="btn-ghost btn-sm px-1"
                :disabled="busy || studio.isPending(`frame:${frame.id}`)"
                :title="t('studio.viewer.restoreHint')"
                @click="studio.restoreVersion(frame.id, v.index)"
              ><AppIcon name="reply" :size="14" />{{ t('studio.viewer.restore') }}</button>
            </div>
          </div>
        </section>
      </div>

      <!-- Settings of this frame -->
      <aside class="min-w-0 space-y-5">
        <section class="space-y-2">
          <label class="label" :for="`studio-brief-${frame.id}`">{{ t('studio.frame.brief') }}</label>
          <textarea
            :id="`studio-brief-${frame.id}`"
            v-model="brief"
            rows="4"
            class="input text-sm"
            :maxlength="STUDIO_LIMITS.brief"
            :placeholder="t('studio.frame.briefPlaceholder')"
            :disabled="busy"
            @blur="saveBrief"
          />
          <p v-if="drawBlocker" class="muted text-xs">{{ drawBlocker }}</p>
          <div class="flex flex-wrap gap-2">
            <PriceButton
              icon="sparkles"
              :label="frame.file ? t('studio.frame.redraw') : t('studio.frame.draw')"
              :usd="drawUsd"
              :busy="studio.isPending(`draw:${frame.id}`)"
              :disabled="busy || Boolean(drawError) || drawUsd === null"
              @click="draw"
            />
            <button type="button" class="btn-secondary" :disabled="busy" @click="picking = true">
              <AppIcon name="upload" :size="16" />{{ t('studio.viewer.ownPicture') }}
            </button>
          </div>
          <p v-if="eff && !eff.error" class="muted text-xs">
            {{ t('studio.viewer.madeWith', { model: eff.model_title || eff.model_id, size: eff.image_size }) }}
            <template v-if="eff.size_wanted && eff.size_wanted !== eff.image_size">
              · {{ t('studio.viewer.sizeFallback', { wanted: eff.size_wanted, size: eff.image_size }) }}
            </template>
          </p>
          <p v-else-if="eff?.error" class="text-xs text-rose-600 dark:text-rose-400">{{ studioReasonText(eff.error, t, te) }}</p>
        </section>

        <section class="space-y-3">
          <h3 class="text-sm font-semibold">{{ t('studio.viewer.ownSettings') }}</h3>
          <p class="muted text-xs">{{ t('studio.viewer.ownSettingsHint') }}</p>
          <div class="grid grid-cols-2 gap-2">
            <label class="col-span-2 space-y-1 text-xs">
              <span class="muted">{{ t('studio.settings.model') }}</span>
              <select class="input py-1.5 text-sm" :value="ov.model_id || ''" :disabled="busy" @change="setOverride('model_id', $event.target.value || undefined)">
                <option value="">{{ t('studio.viewer.asWork') }}</option>
                <option v-for="m in modelChoices" :key="m.id" :value="m.id">{{ m.title || m.id }}</option>
              </select>
            </label>
            <label class="space-y-1 text-xs">
              <span class="muted">{{ t('studio.settings.size') }}</span>
              <select class="input py-1.5 text-sm" :value="ov.image_size || ''" :disabled="busy" @change="setOverride('image_size', $event.target.value || undefined)">
                <option value="">{{ t('studio.viewer.asWork') }}</option>
                <option v-for="s in sizeChoices" :key="s" :value="s">{{ s }}</option>
              </select>
            </label>
            <label class="space-y-1 text-xs">
              <span class="muted">{{ t('studio.settings.textMode') }}</span>
              <select class="input py-1.5 text-sm" :value="ov.text_mode || ''" :disabled="busy" @change="setOverride('text_mode', $event.target.value || undefined)">
                <option value="">{{ t('studio.viewer.asWork') }}</option>
                <option v-for="m in STUDIO_TEXT_MODES" :key="m" :value="m">{{ t(`studio.textModes.${m}.name`) }}</option>
              </select>
            </label>
          </div>

          <ToggleSwitch
            :model-value="'references' in ov"
            :label="t('studio.viewer.ownReferences')"
            :disabled="busy"
            @update:model-value="setOverride('references', $event ? [] : undefined)"
          />
          <StudioPictureList
            v-if="'references' in ov"
            :ids="ov.references"
            :max="STUDIO_MAX_PICTURES"
            :disabled="busy"
            :picker-title="t('studio.settings.references')"
            @update="setOverride('references', $event)"
          />

          <div class="space-y-1">
            <span class="label">{{ t('studio.viewer.attachments') }}</span>
            <p class="muted text-xs">{{ t('studio.viewer.attachmentsHint') }}</p>
            <StudioPictureList
              :ids="ov.attachments || []"
              :max="STUDIO_MAX_PICTURES"
              :disabled="busy"
              :picker-title="t('studio.viewer.attachments')"
              @update="setOverride('attachments', $event.length ? $event : undefined)"
            />
          </div>

          <div class="space-y-1">
            <label class="label" :for="`studio-fb-${frame.id}`">{{ t('studio.viewer.feedback') }}</label>
            <textarea
              :id="`studio-fb-${frame.id}`"
              v-model="feedback"
              rows="2"
              class="input text-sm"
              :maxlength="STUDIO_LIMITS.feedback"
              :placeholder="t('studio.viewer.feedbackPlaceholder')"
              :disabled="busy"
              @blur="saveFeedback"
            />
          </div>
        </section>

        <section class="space-y-2">
          <h3 class="text-sm font-semibold">{{ t('studio.viewer.words') }}</h3>
          <p class="muted text-xs">{{ t(`studio.textModes.${eff?.text_mode || 'none'}.hint`) }}</p>
          <StudioTextBlocks
            :model-value="frame.text_blocks"
            :disabled="busy"
            @save="studio.patchFrame(frame.id, { text_blocks: $event })"
          />
        </section>

        <details v-if="frame.prompt_text || frame.attachments?.length" class="space-y-2">
          <summary class="cursor-pointer text-sm font-semibold">{{ t('studio.viewer.sent') }}</summary>
          <div v-if="frame.attachments?.length" class="mt-2 flex flex-wrap gap-2">
            <figure v-for="(a, i) in frame.attachments" :key="i" class="w-20 space-y-0.5 text-[11px]">
              <img v-if="a.thumb_url" :src="a.thumb_url" alt="" loading="lazy" class="aspect-square w-full rounded-button object-cover">
              <figcaption class="truncate" :title="a.label || ''">{{ roleText(a.role) }}</figcaption>
            </figure>
          </div>
          <pre v-if="frame.prompt_text" class="mt-2 max-h-72 overflow-auto whitespace-pre-wrap rounded-button bg-slate-100 p-3 text-xs dark:bg-slate-900">{{ frame.prompt_text }}</pre>
        </details>

        <p v-if="frame.cost_usd" class="muted text-xs">{{ t('studio.viewer.spent', { usd: formatUsd(frame.cost_usd) }) }}</p>
      </aside>
    </div>

    <StudioSourcePicker
      :open="picking"
      :title="t('studio.viewer.ownPicture')"
      @pick="takePicture"
      @close="picking = false"
    />
  </ModalShell>
</template>

<script setup>
import { formatDateTime, formatUsd } from '~/utils/format.js'
import {
  STUDIO_LIMITS, STUDIO_MAX_PICTURES, STUDIO_TEXT_MODES, studioAspectRatio, studioEstimateRequest,
  studioFrameBusy, studioFrameError, studioFrameState, studioModelChoices, studioOverridesWith, studioReasonText, studioSizesFor,
} from '~/utils/studioView.js'

const props = defineProps({
  studio: { type: Object, required: true },
  frameId: { type: Number, default: null },
})
defineEmits(['close', 'open'])
const { t, te, locale } = useI18n()
const models = useModels()
onMounted(() => { if (!models.loaded.value) models.load() })

const work = computed(() => props.studio.work.value || {})
const frames = computed(() => work.value.frames || [])
const index = computed(() => frames.value.findIndex((f) => f.id === props.frameId))
const frame = computed(() => (index.value >= 0 ? frames.value[index.value] : null))
const frameError = computed(() => studioFrameError(frame.value, t, te))
const prevId = computed(() => (index.value > 0 ? frames.value[index.value - 1].id : null))
const nextId = computed(() => (index.value >= 0 ? frames.value[index.value + 1]?.id || null : null))
const aspect = computed(() => work.value.aspect || '1:1')
const title = computed(() => (frame.value ? t('studio.frame.title', { n: index.value + 1 }) : ''))

const state = computed(() => studioFrameState(frame.value))
const busy = computed(() => studioFrameBusy(frame.value))
const eff = computed(() => frame.value?.effective || null)
const ov = computed(() => frame.value?.overrides || {})
const objectItems = computed(() => frame.value?.objects?.items || [])

const modelChoices = computed(() => studioModelChoices(models.items.value))
const sizeChoices = computed(() => {
  const id = ov.value.model_id || work.value.model_id || eff.value?.model_id
  const model = id ? models.find(id) : null
  return model ? studioSizesFor(model) : ['1K']
})

// ── text fields saved when they lose focus ──
const brief = ref('')
const feedback = ref('')
watch(() => [frame.value?.id, frame.value?.brief], () => { brief.value = frame.value?.brief || '' }, { immediate: true })
watch(() => [frame.value?.id, ov.value.feedback], () => { feedback.value = ov.value.feedback || '' }, { immediate: true })

async function saveBrief() {
  const text = brief.value.trim()
  if (!frame.value || text === (frame.value.brief || '').trim()) return true
  return Boolean(await props.studio.patchFrame(frame.value.id, { brief: text }))
}

function saveFeedback() {
  const text = feedback.value.trim()
  if (text === (ov.value.feedback || '')) return
  setOverride('feedback', text || undefined)
}

function setOverride(key, value) {
  if (!frame.value) return
  props.studio.patchFrame(frame.value.id, { overrides: studioOverridesWith(ov.value, key, value) })
}

// ── region, objects and edits ──
const region = ref(null)
const focus = ref('')
const editText = ref('')
watch(() => [frame.value?.id, frame.value?.file_id], () => { region.value = null })
watch(() => frame.value?.id, () => { editText.value = ''; focus.value = frame.value?.objects?.focus || '' }, { immediate: true })

const regionLabel = computed(() => {
  if (!region.value) return ''
  if (region.value.id) {
    const o = objectItems.value.find((x) => x.id === region.value.id)
    return o?.label || region.value.id
  }
  return t('studio.viewer.ownArea')
})

const objectsPrice = useStudioEstimate(() => (
  frame.value?.file && !busy.value ? studioEstimateRequest('find_objects', { frame: frame.value, focus: focus.value.trim() }) : null
))
const editPrice = useStudioEstimate(() => (
  frame.value?.file && !busy.value ? studioEstimateRequest('edit', { frame: frame.value, region: region.value ? 1 : null }) : null
))
const editUsd = computed(() => (editPrice.items.value[0]?.error ? null : editPrice.usd.value))
const drawPrice = useStudioEstimate(() => (frame.value && !busy.value ? studioEstimateRequest('frame', { frame: frame.value }) : null))
const drawError = computed(() => drawPrice.items.value[0]?.error || null)
const drawUsd = computed(() => (drawError.value ? null : drawPrice.usd.value))
const drawBlocker = computed(() => (drawError.value ? studioReasonText(drawError.value, t, te) : ''))

async function findObjects() {
  if (!frame.value) return
  const res = await props.studio.findObjects(frame.value.id, focus.value.trim())
  if (res) region.value = null
}

async function edit() {
  if (!frame.value || !editText.value.trim()) return
  let picked = region.value
  if (picked && !picked.id) picked = { label: '', box: picked.box }
  const res = await props.studio.editFrame(frame.value.id, editText.value.trim(), picked)
  if (res) { editText.value = ''; region.value = null }
}

async function draw() {
  if (!frame.value || !await saveBrief()) return
  await props.studio.startFrame(frame.value.id)
}

// ── own picture ──
const picking = ref(false)
async function takePicture(files, from) {
  picking.value = false
  const file = files?.[0]
  if (file?.id && frame.value) await props.studio.pickPicture(frame.value.id, file.id, from === 'upload' ? 'upload' : 'library')
}

// ── versions and what was sent ──
const versionsNewestFirst = computed(() => [...(frame.value?.versions || [])].reverse())
const roleText = (role) => (te(`studio.roles.${role}`) ? t(`studio.roles.${role}`) : role)
</script>
