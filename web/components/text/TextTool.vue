<template>
  <!--
    «Text on the picture» (module 06), full screen over the chat: the canvas on
    the left, three tabs on the right (words, layers, new background). Every
    change is kept as a draft; «Save» draws the picture with the words, makes it
    a new version of the frame and puts it into the same chat as a new message.
  -->
  <ModalShell open :title="title" size="full" body-class="p-0" :close-on-overlay="false" @close="close">
    <div v-if="s.loading" class="flex h-full items-center justify-center py-16"><Spinner :size="28" /></div>
    <div v-else-if="!s.design" class="space-y-3 p-6 text-sm">
      <p class="rounded-card bg-rose-50 px-3 py-2 text-rose-800 dark:bg-rose-500/10 dark:text-rose-200">{{ s.error || t('text.tool.failed') }}</p>
      <button type="button" class="btn-secondary" @click="tool.open()">{{ t('text.tool.retry') }}</button>
    </div>
    <div v-else class="flex h-full min-h-0 flex-col lg:flex-row">
      <div class="flex h-[45vh] min-h-0 flex-col lg:h-auto lg:flex-1">
        <TextCanvas />
      </div>
      <aside class="flex min-h-0 flex-col border-t border-slate-200 dark:border-slate-700 lg:w-[400px] lg:border-l lg:border-t-0">
        <div class="flex gap-1 border-b border-slate-200 px-3 dark:border-slate-700" role="tablist">
          <button
            v-for="tab in TEXT_TABS"
            :key="tab"
            type="button"
            role="tab"
            :aria-selected="activeTab === tab"
            class="-mb-px inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-medium"
            :class="activeTab === tab ? 'border-primary text-primary' : 'border-transparent muted hover:text-slate-900 dark:hover:text-white'"
            @click="activeTab = tab"
          >
            {{ t(`text.tabs.${tab}`) }}
            <Spinner v-if="tab === 'generate' && generating" :size="12" />
          </button>
        </div>
        <div class="min-h-0 flex-1 overflow-y-auto">
          <TextWordsPanel v-show="activeTab === 'words'" @preview="previewStep = $event" />
          <TextLayersPanel v-show="activeTab === 'layers'" />
          <TextGeneratePanel v-show="activeTab === 'generate'" @preview="previewStep = $event" />
        </div>
      </aside>
    </div>

    <template #footer>
      <p v-if="s.error && s.design" class="mr-auto min-w-0 flex-1 truncate text-sm text-rose-700 dark:text-rose-300" :title="s.error">{{ s.error }}</p>
      <p v-else class="mr-auto min-w-0 flex-1 truncate text-xs muted">
        <Spinner v-if="s.syncing" :size="12" class="mr-1 inline" />{{ s.syncing ? t('text.tool.syncing') : t('text.tool.draftHint') }}
      </p>
      <span v-if="spent" class="text-xs muted">{{ t('text.tool.spent', { usd: formatUsd(spent) }) }}</span>
      <button type="button" class="btn-secondary" @click="close">{{ t('common.close') }}</button>
      <PriceButton
        :label="t('text.tool.save')"
        icon="check"
        :usd="0"
        :busy="Boolean(s.busy.save) || posting"
        :disabled="!s.design?.background || posting"
        @click="save"
      />
    </template>
  </ModalShell>

  <TextPromptPreview v-if="previewStep" :step="previewStep" @close="previewStep = ''" />
</template>

<script setup>
import { formatUsd } from '~/utils/format.js'
import { TEXT_TABS, textBackgroundsBusy } from '~/utils/textView.js'

const props = defineProps({
  room: { type: Object, required: true }, // the chat room (useChatRoom), to put the result in
  message: { type: Object, required: true }, // the chat message with the picture
  item: { type: Object, required: true }, // the picture of that message: { frame_id, file_id, … }
})
const emit = defineEmits(['close'])
const { t } = useI18n()
const toast = useToast()

const tool = useTextTool({
  frameId: props.item.frame_id, fileId: props.item.file_id, chatId: props.room.chatId, messageId: props.message.id,
})
provide('textTool', tool)
const s = tool.state

const activeTab = ref('words')
const previewStep = ref('')
const posting = ref(false)

const title = computed(() => {
  const frame = s.design?.frame
  if (!frame?.work_title) return t('text.tool.title')
  return t('text.tool.titleOf', { title: frame.work_title })
})
const generating = computed(() => textBackgroundsBusy(s.design?.backgrounds))
const spent = computed(() => Number(s.design?.cost_usd) || 0)

onMounted(() => tool.open())

function close() {
  if (s.busy.save || posting.value) return
  emit('close')
}

/** The picture with the words becomes a new version of the frame and a new message in this chat. */
async function save() {
  const res = await tool.save()
  if (!res) return
  posting.value = true
  try {
    await props.room.fromViewer(res.frame?.id || props.item.frame_id, props.message.id)
  } finally {
    posting.value = false
  }
  toast.success(t('text.tool.saved'))
  emit('close')
}
</script>
