<template>
  <article class="card">
    <!-- Header: name, kind, one-off badge, delete -->
    <header class="flex flex-wrap items-center gap-2 border-b border-slate-200 px-3 py-2.5 dark:border-slate-700">
      <BrandTextField
        class="min-w-0 flex-1 basis-40"
        :model-value="subject.name"
        :maxlength="120"
        :placeholder="t('brand.subjects.card.namePlaceholder')"
        input-class="input border-transparent bg-transparent px-2 py-1 font-medium hover:border-slate-300 dark:border-transparent dark:bg-transparent dark:hover:border-slate-600"
        @save="(v) => patch({ name: v })"
      />
      <select
        class="input w-32 py-1 text-xs"
        :value="subject.kind"
        :aria-label="t('brand.subjects.kind')"
        :disabled="busy"
        @change="patch({ kind: $event.target.value })"
      >
        <option v-for="k in SUBJECT_KINDS" :key="k" :value="k">{{ t(`brand.subjects.kinds.${k}`) }}</option>
      </select>
      <template v-if="subject.one_off">
        <span class="badge bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-200">{{ t('brand.subjects.card.oneOff') }}</span>
        <button type="button" class="btn-ghost btn-sm" :disabled="busy" @click="promote">
          <AppIcon name="library" :size="14" />{{ t('brand.subjects.card.promote') }}
        </button>
      </template>
      <button
        type="button"
        class="btn-ghost p-2 text-rose-600 dark:text-rose-400"
        :disabled="busy"
        :title="t('brand.subjects.card.remove')"
        :aria-label="t('brand.subjects.card.remove')"
        @click="removeSubject"
      >
        <AppIcon name="trash" :size="16" />
      </button>
    </header>

    <div class="space-y-3 p-3">
      <!-- Photos. The first few are ringed: only those reach the model, and the order is the person's to change. -->
      <div class="grid grid-cols-3 gap-2 sm:grid-cols-4 lg:grid-cols-6">
        <div
          v-for="(photo, i) in photos"
          :key="photo.id"
          class="group relative aspect-square overflow-hidden rounded-button border"
          :class="i < sent ? 'border-primary/60 ring-1 ring-primary/30' : 'border-slate-200 opacity-70 dark:border-slate-600'"
        >
          <img v-if="photo.file" :src="photo.file.thumb_url || photo.file.url" alt="" loading="lazy" class="h-full w-full object-cover">
          <span
            class="absolute bottom-1 left-1 rounded bg-slate-900/70 px-1 text-[10px] leading-4 text-white tabular-nums"
            :title="i < sent ? t('brand.subjects.card.sentHint', { n: sent }) : t('brand.subjects.card.notSentHint')"
          >{{ i + 1 }}</span>
          <span
            v-if="photo.angle"
            class="absolute bottom-1 right-1 max-w-[70%] truncate rounded bg-slate-900/70 px-1 text-[10px] leading-4 text-white group-hover:hidden"
            :title="photo.angle"
          >{{ photo.angle }}</span>

          <div class="absolute inset-x-1 top-1 flex items-center justify-between opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
            <button
              v-if="i > 0"
              type="button"
              class="inline-flex h-6 w-6 items-center justify-center rounded bg-slate-900/70 text-white hover:bg-slate-900"
              :disabled="busy"
              :title="t('brand.subjects.card.moveUp')"
              :aria-label="t('brand.subjects.card.moveUp')"
              @click="movePhoto(i)"
            >
              <AppIcon name="chevron-left" :size="14" />
            </button>
            <span v-else />
            <button
              type="button"
              class="inline-flex h-6 w-6 items-center justify-center rounded bg-slate-900/70 text-white hover:bg-rose-600"
              :disabled="busy"
              :title="t('brand.subjects.card.removePhoto')"
              :aria-label="t('brand.subjects.card.removePhoto')"
              @click="removePhoto(photo)"
            >
              <AppIcon name="close" :size="14" />
            </button>
          </div>

          <!-- Angle label: optional, but it stops the model from drawing the same view every time. -->
          <input
            :value="photo.angle || ''"
            type="text"
            maxlength="60"
            class="absolute inset-x-0 bottom-0 h-0 border-0 bg-white/95 px-1 text-[11px] text-slate-700 opacity-0 transition-all focus:h-6 focus:opacity-100 focus:outline-none group-hover:h-6 group-hover:opacity-100 dark:bg-slate-900/95 dark:text-slate-200"
            :placeholder="t('brand.subjects.card.anglePlaceholder')"
            :aria-label="t('brand.subjects.card.anglePlaceholder')"
            @change="saveAngle(photo, $event.target.value)"
            @keydown.enter.prevent="$event.target.blur()"
          >
        </div>

        <button
          v-if="photos.length < maxPhotos"
          type="button"
          class="flex aspect-square items-center justify-center rounded-button border border-dashed border-slate-300 text-slate-400 transition-colors hover:border-primary hover:text-primary disabled:opacity-40 dark:border-slate-600"
          :disabled="uploading"
          :title="t('brand.subjects.card.addPhoto')"
          :aria-label="t('brand.subjects.card.addPhoto')"
          @click="fileInput?.click()"
        >
          <Spinner v-if="uploading" :size="16" /><AppIcon v-else name="plus" :size="20" />
        </button>
        <input ref="fileInput" type="file" class="hidden" :accept="IMAGE_ACCEPT" multiple @change="onFiles">
      </div>

      <p v-if="!photos.length" class="text-xs text-amber-700 dark:text-amber-300">{{ t('brand.subjects.card.noPhotos') }}</p>
      <p v-else class="text-xs muted">{{ t('brand.subjects.card.photosHint', { sent, max: maxPhotos }) }}</p>

      <!-- Description: what the model is told the thing IS, on top of the photos. -->
      <div class="space-y-2">
        <div class="flex flex-wrap items-center gap-2">
          <span class="text-xs font-medium muted">{{ t('brand.subjects.card.description') }}</span>
          <span
            v-if="subject.description"
            class="badge"
            :class="subject.description_source === 'photo'
              ? 'bg-violet-100 text-violet-800 dark:bg-violet-500/15 dark:text-violet-200'
              : 'bg-slate-100 text-slate-700 dark:bg-slate-700 dark:text-slate-200'"
          >
            {{ subject.description_source === 'photo' ? t('brand.subjects.card.sourcePhoto') : t('brand.subjects.card.sourceManual') }}
          </span>
          <span class="flex-1" />
          <PriceButton
            variant="secondary"
            class="btn-sm"
            icon="sparkles"
            :label="t('brand.subjects.card.describe')"
            :estimate="estimate"
            :disabled="!photos.length || busy"
            :busy="describing"
            @click="describe(false)"
          />
        </div>
        <p class="text-xs muted">{{ photos.length ? t('brand.subjects.card.describeHint', { n: describePhotos }) : t('brand.subjects.card.describeNeedsPhoto') }}</p>

        <BrandTextField
          :model-value="subject.describe_focus"
          :maxlength="300"
          :placeholder="t('brand.subjects.card.focusPlaceholder')"
          :aria-label="t('brand.subjects.card.focusPlaceholder')"
          :title="t('brand.subjects.card.focusHint')"
          input-class="input border-dashed py-1.5 text-xs focus:border-solid"
          @save="saveFocus"
        />
        <BrandTextField
          :model-value="subject.description"
          multiline
          :rows="3"
          :maxlength="2000"
          :placeholder="t('brand.subjects.card.descriptionPlaceholder')"
          :aria-label="t('brand.subjects.card.description')"
          input-class="input resize-y text-sm"
          @save="(v) => patch({ description: v })"
        />
      </div>
    </div>
  </article>
