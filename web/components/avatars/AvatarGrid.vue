<template>
  <!--
    The 36 shots of an avatar on the whole screen, in groups (portraits, angles,
    body, scenes, speech, emotions, gaze). A click opens the shot: change its
    prompt, draw it again, fix it, put an own photo in it. «Choose» ticks shots
    to draw again in one go. Closing it returns to the same chat.
  -->
  <ModalShell open size="full" body-class="p-4 sm:p-5" @close="emit('close')">
    <template #header>
      <div class="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-1">
        <h2 class="min-w-0 truncate text-base font-semibold">{{ t('avatars.grid.title', { name: view.name }) }}</h2>
        <span class="text-xs muted">{{ t('avatars.card.count', { done: c.done, total: c.total }) }}</span>
        <span v-if="c.busy" class="inline-flex items-center gap-1 text-xs muted"><Spinner :size="10" />{{ t('avatars.pack.busy', { n: c.busy }) }}</span>
      </div>
    </template>

    <div class="space-y-5">
      <!-- the tools -->
      <div class="flex flex-wrap items-center gap-2">
        <template v-if="!choosing">
          <PriceButton
            icon="sparkles"
            :label="t('avatars.pack.finish', { n: finishEst.est.value?.count || c.empty }, finishEst.est.value?.count || c.empty)"
            :usd="finishEst.usd.value"
            :disabled="Boolean(finishBlock) || finishEst.usd.value === null || Boolean(busy)"
            :busy="busy === 'finish'"
            @click="finish"
          />
          <button type="button" class="btn-secondary btn-sm" :disabled="!view.face" @click="startChoosing">
            <AppIcon name="check" :size="14" />{{ t('avatars.grid.choose') }}
          </button>
        </template>
        <template v-else>
          <PriceButton
            icon="refresh"
            :label="t('avatars.grid.redrawChosen', { n: chosen.length }, chosen.length)"
            :usd="chosen.length ? packEst.usd.value : null"
            :disabled="!chosen.length || packEst.usd.value === null || Boolean(busy)"
            :busy="busy === 'pack'"
            @click="drawChosen"
          />
          <button type="button" class="btn-ghost btn-sm" @click="stopChoosing">{{ t('common.cancel') }}</button>
          <span class="text-xs muted">{{ t('avatars.grid.chooseHint') }}</span>
        </template>
        <a v-if="c.done && !choosing" :href="avatarsExportUrl(view.id)" class="btn-secondary btn-sm" download>
          <AppIcon name="download" :size="14" />{{ t('avatars.pack.zip') }}
        </a>
        <button v-if="view.busy" type="button" class="btn-ghost btn-sm" :disabled="Boolean(busy)" @click="stopAll">
          <AppIcon name="stop" :size="14" />{{ t('avatars.pack.stop') }}
        </button>
      </div>
      <p v-if="!choosing && finishBlock && finishBlock !== 'avatar_nothing_to_draw'" class="text-xs text-amber-700 dark:text-amber-300">
        {{ avatarsReasonText(finishBlock, t, te) }}
      </p>
      <p v-else-if="!choosing && finishTime" class="text-xs muted">{{ finishTime }} · {{ t('avatars.pack.twoAtOnce') }}</p>
      <p v-else-if="choosing && chosen.length && packTime" class="text-xs muted">{{ packTime }}</p>

      <!-- the groups -->
      <section v-for="g in groups" :key="g.category" class="space-y-2">
        <h3 class="text-sm font-semibold">
          {{ te(`avatars.categories.${g.category}`) ? t(`avatars.categories.${g.category}`) : g.category }}
          <span class="ml-1 text-xs font-normal muted">{{ groupDone(g) }}/{{ g.slots.length }}</span>
        </h3>
        <ul class="grid grid-cols-3 gap-2 sm:grid-cols-4 md:grid-cols-6 xl:grid-cols-8">
          <li v-for="s in g.slots" :key="s.id">
            <button
              type="button"
              class="block w-full rounded-card text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="choosing && !canChoose(s)"
              :aria-pressed="choosing ? chosen.includes(s.shot_code) : undefined"
              @click="onTile(s)"
            >
              <AvatarTile
                :photo="s"
                :title="avatarsShotTitle(s.shot_code, t, te, s.title)"
                show-number
                :selectable="choosing && canChoose(s)"
                :selected="choosing && chosen.includes(s.shot_code)"
              />
            </button>
          </li>
        </ul>
      </section>
    </div>

    <AvatarSlotDialog
      v-if="openId"
      :view="view"
      :photo-id="openId"
      @open="openId = $event"
      @close="openId = null"
    />
  </ModalShell>
