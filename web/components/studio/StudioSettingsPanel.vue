<template>
  <!-- Settings of the whole work, for the side panel of the chat. Each field saves on its own. -->
  <div v-if="work" class="space-y-6 text-sm">
    <!-- Basics -->
    <section class="space-y-3">
      <label class="block space-y-1">
        <span class="label">{{ t('studio.settings.title') }}</span>
        <input v-model="title" type="text" class="input" :maxlength="STUDIO_LIMITS.title" @blur="saveTitle" @keydown.enter="$event.target.blur()">
      </label>

      <label class="block space-y-1">
        <span class="label">{{ t('studio.settings.kit') }}</span>
        <select class="input" :value="work.kit_id || ''" :disabled="saving" @change="setKit($event.target.value)">
          <option value="">{{ t('studio.settings.noKit') }}</option>
          <option v-for="k in kits" :key="k.id" :value="k.id">{{ k.name }}</option>
        </select>
      </label>
      <div v-if="work.kit_changed === true" class="flex flex-wrap items-center gap-2 rounded-card bg-amber-50 px-3 py-2 text-amber-900 dark:bg-amber-500/10 dark:text-amber-100">
        <span class="min-w-0 flex-1 text-xs">{{ t('studio.settings.kitChanged') }}</span>
        <button type="button" class="btn-secondary btn-sm" :disabled="studio.isPending('brand')" @click="studio.refreshBrand()">
          <AppIcon name="refresh" :size="14" />{{ t('studio.settings.kitRefresh') }}
        </button>
      </div>

      <label class="block space-y-1">
        <span class="label">{{ t('studio.settings.model') }}</span>
        <select class="input" :value="work.model_id || ''" :disabled="saving" @change="studio.patchWork({ model_id: $event.target.value || null })">
          <option value="">{{ t('studio.settings.modelDefault', { name: defaultModelTitle }) }}</option>
          <option v-for="m in modelChoices" :key="m.id" :value="m.id">{{ m.title || m.id }}</option>
        </select>
      </label>

      <div class="grid grid-cols-3 gap-2">
        <label class="block space-y-1">
          <span class="label">{{ t('studio.settings.aspect') }}</span>
          <select class="input" :value="work.aspect" :disabled="saving" @change="studio.patchWork({ aspect: $event.target.value })">
            <option v-for="a in STUDIO_ASPECTS" :key="a" :value="a">{{ a }}</option>
          </select>
        </label>
        <label class="block space-y-1">
          <span class="label">{{ t('studio.settings.size') }}</span>
          <select class="input" :value="work.image_size" :disabled="saving" @change="studio.patchWork({ image_size: $event.target.value })">
            <option v-for="s in sizeChoices" :key="s" :value="s">{{ s }}</option>
          </select>
        </label>
        <label class="block space-y-1">
          <span class="label">{{ t('studio.settings.frames') }}</span>
          <select class="input" :value="work.frame_count" :disabled="saving" @change="setCount(Number($event.target.value))">
            <option v-for="n in STUDIO_MAX_FRAMES" :key="n" :value="n">{{ n }}</option>
          </select>
        </label>
      </div>
      <p v-if="!sizeChoices.includes(work.image_size)" class="muted text-xs">
        {{ t('studio.settings.sizeFallback', { size: work.image_size }) }}
      </p>

      <ToggleSwitch
        :model-value="Boolean(s.series)"
        :label="t('studio.settings.series')"
        :disabled="saving || (!s.series && work.frame_count < 2)"
        @update:model-value="studio.patchSettings({ series: $event })"
      />
      <p class="muted text-xs">{{ t('studio.settings.seriesHint') }}</p>

      <label class="block space-y-1">
        <span class="label">{{ t('studio.settings.ideasBrief') }}</span>
        <textarea
          v-model="ideasBrief"
          rows="3"
          class="input"
          :maxlength="STUDIO_LIMITS.brief"
          :placeholder="t('studio.settings.ideasBriefHint')"
          @blur="saveText('ideas_brief', ideasBrief)"
        />
      </label>
    </section>

    <!-- Pictures that go with every frame -->
    <section class="space-y-3">
      <h3 class="font-semibold">{{ t('studio.settings.references') }}</h3>
      <p class="muted text-xs">{{ t('studio.settings.referencesHint') }}</p>
      <StudioPictureList
        :ids="s.references || []"
        :max="STUDIO_MAX_PICTURES"
        :disabled="saving"
        :picker-title="t('studio.settings.references')"
        @update="studio.patchSettings({ references: $event })"
      />
      <ToggleSwitch
        v-if="work.kit_id"
        :model-value="s.kit_references !== false"
        :label="t('studio.settings.kitReferences')"
        :disabled="saving"
        @update:model-value="studio.patchSettings({ kit_references: $event })"
      />

      <div class="space-y-1">
        <span class="label">{{ t('studio.settings.subjects') }}</span>
        <p v-if="!subjects.length" class="muted text-xs">{{ t('studio.settings.noSubjects') }}</p>
        <div v-else class="flex flex-wrap gap-1.5">
          <button
            v-for="sub in subjects"
            :key="sub.id"
            type="button"
            class="inline-flex items-center gap-1.5 rounded-full border py-0.5 pl-0.5 pr-2.5 text-xs"
            :class="pickedSubjects.includes(sub.id) ? 'border-primary bg-primary/10 text-primary' : 'border-slate-200 dark:border-slate-600'"
            :aria-pressed="pickedSubjects.includes(sub.id)"
            :disabled="saving"
            @click="toggleSubject(sub.id)"
          >
            <img v-if="sub.cover" :src="sub.cover.thumb_url || sub.cover.url" alt="" class="h-6 w-6 rounded-full object-cover">
            <AppIcon v-else name="user" :size="14" class="ml-1" />
            {{ sub.name }}
          </button>
        </div>
      </div>
    </section>

    <!-- Look -->
    <section class="space-y-3">
      <h3 class="font-semibold">{{ t('studio.settings.look') }}</h3>
      <label class="block space-y-1">
        <span class="label">{{ t('studio.settings.photoStyle') }}</span>
        <select class="input" :value="s.photo_style ?? ''" :disabled="saving" @change="setPhotoStyle($event.target.value)">
          <option value="">{{ t('studio.settings.plainPhoto') }}</option>
          <option v-for="p in photoStyles" :key="p.id" :value="p.id">{{ p.title }}</option>
        </select>
      </label>

      <div class="space-y-1">
        <span class="label">{{ t('studio.settings.style') }}</span>
        <div class="flex gap-1">
          <button
            v-for="k in ['none', 'library', 'words']"
            :key="k"
            type="button"
            class="btn-sm"
            :class="styleKind === k ? 'btn-primary' : 'btn-secondary'"
            :disabled="saving"
            @click="setStyleKind(k)"
          >{{ t(`studio.settings.styleKinds.${k}`) }}</button>
        </div>
        <select
          v-if="styleKind === 'library'"
          class="input mt-2"
          :value="styleValue?.kind === 'library' ? styleValue.id : ''"
          :disabled="saving"
          @change="setLibraryStyle($event.target.value)"
        >
          <option value="" disabled>{{ t('studio.settings.stylePick') }}</option>
          <option v-for="st in styles" :key="st.id" :value="st.id">{{ st.title }}</option>
        </select>
        <textarea
          v-if="styleKind === 'words'"
          v-model="styleWords"
          rows="3"
          class="input mt-2"
          :maxlength="STUDIO_LIMITS.style"
          :placeholder="t('studio.settings.styleWords')"
          @blur="saveStyleWords"
        />
        <ToggleSwitch
          v-if="styleValue?.kind === 'library'"
          class="mt-2"
          :model-value="Boolean(s.style_sample)"
          :label="t('studio.settings.styleSample')"
          :disabled="saving"
          @update:model-value="studio.patchSettings({ style_sample: $event })"
        />
      </div>
    </section>

    <!-- Words on the picture -->
    <section class="space-y-2">
      <h3 class="font-semibold">{{ t('studio.settings.textMode') }}</h3>
      <label v-for="m in STUDIO_TEXT_MODES" :key="m" class="flex cursor-pointer items-start gap-2">
        <input type="radio" class="mt-1" name="studio-text-mode" :value="m" :checked="s.text_mode === m" :disabled="saving" @change="studio.patchSettings({ text_mode: m })">
        <span>
          <span class="block">{{ t(`studio.textModes.${m}.name`) }}</span>
          <span class="muted block text-xs">{{ t(`studio.textModes.${m}.hint`) }}</span>
        </span>
      </label>
    </section>

    <!-- What to change next time -->
    <section class="space-y-1">
      <label class="label" for="studio-work-feedback">{{ t('studio.settings.feedback') }}</label>
      <textarea
        id="studio-work-feedback"
        v-model="feedback"
        rows="2"
        class="input"
        :maxlength="STUDIO_LIMITS.feedback"
        :placeholder="t('studio.settings.feedbackHint')"
        @blur="saveText('feedback', feedback)"
      />
    </section>

    <!-- Prompt blocks -->
    <section class="space-y-2">
      <h3 class="font-semibold">{{ t('studio.settings.blocks') }}</h3>
      <p class="muted text-xs">{{ t('studio.settings.blocksHint') }}</p>
      <StudioBlockToggles
        v-if="firstFrame?.blocks"
        :blocks="firstFrame.blocks"
        :disabled="saving"
        @change="studio.patchSettings({ blocks: $event })"
      />
      <p v-else-if="firstFrame?.effective?.error" class="text-xs text-rose-600 dark:text-rose-400">
        {{ studioReasonText(firstFrame.effective.error, t, te) }}
      </p>
    </section>
  </div>