</template>

<script setup>
/**
 * One subject: name, kind, photos and description. Every write returns the
 * fresh subject, which goes up to the list with `updated`.
 *
 * Photo order matters: only the first `limits.sent` photos reach the image
 * model, so those tiles are ringed and the rest dimmed.
 */
import { DESCRIBE_PHOTOS, IMAGE_ACCEPT, SUBJECT_KINDS, brandErrorText, describeEstimate, photoIdsMovedForward } from '~/utils/brand.js'

const props = defineProps({
  subject: { type: Object, required: true },
  limits: { type: Object, default: () => ({ photos: 12, sent: 4, describe_photos: DESCRIBE_PHOTOS }) },
})
const emit = defineEmits(['updated', 'removed'])
const { t, te } = useI18n()
const api = useApi()
const toast = useToast()
const { confirm } = useConfirm()

const base = computed(() => `/api/brand/subjects/${props.subject.id}`)
const photos = computed(() => props.subject.photos || [])
const maxPhotos = computed(() => props.limits.photos || 12)
const sent = computed(() => props.limits.sent || 4)
const describePhotos = computed(() => Math.min(props.limits.describe_photos || DESCRIBE_PHOTOS, photos.value.length || DESCRIBE_PHOTOS))
const estimate = computed(() => describeEstimate(photos.value.length))

