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
      <div class="space-y-1">
        <span class="label">{{ t('studio.settings.photoStyle') }}</span>
        <StudioPhotoStylePicker
          :model-value="s.photo_style ?? null"
          :disabled="saving"
          @update:model-value="studio.patchSettings({ photo_style: $event })"
        />
      </div>
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

  </div>
</template>

<script setup>
import {
  STUDIO_ASPECTS, STUDIO_LIMITS, STUDIO_MAX_FRAMES, STUDIO_MAX_PICTURES, studioModelChoices, studioSizesFor,
  studioTogglePicked,
} from '~/utils/studioView.js'

const props = defineProps({
  studio: { type: Object, required: true },
})
const { t } = useI18n()
const api = useApi()
const { confirm } = useConfirm()
const models = useModels()

const work = computed(() => props.studio.work.value)
const s = computed(() => work.value?.settings || {})
const saving = computed(() => props.studio.isPending('work'))

// ── lists for the selects (loaded once) ──
const kits = ref([])
const subjects = ref([])
const quietly = async (fn, fallback) => { try { return await fn() } catch { return fallback } }

onMounted(async () => {
  if (!models.loaded.value) models.load()
  const [k, sub] = await Promise.all([
    quietly(() => api.get('/api/brand/kits'), {}),
    quietly(() => api.get('/api/brand/subjects', { scope: 'library' }), {}),
  ])
  kits.value = k.items || []
  subjects.value = sub.items || []
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

// ── subjects ──
const pickedSubjects = computed(() => s.value.subjects || [])
function toggleSubject(id) {
  props.studio.patchSettings({ subjects: studioTogglePicked(pickedSubjects.value, id, STUDIO_MAX_PICTURES) })
}
</script>
