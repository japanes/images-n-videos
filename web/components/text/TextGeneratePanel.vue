<template>
  <!--
    «New background» tab: up to four new pictures for under the words, drawn by
    the picture model. A picked one becomes the canvas; the words and the
    layers stay where they are. The drawing runs as a job, so the tool can be
    closed meanwhile.
  -->
  <div class="space-y-4 p-4 text-sm">
    <section class="space-y-2 rounded-card border border-slate-200 p-3 dark:border-slate-700">
      <h3 class="font-semibold">{{ t('text.generate.title') }}</h3>
      <p class="text-xs muted">{{ t('text.generate.hint') }}</p>
      <textarea
        v-model="f.prompt"
        class="input"
        rows="4"
        :maxlength="TEXT_MAX_PROMPT"
        :placeholder="t('text.generate.placeholder')"
      />
      <div class="flex flex-wrap items-center gap-2">
        <span class="text-xs muted">{{ t('text.generate.count') }}</span>
        <div class="inline-flex overflow-hidden rounded-card border border-slate-200 dark:border-slate-700" role="group">
          <button
            v-for="n in TEXT_MAX_BACKGROUNDS"
            :key="n"
            type="button"
            class="px-3 py-1 text-xs"
            :class="f.count === n ? 'bg-primary text-white' : 'hover:bg-slate-100 dark:hover:bg-slate-700'"
            :aria-pressed="f.count === n"
            @click="f.count = n"
          >
            {{ n }}
          </button>
        </div>
      </div>
      <ToggleSwitch v-model="f.no_lettering" :label="t('text.generate.noLettering')" />
      <p class="pl-11 text-xs muted">{{ t('text.generate.noLetteringHint') }}</p>
      <ToggleSwitch v-model="f.use_current" :label="t('text.generate.useCurrent')" />
      <p class="pl-11 text-xs muted">{{ t('text.generate.useCurrentHint') }}</p>
      <p v-if="refusal" class="text-xs text-rose-700 dark:text-rose-300">{{ refusal }}</p>
      <div class="flex flex-wrap items-center gap-2">
        <PriceButton
          :label="t('text.generate.button', { n: f.count }, f.count)"
          icon="image"
          :usd="price"
          :busy="Boolean(s.busy.backgrounds)"
          :disabled="!hasPrompt || price === null || running"
          @click="tool.startBackgrounds()"
        />
        <button type="button" class="btn-ghost btn-sm" :disabled="!hasPrompt" @click="$emit('preview', 'backgrounds')">
          <AppIcon name="eye" :size="14" />{{ t('text.preview.button') }}
        </button>
        <button v-if="running" type="button" class="btn-secondary btn-sm" :disabled="Boolean(s.busy.cancel)" @click="stop">
          <Spinner v-if="s.busy.cancel" :size="12" /><AppIcon v-else name="stop" :size="14" />{{ t('text.generate.stop') }}
        </button>
      </div>
      <p v-if="running" class="text-xs muted">{{ t('text.generate.running') }}</p>
    </section>

    <section class="space-y-2">
      <div class="flex items-center gap-2">
        <h3 class="flex-1 font-semibold">{{ t('text.generate.results') }}</h3>
        <button
          v-if="s.original && s.original !== currentId"
          type="button"
          class="btn-ghost btn-sm"
          :disabled="Boolean(s.busy.original)"
          @click="tool.useOriginal()"
        >
          <Spinner v-if="s.busy.original" :size="12" /><AppIcon v-else name="refresh" :size="14" />{{ t('text.generate.original') }}
        </button>
      </div>
      <p v-if="!list.length" class="text-xs muted">{{ t('text.generate.empty') }}</p>
      <div v-else class="grid grid-cols-2 gap-2">
        <div
          v-for="bg in list"
          :key="bg.id"
          class="overflow-hidden rounded-card border dark:border-slate-700"
          :class="bg.file_id && bg.file_id === currentId ? 'border-primary ring-1 ring-primary' : 'border-slate-200'"
        >
          <div class="relative flex aspect-square items-center justify-center bg-slate-100 dark:bg-slate-900">
            <img v-if="bg.status === 'done' && (bg.thumb_url || bg.url)" :src="bg.thumb_url || bg.url" alt="" class="h-full w-full object-contain">
            <Spinner v-else-if="bg.status === 'queued' || bg.status === 'running'" :size="18" />
            <AppIcon v-else-if="bg.status === 'error'" name="alert" :size="20" class="text-rose-600" />
            <AppIcon v-else name="close" :size="20" class="muted" />
          </div>
          <div class="space-y-1.5 p-2 text-xs">
            <p class="muted">
              {{ t(`text.generate.status.${bg.status}`) }}
              <template v-if="bg.cost_usd"> · {{ formatUsd(bg.cost_usd) }}</template>
            </p>
            <TextErrorLine v-if="bg.status === 'error'" :item="bg" compact />
            <span v-if="bg.file_id && bg.file_id === currentId" class="badge bg-primary/10 text-primary">
              <AppIcon name="check" :size="12" />{{ t('text.generate.inUse') }}
            </span>
            <button
              v-else-if="bg.status === 'done' && bg.file_id"
              type="button"
              class="btn-secondary btn-sm w-full justify-center"
              :disabled="Boolean(s.busy[`use${bg.id}`])"
              @click="tool.useBackground(bg.id)"
            >
              <Spinner v-if="s.busy[`use${bg.id}`]" :size="12" />{{ t('text.generate.use') }}
            </button>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { formatUsd } from '~/utils/format.js'
import { TEXT_MAX_BACKGROUNDS, TEXT_MAX_PROMPT, textBackgroundsBusy, textPrice, textReasonText } from '~/utils/textView.js'

defineEmits(['preview'])
const tool = inject('textTool')
const s = tool.state
const f = s.forms.background
const { t, te } = useI18n()
const { confirm } = useConfirm()

const price = computed(() => textPrice(s.est?.background))
const refusal = computed(() => textReasonText(s.est?.background?.refusal, t, te))
const hasPrompt = computed(() => Boolean(String(f.prompt || '').trim()))
const list = computed(() => s.design?.backgrounds || [])
const running = computed(() => textBackgroundsBusy(list.value))
const currentId = computed(() => s.design?.background?.file_id || null)

async function stop() {
  const ok = await confirm({ message: t('text.generate.stopAsk'), confirmLabel: t('text.generate.stop'), tone: 'danger' })
  if (ok) tool.cancelBackgrounds()
}
</script>
