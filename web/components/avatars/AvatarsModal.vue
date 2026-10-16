<template>
  <!--
    The «Avatars» window of the chat (module 09): the list of avatars, a new one,
    calling a ready avatar into the current request by its name (@Name) and
    adding the pictures attached in the composer to the avatar of this chat.
    Every avatar lives in a chat of its own: «Open» goes there.
  -->
  <ModalShell open :title="t('avatars.modal.title')" size="lg" @close="emit('close')">
    <div class="space-y-4 text-sm">
      <p class="muted">{{ t('avatars.modal.text') }}</p>

      <!-- pictures attached in this avatar's chat -> photos of the person -->
      <div v-if="here && draftIds.length" class="flex flex-wrap items-center gap-2 rounded-card bg-slate-50 p-3 dark:bg-slate-900/60">
        <AppIcon name="paperclip" :size="16" class="muted" />
        <span class="min-w-0 flex-1">{{ t('avatars.modal.attached', { n: draftIds.length, name: here.name }, draftIds.length) }}</span>
        <button type="button" class="btn-primary btn-sm" :disabled="Boolean(busy)" @click="addAttached">
          <Spinner v-if="busy === 'attach'" :size="14" />{{ t('avatars.modal.attachedAdd') }}
        </button>
      </div>

      <!-- a new avatar -->
      <section v-if="creating" class="space-y-3 rounded-card border border-slate-200 p-4 dark:border-slate-700">
        <h3 class="font-semibold">{{ t('avatars.modal.new') }}</h3>
        <div>
          <label class="label" for="avatar-name">{{ t('avatars.modal.name') }}</label>
          <input
            id="avatar-name"
            v-model="form.name"
            class="input"
            :maxlength="AVATAR_LIMITS.name"
            :placeholder="t('avatars.modal.namePlaceholder')"
          >
          <p class="mt-1 text-xs muted">{{ t('avatars.modal.nameHint') }}</p>
        </div>
        <fieldset class="space-y-1.5">
          <legend class="label">{{ t('avatars.modes.label') }}</legend>
          <label
            v-for="m in AVATAR_MODES"
            :key="m"
            class="flex cursor-pointer items-start gap-2 rounded-card border px-3 py-2"
            :class="form.mode === m ? 'border-primary bg-primary/5' : 'border-slate-200 dark:border-slate-700'"
          >
            <input v-model="form.mode" type="radio" name="avatar-mode" :value="m" class="mt-1">
            <span class="min-w-0">
              <span class="block font-medium">{{ t(`avatars.modes.${m}.name`) }}</span>
              <span class="block text-xs muted">{{ t(`avatars.modes.${m}.text`) }}</span>
            </span>
          </label>
        </fieldset>
        <div v-if="form.mode !== 'reference'">
          <label class="label" for="avatar-brief">{{ t('avatars.person.brief') }}</label>
          <textarea
            id="avatar-brief"
            v-model="form.brief"
            class="input"
            rows="3"
            :maxlength="AVATAR_LIMITS.brief"
            :placeholder="t('avatars.person.briefPlaceholder')"
          />
          <p class="mt-1 text-xs muted">
            {{ form.mode === 'description' ? t('avatars.person.briefNeeded') : t('avatars.person.briefOptional') }}
          </p>
        </div>
        <label v-if="!here && draftIds.length && form.mode === 'reference'" class="flex items-center gap-2">
          <input v-model="form.attach" type="checkbox">
          <span>{{ t('avatars.modal.createAttached', { n: draftIds.length }, draftIds.length) }}</span>
        </label>
        <div class="flex flex-wrap justify-end gap-2">
          <button type="button" class="btn-secondary btn-sm" @click="creating = false">{{ t('common.cancel') }}</button>
          <button type="button" class="btn-primary btn-sm" :disabled="!canCreate || Boolean(busy)" @click="create">
            <Spinner v-if="busy === 'create'" :size="14" />{{ t('avatars.modal.create') }}
          </button>
        </div>
        <p class="text-xs muted">{{ t('avatars.modal.createFree') }}</p>
      </section>
      <button v-else type="button" class="btn-primary" @click="startCreate">
        <AppIcon name="plus" :size="16" />{{ t('avatars.modal.new') }}
      </button>

      <!-- the list -->
      <section class="space-y-2">
        <div class="flex flex-wrap items-center gap-2">
          <h3 class="min-w-0 flex-1 font-semibold">{{ archived ? t('avatars.modal.archived') : t('avatars.modal.list') }}</h3>
          <ToggleSwitch v-model="archived" :label="t('avatars.modal.showArchived')" />
        </div>
        <div v-if="loading && !items.length" class="flex items-center gap-2 muted"><Spinner :size="14" />{{ t('common.loading') }}</div>
        <AvatarsErrorLine v-else-if="loadError" :item="{ error_code: loadError.code, error: loadError.message }" />
        <EmptyState
          v-else-if="!items.length"
          icon="user"
          :title="archived ? t('avatars.modal.emptyArchived') : t('avatars.modal.empty')"
        />
        <ul v-else class="space-y-2">
          <li
            v-for="a in items"
            :key="a.id"
            class="flex items-center gap-3 rounded-card border border-slate-200 p-2 dark:border-slate-700"
          >
            <img
              v-if="a.face"
              :src="chatFileThumb(a.face)"
              alt=""
              class="h-14 w-11 shrink-0 rounded-button bg-slate-100 object-cover dark:bg-slate-800"
            >
            <span v-else class="grid h-14 w-11 shrink-0 place-items-center rounded-button bg-slate-100 muted dark:bg-slate-800">
              <AppIcon name="user" :size="18" />
            </span>
            <div class="min-w-0 flex-1">
              <p class="truncate font-medium">{{ a.name }}</p>
              <p class="flex flex-wrap items-center gap-x-2 text-xs muted">
                <span>{{ t(`avatars.states.${a.state}`) }}</span>
                <span v-if="a.counts">{{ t('avatars.card.count', { done: a.counts.done, total: a.counts.total }) }}</span>
                <span v-if="a.busy || a.describing" class="inline-flex items-center gap-1"><Spinner :size="10" />{{ t('avatars.card.working') }}</span>
              </p>
            </div>
            <div class="flex shrink-0 flex-wrap justify-end gap-1">
              <button
                v-if="canCall(a)"
                type="button"
                class="btn-secondary btn-sm"
                :title="t('avatars.chat.callHint', { name: a.name })"
                @click="call(a)"
              >
                {{ t('avatars.chat.call') }}
              </button>
              <button v-if="a.archived_at" type="button" class="btn-secondary btn-sm" :disabled="Boolean(busy)" @click="restore(a)">
                <Spinner v-if="busy === `restore:${a.id}`" :size="14" />{{ t('avatars.card.restore') }}
              </button>
              <button type="button" class="btn-ghost btn-sm" :disabled="!a.chat_id" @click="open(a)">
                {{ t('avatars.modal.open') }}<AppIcon name="chevron-right" :size="14" />
              </button>
            </div>
          </li>
        </ul>
        <p v-if="mode === 'image' && items.some((a) => !a.archived_at)" class="text-xs muted">{{ t('avatars.chat.callAbout') }}</p>
      </section>
    </div>
  </ModalShell>
