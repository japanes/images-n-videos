<template>
  <!-- «What went to the model»: the exact text and settings kept on the request when it was sent. -->
  <details class="group text-xs" :open="open" @toggle="open = $event.target.open">
    <summary class="inline-flex cursor-pointer select-none items-center gap-1 text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200">
      <AppIcon name="eye" :size="14" />{{ t('chat.sent.title') }}
    </summary>
    <div v-if="open" class="mt-2 space-y-2 rounded-card border border-slate-200 bg-white/70 p-3 text-slate-700 dark:border-slate-700 dark:bg-slate-900/40 dark:text-slate-200">
      <dl class="grid grid-cols-[minmax(0,8rem)_minmax(0,1fr)] gap-x-3 gap-y-1.5">
        <template v-for="row in rows" :key="row.key">
          <dt class="muted">{{ row.label }}</dt>
          <dd class="min-w-0 break-words" :class="row.pre && 'whitespace-pre-wrap'">{{ row.value }}</dd>
        </template>
      </dl>
      <div v-if="pictures.length" class="space-y-1">
        <p class="muted">{{ t('chat.sent.pictures') }}</p>
        <div class="flex flex-wrap gap-2">
          <figure v-for="(a, i) in pictures" :key="`${a.file_id}-${i}`" class="w-16">
            <img v-if="chatFileThumb(a.file)" :src="chatFileThumb(a.file)" alt="" class="h-16 w-16 rounded-button object-cover">
            <div v-else class="grid h-16 w-16 place-items-center rounded-button bg-slate-100 dark:bg-slate-800"><AppIcon name="alert" :size="16" /></div>
            <figcaption class="mt-0.5 truncate text-[11px] muted">{{ roleText(a.role) }}</figcaption>
          </figure>
        </div>
      </div>
      <ul v-if="warnings.length" class="list-disc space-y-0.5 pl-4 text-amber-700 dark:text-amber-300">
        <li v-for="w in warnings" :key="w">{{ w }}</li>
      </ul>
    </div>
  </details>
</template>

<script setup>
import { formatUsd } from '~/utils/format.js'
import { studioStyleValue } from '~/utils/studioView.js'
import { chatFileThumb, chatWarningText } from '~/utils/chatView.js'

const props = defineProps({
  settings: { type: Object, default: () => ({}) }, // the snapshot of the request
  attachments: { type: Array, default: () => [] },
})
const { t, te } = useI18n()
const modelTitle = inject('chatModelTitle', (id) => id)
const open = ref(false)

const s = computed(() => props.settings || {})
const pictures = computed(() => props.attachments || [])
const warnings = computed(() => (s.value.warnings || []).map((w) => chatWarningText(w, t, te)))
const onOff = (v) => (v ? t('common.on') : t('common.off'))

function roleText(role) {
  return te(`chat.roles.${role}`) ? t(`chat.roles.${role}`) : role
}

function styleText(style) {
  const v = studioStyleValue(style)
  if (!v) return ''
  return v.kind === 'library' ? v.title || `#${v.id}` : v.text
}

function regionText(region) {
  if (!region) return ''
  if (region.id) return t('chat.sent.regionObject')
  return region.label ? `${t('chat.sent.regionBox')}: ${region.label}` : t('chat.sent.regionBox')
}

const rows = computed(() => {
  const out = []
  const add = (key, value, extra = {}) => {
    if (value !== null && value !== undefined && value !== '') out.push({ key, label: t(`chat.sent.${key}`), value, ...extra })
  }
  const v = s.value
  add('text', v.sent_text || '—', { pre: true })
  if (v.enhanced) {
    add('original', v.original_text, { pre: true })
    const prompt = v.enhance_prompt ? `${v.enhance_prompt.code} v${v.enhance_prompt.version}` : ''
    add('enhance', [modelTitle(v.enhance_model_id), prompt, formatUsd(v.enhance_cost_usd || 0)].filter(Boolean).join(' · '))
  } else if (v.enhance) {
    add('enhance', t('chat.sent.enhanceAsked'))
  }
  if (v.action) add('action', te(`chat.actions.${v.action}`) ? t(`chat.actions.${v.action}`) : v.action)
  if (v.model_id) add('model', modelTitle(v.model_id))
  if (v.mode === 'image') {
    const img = v.image || {}
    add('aspect', img.aspect)
    add('size', v.image_size || img.image_size)
    if (v.action === 'new_image') {
      add('count', v.count)
      if (img.series && v.count > 1) add('series', t('common.on'))
      if (img.text_mode) add('textMode', te(`studio.textModes.${img.text_mode}.name`) ? t(`studio.textModes.${img.text_mode}.name`) : img.text_mode)
      add('style', styleText(img.style))
      if (img.photo_style) add('photoStyle', `#${img.photo_style}`)
      if (img.subjects?.length) add('subjects', img.subjects.map((id) => `#${id}`).join(', '))
      if (v.kit_id) add('kitReferences', onOff(img.kit_references !== false))
    }
    add('region', regionText(v.region))
  } else {
    const vid = v.video || {}
    const sent = v.video_sent || {}
    if (v.extend) {
      add('seconds', t('chat.summary.seconds', { n: v.extend.seconds }))
    } else {
      if (sent.seconds) add('seconds', t('chat.summary.seconds', { n: sent.seconds }))
      add('resolution', sent.resolution || vid.resolution)
      add('aspect', sent.aspect || vid.aspect)
      add('cameraMove', vid.camera_move || '')
      add('sound', onOff(vid.sound !== false))
    }
  }
  if (v.mentions?.length) add('mentions', v.mentions.map((m) => `@${m.name}`).join(', '))
  if (v.kit_id) add('kit', `#${v.kit_id}`)
  if (v.estimate_usd !== null && v.estimate_usd !== undefined) add('estimate', formatUsd(v.estimate_usd, { approx: true }))
  return out
})
</script>