</template>

<script setup>
import {
  STUDIO_ASPECTS, STUDIO_LIMITS, STUDIO_MAX_FRAMES, STUDIO_MAX_PICTURES, STUDIO_TEXT_MODES, studioModelChoices,
  studioReasonText, studioSizesFor, studioStyleSetting, studioStyleValue, studioTogglePicked,
} from '~/utils/studioView.js'

const props = defineProps({
  studio: { type: Object, required: true },
})
const { t, te } = useI18n()
const api = useApi()
const { confirm } = useConfirm()
const models = useModels()

const work = computed(() => props.studio.work.value)
const s = computed(() => work.value?.settings || {})
const firstFrame = computed(() => work.value?.frames?.[0] || null)
const saving = computed(() => props.studio.isPending('work'))

// ── lists for the selects (loaded once) ──
const kits = ref([])
const subjects = ref([])
const styles = ref([])
const photoStyles = ref([])
const quietly = async (fn, fallback) => { try { return await fn() } catch { return fallback } }

onMounted(async () => {
  if (!models.loaded.value) models.load()
  const [k, sub, st, ph] = await Promise.all([
    quietly(() => api.get('/api/brand/kits'), {}),
    quietly(() => api.get('/api/brand/subjects', { scope: 'library' }), {}),
    quietly(() => api.get('/api/library/styles', { kind: 'style', tab: 'all', limit: 200 }), {}),
    quietly(() => api.get('/api/library/styles', { kind: 'photo_style', tab: 'all', limit: 200 }), {}),
  ])
  kits.value = k.items || []
  subjects.value = sub.items || []
  styles.value = st.items || []
  photoStyles.value = ph.items || []
})

