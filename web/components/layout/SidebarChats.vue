<template>
  <!--
    The chats in the left menu (module 15): «New chat», search, the list with
    rename and archive, and the archive itself behind a switch at the bottom.
  -->
  <div class="flex min-h-0 flex-col">
    <div class="space-y-2 px-3 pb-2">
      <button v-if="!list.archived" type="button" class="btn-primary w-full justify-center" :disabled="starting" @click="newChat">
        <Spinner v-if="starting" :size="14" /><AppIcon v-else name="plus" :size="16" />{{ t('chat.sidebar.new') }}
      </button>
      <div v-else class="flex items-center gap-2 px-1 text-sm font-semibold">
        <AppIcon name="archive" :size="16" />{{ t('chat.sidebar.archiveTitle') }}
      </div>
      <label class="relative block">
        <span class="sr-only">{{ t('chat.sidebar.search') }}</span>
        <AppIcon name="search" :size="14" class="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 opacity-50" />
        <input v-model="list.q" type="search" class="input py-1.5 pl-8 text-sm" :placeholder="t('chat.sidebar.search')">
      </label>
    </div>

    <div class="min-h-0 flex-1 overflow-y-auto px-2">
      <div v-if="list.loading && !list.items.length" class="flex justify-center py-6"><Spinner :size="16" /></div>
      <p v-else-if="list.error && !list.items.length" class="px-2.5 py-2 text-xs text-rose-600 dark:text-rose-400">
        {{ chatErrorText(list.error, t, te) }}
      </p>
      <p v-else-if="!list.items.length" class="px-2.5 py-2 text-xs muted">
        {{ list.q.trim() ? t('chat.sidebar.nothingFound') : list.archived ? t('chat.sidebar.archiveEmpty') : t('chat.sidebar.empty') }}
      </p>

      <ul class="space-y-0.5">
        <li v-for="c in list.items" :key="c.id" class="group relative">
          <input
            v-if="editing === c.id"
            ref="renameInput"
            v-model="editTitle"
            class="input py-1.5 text-sm"
            :maxlength="CHAT_LIMITS.title"
            :aria-label="t('chat.sidebar.rename')"
            @keydown.enter.prevent="saveRename(c)"
            @keydown.escape="editing = null"
            @blur="saveRename(c)"
          >
          <template v-else>
            <NuxtLink
              :to="`/chat/${c.id}`"
              class="flex items-center gap-2 rounded-button py-1.5 pl-2.5 pr-9 text-sm text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
              :class="c.id === activeId && '!bg-primary/10 !text-primary'"
              :title="c.title || t('chat.room.untitled')"
              @click="$emit('navigate')"
            >
              <AppIcon :name="c.mode === 'video' ? 'video' : 'image'" :size="14" class="shrink-0 opacity-60" />
              <span class="truncate">{{ c.title || t('chat.room.untitled') }}</span>
            </NuxtLink>
            <ChatMenu
              class="absolute right-1 top-1/2 -translate-y-1/2 opacity-100 lg:opacity-0 lg:focus-within:opacity-100 lg:group-hover:opacity-100"
              :items="menuItems(c)"
              :label="t('chat.sidebar.actions')"
              icon="more"
              button-class="btn-ghost p-1"
            />
          </template>
        </li>
      </ul>

      <div v-if="list.more" class="flex justify-center py-2">
        <button type="button" class="btn-ghost btn-sm" :disabled="list.loading" @click="list.load({ append: true })">
          <Spinner v-if="list.loading" :size="14" />{{ t('chat.sidebar.more') }}
        </button>
      </div>
    </div>

    <div class="px-2 py-1.5">
      <button
        type="button"
        class="flex w-full items-center gap-2.5 rounded-button px-2.5 py-1.5 text-xs text-slate-500 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800"
        @click="toggleArchive"
      >
        <AppIcon :name="list.archived ? 'chevron-left' : 'archive'" :size="14" />
        {{ list.archived ? t('chat.sidebar.backToChats') : t('chat.sidebar.showArchive') }}
      </button>
    </div>
  </div>
</template>

<script setup>
import { CHAT_LIMITS, chatErrorText, chatQueryId } from '~/utils/chatView.js'

const emit = defineEmits(['navigate'])
const { t, te } = useI18n()
const route = useRoute()
const { confirm } = useConfirm()
const start = useChatStart()

const list = reactive(useChatList())
onMounted(() => list.load())

const activeId = computed(() => (route.path.startsWith('/chat/') ? chatQueryId(route.params.id) : null))

const starting = ref(false)
async function newChat() {
  starting.value = true
  try {
    const chat = await start.open({ onlyEmpty: true })
    if (chat) {
      list.reload()
      emit('navigate')
      await navigateTo(`/chat/${chat.id}`)
    }
  } finally {
    starting.value = false
  }
}

function toggleArchive() {
  editing.value = null
  list.archived = !list.archived
}

// ── rename in place ──

const editing = ref(null)
const editTitle = ref('')
const renameInput = ref(null)

function startRename(c) {
  editing.value = c.id
  editTitle.value = c.title || ''
  nextTick(() => {
    const el = Array.isArray(renameInput.value) ? renameInput.value[0] : renameInput.value
    el?.focus()
    el?.select()
  })
}

async function saveRename(c) {
  if (editing.value !== c.id) return
  editing.value = null
  const title = editTitle.value.trim()
  if (!title || title === c.title) return
  await list.rename(c.id, title)
}

// ── archive ──

async function setArchived(c, value) {
  if (value) {
    const ok = await confirm({
      title: t('chat.sidebar.archiveAskTitle'),
      message: t('chat.sidebar.archiveAsk', { title: c.title || t('chat.room.untitled') }),
      confirmLabel: t('chat.sidebar.archive'),
      tone: 'danger',
    })
    if (!ok) return
  }
  const res = await list.archive(c.id, value)
  if (res && value && c.id === activeId.value) await navigateTo('/chat')
}

function menuItems(c) {
  return [
    { id: 'rename', icon: 'edit', label: t('chat.sidebar.rename'), onClick: () => startRename(c) },
    c.archived || list.archived
      ? { id: 'unarchive', icon: 'archive', label: t('chat.sidebar.unarchive'), onClick: () => setArchived(c, false) }
      : { id: 'archive', icon: 'archive', label: t('chat.sidebar.archive'), tone: 'danger', onClick: () => setArchived(c, true) },
  ]
}
</script>