</template>

<script setup>
import { chatFileThumb } from '~/utils/chatView.js'
import {
  AVATAR_LIMITS, AVATAR_MODES, avatarsChatAvatarId, avatarsDraftFileIds, avatarsErrorText, avatarsMention,
} from '~/utils/avatarsView.js'

const props = defineProps({
  room: { type: Object, required: true },
  text: { type: String, default: '' }, // what is typed in the composer
  setText: { type: Function, default: null }, // puts the text in the composer
})
const emit = defineEmits(['close'])
const { t, te } = useI18n()
const api = useApi()
const toast = useToast()
const { on } = useEvents()

const mode = computed(() => props.room.mode || props.room.chat?.mode || 'image')
const draftIds = computed(() => avatarsDraftFileIds(props.room.draft))
const hereId = computed(() => avatarsChatAvatarId(props.room.chat))

// ── the list ──

const archived = ref(false)
const items = ref([])
const loading = ref(false)
const loadError = ref(null)
const all = ref([]) // the avatars that are not archived (to find this chat's avatar)
let seq = 0

async function load() {
  const mine = ++seq
  loading.value = true
  try {
    const res = await api.get('/api/avatars', { archived: archived.value })
    if (mine !== seq) return
    items.value = res?.items || []
    if (!archived.value) all.value = items.value
    loadError.value = null
  } catch (err) {
    if (mine === seq) loadError.value = err
  } finally {
    if (mine === seq) loading.value = false
  }
}
watch(archived, load, { immediate: true })
let timer = null
on('avatars.updated', () => { clearTimeout(timer); timer = setTimeout(load, 300) })
onBeforeUnmount(() => clearTimeout(timer))

const here = computed(() => (hereId.value ? all.value.find((a) => a.id === hereId.value) || null : null))

function canCall(a) {
  return mode.value === 'image' && !a.archived_at && a.as_subject && Boolean(a.subject_id) && Boolean(props.setText)
}

function call(a) {
  props.setText(avatarsMention(props.text, a.name))
  emit('close')
}

async function open(a) {
  emit('close')
  await navigateTo(`/chat/${a.chat_id}`)
}

// ── actions ──

const busy = ref('')
async function act(key, fn) {
  if (busy.value) return null
  busy.value = key
  try {
    return await fn()
  } catch (err) {
    toast.error(avatarsErrorText(err, t, te))
    return null
  } finally {
    busy.value = ''
  }
}

async function restore(a) {
  await act(`restore:${a.id}`, async () => {
    await api.post(`/api/avatars/${a.id}/archive`, { archived: false })
    await load()
  })
}

async function addAttached() {
  const id = hereId.value
  await act('attach', async () => {
    const res = await api.post(`/api/avatars/${id}/photos/from-files`, { file_ids: draftIds.value })
    props.room.editDraft({ attachments: [] })
    toast.success(t('avatars.modal.attachedDone', { n: res?.added?.length || 0 }, res?.added?.length || 0))
    emit('close')
  })
}

// ── a new avatar ──

const creating = ref(false)
const form = reactive({ name: '', mode: 'reference', brief: '', attach: true })
const canCreate = computed(() => form.name.trim().length > 0
  && (form.mode !== 'description' || form.brief.trim().length > 0))

function startCreate() {
  creating.value = true
  form.attach = draftIds.value.length > 0
}

async function create() {
  const attach = form.attach && !hereId.value && form.mode === 'reference' ? draftIds.value : []
  await act('create', async () => {
    const res = await api.post('/api/avatars', {
      name: form.name.trim(), mode: form.mode, brief: form.mode === 'reference' ? '' : form.brief.trim(),
    })
    if (attach.length && res?.avatar?.id) {
      try {
        await api.post(`/api/avatars/${res.avatar.id}/photos/from-files`, { file_ids: attach })
        props.room.editDraft({ attachments: [] })
      } catch (err) {
        toast.error(avatarsErrorText(err, t, te))
      }
    }
    emit('close')
    if (res?.chat_id) await navigateTo(`/chat/${res.chat_id}`)
  })
}
</script>
