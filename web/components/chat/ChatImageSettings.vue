<template>
  <!--
    Picture settings of the chat, for the side panel. Each field saves on its
    own and applies to the next requests (sent ones keep what they were sent with).
    Every field sits in a box with id `chat-set-<key>`: a click on the summary
    line under the composer opens that very field.
  -->
  <div v-if="chat" class="space-y-6 text-sm">
    <section class="space-y-3">
      <label id="chat-set-kit" class="block space-y-1">
        <span class="label">{{ t('studio.settings.kit') }}</span>
        <select class="input" :value="chat.kit_id || ''" :disabled="saving" @change="setKit($event.target.value)">
          <option value="">{{ t('studio.settings.noKit') }}</option>
          <option v-for="k in kits" :key="k.id" :value="k.id">{{ k.name }}</option>
        </select>
      </label>

      <label id="chat-set-model" class="block space-y-1">
        <span class="label">{{ t('studio.settings.model') }}</span>
        <select class="input" :value="s.model_id || ''" :disabled="saving" @change="room.patchImage({ model_id: $event.target.value || null })">
          <option value="">{{ t('studio.settings.modelDefault', { name: defaultModelTitle }) }}</option>
          <option v-for="m in modelChoices" :key="m.id" :value="m.id">{{ m.title || m.id }}</option>
        </select>
      </label>

      <div class="grid grid-cols-3 gap-2">
        <label id="chat-set-aspect" class="block space-y-1">
          <span class="label">{{ t('studio.settings.aspect') }}</span>
          <select class="input" :value="s.aspect" :disabled="saving" @change="room.patchImage({ aspect: $event.target.value })">
            <option v-for="a in STUDIO_ASPECTS" :key="a" :value="a">{{ a }}</option>
          </select>
        </label>
        <label id="chat-set-size" class="block space-y-1">
          <span class="label">{{ t('studio.settings.size') }}</span>
          <select class="input" :value="s.image_size" :disabled="saving" @change="room.patchImage({ image_size: $event.target.value })">
            <option v-for="size in sizeChoices" :key="size" :value="size">{{ size }}</option>
          </select>
        </label>
        <label id="chat-set-count" class="block space-y-1">
          <span class="label">{{ t('chat.settings.count') }}</span>
          <select class="input" :value="s.count" :disabled="saving" @change="room.patchImage({ count: Number($event.target.value) })">
            <option v-for="n in STUDIO_MAX_FRAMES" :key="n" :value="n">{{ n }}</option>
          </select>
        </label>
      </div>
      <p v-if="s.image_size && !sizeChoices.includes(s.image_size)" class="muted text-xs">
        {{ t('studio.settings.sizeFallback', { size: s.image_size }) }}
      </p>

      <div id="chat-set-series" class="space-y-1">
        <ToggleSwitch
          :model-value="Boolean(s.series)"
          :label="t('studio.settings.series')"
          :disabled="saving || (!s.series && Number(s.count) < 2)"
          @update:model-value="room.patchImage({ series: $event })"
        />
        <p class="muted text-xs">{{ t('chat.settings.seriesHint') }}</p>
      </div>
    </section>

    <section class="space-y-3">
      <h3 class="font-semibold">{{ t('chat.settings.people') }}</h3>
      <ToggleSwitch
        v-if="chat.kit_id"
        id="chat-set-kit_references"
        :model-value="s.kit_references !== false"
        :label="t('studio.settings.kitReferences')"
        :disabled="saving"
        @update:model-value="room.patchImage({ kit_references: $event })"
      />
      <div id="chat-set-subjects" class="space-y-1">
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
        <p class="muted text-xs">{{ t('chat.settings.mentionsHint') }}</p>
      </div>
    </section>

    <section class="space-y-3">
      <h3 class="font-semibold">{{ t('studio.settings.look') }}</h3>
      <label id="chat-set-photo_style" class="block space-y-1">
        <span class="label">{{ t('studio.settings.photoStyle') }}</span>
        <select class="input" :value="s.photo_style ?? ''" :disabled="saving" @change="setPhotoStyle($event.target.value)">
          <option value="">{{ t('studio.settings.plainPhoto') }}</option>
          <option v-for="p in photoStyles" :key="p.id" :value="p.id">{{ p.title }}</option>
        </select>
      </label>

      <div id="chat-set-style" class="space-y-1">
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
          @update:model-value="room.patchImage({ style_sample: $event })"
        />
      </div>
    </section>

    <section id="chat-set-text_mode" class="space-y-2">
      <h3 class="font-semibold">{{ t('studio.settings.textMode') }}</h3>
      <label v-for="m in STUDIO_TEXT_MODES" :key="m" class="flex cursor-pointer items-start gap-2">
        <input type="radio" class="mt-1" name="chat-text-mode" :value="m" :checked="s.text_mode === m" :disabled="saving" @change="room.patchImage({ text_mode: m })">
        <span>
          <span class="block">{{ t(`studio.textModes.${m}.name`) }}</span>
          <span class="muted block text-xs">{{ t(`studio.textModes.${m}.hint`) }}</span>
        </span>
      </label>
    </section>

    <section id="chat-set-blocks" class="space-y-2">
      <h3 class="font-semibold">{{ t('studio.settings.blocks') }}</h3>
      <p class="muted text-xs">{{ t('chat.settings.blocksHint') }}</p>
      <StudioBlockToggles
        v-if="blocks.items?.length"
        :blocks="blocks.items"
        :disabled="saving"
        @change="room.patchImage({ blocks: $event })"
      />
      <p v-else-if="blocks.error" class="text-xs text-rose-600 dark:text-rose-400">
        {{ studioReasonText(blocks.error, t, te) }}
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
  room: { type: Object, required: true }, // reactive(useChatRoom(…))
})
const { t, te } = useI18n()
const api = useApi()
const models = inject('chatModels', () => useModels(), true)