const busy = ref(false)
const uploading = ref(false)
const describing = ref(false)
const fileInput = ref(null)
const focusText = ref(props.subject.describe_focus || '')
watch(() => props.subject.describe_focus, (v) => { focusText.value = v || '' })

const showError = (err) => toast.error(brandErrorText(err, t, te))

async function run(fn) {
  busy.value = true
  try {
    const subject = await fn()
    if (subject?.id) emit('updated', subject)
    return subject
  } catch (err) {
    showError(err)
    return null
  } finally {
    busy.value = false
  }
}

const patch = (body) => run(() => api.patch(base.value, body))

function saveFocus(value) {
  focusText.value = value
  patch({ describe_focus: value })
}

async function promote() {
  if (await run(() => api.post(`${base.value}/promote`))) toast.success(t('brand.subjects.card.promoted'))
}

async function removeSubject() {
  const name = props.subject.name || t('brand.subjects.card.unnamed')
  const ok = await confirm({ message: t('brand.subjects.card.removeConfirm', { name }), confirmLabel: t('common.delete'), tone: 'danger' })
  if (!ok) return
  busy.value = true
  try {
    await api.del(base.value)
    emit('removed', props.subject.id)
  } catch (err) {
    showError(err)
  } finally {
    busy.value = false
  }
}

const movePhoto = (i) => run(() => api.put(`${base.value}/photos/order`, { ids: photoIdsMovedForward(photos.value, i) }))

async function removePhoto(photo) {
  const ok = await confirm({ message: t('brand.subjects.card.removePhotoConfirm'), confirmLabel: t('common.delete'), tone: 'danger' })
  if (ok) await run(() => api.del(`/api/brand/subject-photos/${photo.id}`))
}

function saveAngle(photo, value) {
  if ((value || '').trim() === (photo.angle || '')) return
  run(() => api.patch(`/api/brand/subject-photos/${photo.id}`, { angle: value }))
}

async function onFiles(e) {
  let files = [...(e.target.files || [])]
  e.target.value = ''
  if (!files.length) return
  const room = maxPhotos.value - photos.value.length
  if (files.length > room) {
    toast.error(t('brand.subjects.card.photoMax', { n: maxPhotos.value }))
    files = files.slice(0, Math.max(0, room))
  }
  uploading.value = true
  for (const file of files) {
    try {
      emit('updated', await api.upload(`${base.value}/photos`, file, { angle: '' }))
    } catch (err) {
      toast.error(`${file.name}: ${brandErrorText(err, t, te)}`)
    }
  }
  uploading.value = false
}

async function describe(force) {
  describing.value = true
  try {
    const res = await api.post(`${base.value}/describe`, { force, focus: focusText.value })
    emit('updated', res.subject)
    toast.success(t('brand.subjects.card.described'))
  } catch (err) {
    if (err.code === 'subject_description_manual' && !force) {
      describing.value = false
      const ok = await confirm({
        message: t('brand.subjects.card.describeOverwrite'),
        confirmLabel: t('brand.subjects.card.describeOverwriteConfirm'),
      })
      if (ok) await describe(true)
      return
    }
    showError(err)
  } finally {
    describing.value = false
  }
}
</script>