// ── model and size ──
const modelChoices = computed(() => studioModelChoices(models.items.value))
const defaultModel = computed(() => modelChoices.value.find((m) => m.is_default) || null)
const defaultModelTitle = computed(() => defaultModel.value?.title || defaultModel.value?.id || '—')
const currentModel = computed(() => (work.value?.model_id ? models.find(work.value.model_id) : defaultModel.value))
const sizeChoices = computed(() => studioSizesFor(currentModel.value))

// ── text fields saved when they lose focus ──
const title = ref('')
const ideasBrief = ref('')
const feedback = ref('')
const styleWords = ref('')
watch(() => work.value?.title, (v) => { title.value = v || '' }, { immediate: true })
watch(() => s.value.ideas_brief, (v) => { ideasBrief.value = v || '' }, { immediate: true })
watch(() => s.value.feedback, (v) => { feedback.value = v || '' }, { immediate: true })

function saveTitle() {
  const text = title.value.trim()
  if (text && text !== work.value.title) props.studio.patchWork({ title: text })
  else title.value = work.value.title || ''
}

function saveText(key, value) {
  const text = String(value || '').trim()
  if (text !== (s.value[key] || '')) props.studio.patchSettings({ [key]: text })
}

// ── brand kit and frame count ──
function setKit(value) {
  props.studio.patchWork({ kit_id: value ? Number(value) : null })
}

async function setCount(count) {
  const frames = work.value.frames || []
  const dropped = frames.slice(count)
  if (dropped.some((f) => f.file_id || (f.brief || '').trim())) {
    const ok = await confirm({
      message: t('studio.settings.framesDropAsk', { n: dropped.length }),
      confirmLabel: t('common.delete'),
      tone: 'danger',
    })
    if (!ok) return
  }
  props.studio.patchWork({ frame_count: count })
}

// ── subjects, photo style, style ──
const pickedSubjects = computed(() => s.value.subjects || [])
function toggleSubject(id) {
  props.studio.patchSettings({ subjects: studioTogglePicked(pickedSubjects.value, id, STUDIO_MAX_PICTURES) })
}

function setPhotoStyle(value) {
  props.studio.patchSettings({ photo_style: value ? Number(value) : null })
}

const styleValue = computed(() => studioStyleValue(s.value.style))
const styleKind = ref('none')
watch(styleValue, (v) => {
  styleKind.value = v?.kind || (styleKind.value === 'library' ? 'library' : 'none')
  if (v?.kind === 'words') styleWords.value = v.text
}, { immediate: true })

function setStyleKind(kind) {
  styleKind.value = kind
  if (kind === 'none' && styleValue.value) props.studio.patchSettings({ style: null })
  if (kind === 'words') styleWords.value = styleValue.value?.kind === 'words' ? styleValue.value.text : ''
}

function setLibraryStyle(value) {
  const st = styles.value.find((x) => String(x.id) === String(value))
  if (st) props.studio.patchSettings({ style: studioStyleSetting({ kind: 'library', id: st.id, title: st.title }) })
}

function saveStyleWords() {
  const next = studioStyleSetting({ kind: 'words', text: styleWords.value })
  const now = styleValue.value?.kind === 'words' ? styleValue.value.text : null
  if (next !== now) props.studio.patchSettings({ style: next })
}
</script>