const chat = computed(() => props.room.chat)
const s = computed(() => chat.value?.image_settings || {})
const blocks = computed(() => chat.value?.image_blocks || {})
const saving = computed(() => props.room.isPending('settings'))

// ── lists for the selects (loaded once) ──
const kits = ref([])
const subjects = ref([])
const styles = ref([])
const photoStyles = ref([])
const quietly = async (fn, fallback) => { try { return await fn() } catch { return fallback } }

onMounted(async () => {
  if (!models.loaded.value && !models.loading.value) models.load()
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
const currentModel = computed(() => (s.value.model_id ? models.find(s.value.model_id) : defaultModel.value))
const sizeChoices = computed(() => studioSizesFor(currentModel.value))

function setKit(value) {
  props.room.patch({ kit_id: value ? Number(value) : null })
}

// ── subjects, photo style, style ──
const pickedSubjects = computed(() => s.value.subjects || [])
function toggleSubject(id) {
  props.room.patchImage({ subjects: studioTogglePicked(pickedSubjects.value, id, STUDIO_MAX_PICTURES) })
}

function setPhotoStyle(value) {
  props.room.patchImage({ photo_style: value ? Number(value) : null })
}

const styleWords = ref('')
const styleValue = computed(() => studioStyleValue(s.value.style))
const styleKind = ref('none')
watch(styleValue, (v) => {
  styleKind.value = v?.kind || (styleKind.value === 'library' ? 'library' : 'none')
  if (v?.kind === 'words') styleWords.value = v.text
}, { immediate: true })

function setStyleKind(kind) {
  styleKind.value = kind
  if (kind === 'none' && styleValue.value) props.room.patchImage({ style: null })
  if (kind === 'words') styleWords.value = styleValue.value?.kind === 'words' ? styleValue.value.text : ''
}

function setLibraryStyle(value) {
  const st = styles.value.find((x) => String(x.id) === String(value))
  if (st) props.room.patchImage({ style: studioStyleSetting({ kind: 'library', id: st.id, title: st.title }) })
}

function saveStyleWords() {
  const next = studioStyleSetting({ kind: 'words', text: styleWords.value })
  const now = styleValue.value?.kind === 'words' ? styleValue.value.text : null
  if (next !== now) props.room.patchImage({ style: next })
}
</script>