</template>

<script setup>
import {
  AVATAR_FACE_CODE, AVATAR_SHOT_COUNT, avatarsExportUrl, avatarsGroupSlots, avatarsPackBlock,
  avatarsReasonText, avatarsShotTitle, avatarsSlotBusy, avatarsTimeText,
} from '~/utils/avatarsView.js'
import { useAvatarAction, useAvatarEstimate } from '~/composables/useAvatars.js'

const props = defineProps({
  view: { type: Object, required: true },
})
const emit = defineEmits(['close'])
const { t, te } = useI18n()
const api = useApi()
const toast = useToast()
const { confirm } = useConfirm()
const { busy, act } = useAvatarAction()

const base = computed(() => `/api/avatars/${props.view.id}`)
const c = computed(() => ({ done: 0, total: AVATAR_SHOT_COUNT, busy: 0, failed: 0, empty: 0, ...(props.view.counts || {}) }))
const groups = computed(() => avatarsGroupSlots(props.view.slots))
const groupDone = (g) => g.slots.filter((s) => s.file_id).length

const openId = ref(null)
const choosing = ref(false) // ticking shots to draw again
const chosen = ref([]) // their shot codes

// ── «draw the rest» ──

const finishBlock = computed(() => avatarsPackBlock(props.view))
const finishEst = useAvatarEstimate(
  () => props.view.id,
  () => (finishBlock.value || choosing.value ? null : { action: 'finish' }),
  () => [props.view.updated_at, props.view.image_model_id, c.value.empty, choosing.value],
)
const finishTime = computed(() => avatarsTimeText(finishEst.est.value?.time, t))

async function finish() {
  const res = await act('finish', () => api.post(`${base.value}/finish`))
  tellSkipped(res)
}

// ── ticked shots drawn again ──

const canChoose = (s) => s.shot_code !== AVATAR_FACE_CODE && !avatarsSlotBusy(s)

const packEst = useAvatarEstimate(
  () => props.view.id,
  () => (choosing.value && chosen.value.length ? { action: 'pack', codes: [...chosen.value] } : null),
  () => [props.view.updated_at, props.view.image_model_id, chosen.value.join(',')],
)
const packTime = computed(() => avatarsTimeText(packEst.est.value?.time, t))

function startChoosing() {
  chosen.value = []
  choosing.value = true
}

function stopChoosing() {
  choosing.value = false
  chosen.value = []
}

function onTile(s) {
  if (!choosing.value) {
    openId.value = s.id
    return
  }
  if (!canChoose(s)) return
  chosen.value = chosen.value.includes(s.shot_code)
    ? chosen.value.filter((code) => code !== s.shot_code)
    : [...chosen.value, s.shot_code]
}

async function drawChosen() {
  const res = await act('pack', () => api.post(`${base.value}/pack`, { codes: [...chosen.value] }))
  if (!res) return
  tellSkipped(res)
  stopChoosing()
}

// ── stop ──

async function stopAll() {
  if (!await confirm({ message: t('avatars.pack.stopAsk'), confirmLabel: t('avatars.pack.stop'), tone: 'danger' })) return
  await act('stop', () => api.post(`${base.value}/cancel`))
}

function tellSkipped(res) {
  const skipped = res?.skipped || []
  if (!skipped.length) return
  const reasons = [...new Set(skipped.map((s) => avatarsReasonText(s.reason, t, te)).filter(Boolean))]
  toast.info([t('avatars.pack.skipped', { n: skipped.length }, skipped.length), ...reasons].join(' '))
}
</script>
