<template>
  <section class="space-y-3">
    <div>
      <h2 class="text-base font-semibold">{{ t('updates.versions.title') }}</h2>
      <p class="text-sm muted">{{ t('updates.versions.hint') }}</p>
    </div>

    <article v-for="(r, i) in releases" :key="r.version" class="card space-y-3 p-5">
      <div class="flex flex-wrap items-start gap-3">
        <div class="min-w-0 flex-1 space-y-1">
          <div class="flex flex-wrap items-center gap-2">
            <h3 class="text-base font-semibold">{{ t('updates.versions.version', { version: r.version }) }}</h3>
            <span v-if="i === 0" class="badge bg-primary/10 text-primary">{{ t('updates.versions.newest') }}</span>
            <span v-if="r.prerelease" class="badge bg-amber-100 text-amber-900 dark:bg-amber-500/15 dark:text-amber-200">
              {{ t('updates.versions.prerelease') }}
            </span>
          </div>
          <p class="text-xs muted">
            <template v-if="r.published_at">{{ t('updates.versions.published', { date: formatDate(r.published_at, locale) }) }}</template>
            <a
              v-if="r.html_url"
              :href="r.html_url"
              target="_blank"
              rel="noopener noreferrer"
              class="ml-2 inline-flex items-center gap-1 text-primary hover:underline"
            >{{ t('updates.versions.onGithub') }}<AppIcon name="external" :size="12" /></a>
          </p>
        </div>
        <button
          v-if="canInstall"
          type="button"
          :class="i === 0 ? 'btn-primary' : 'btn-secondary'"
          :disabled="!r.installable || !!installing"
          @click="$emit('install', r.version)"
        >
          <Spinner v-if="installing === r.version" :size="16" /><AppIcon v-else name="download" :size="16" />
          {{ t('updates.versions.install') }}
        </button>
      </div>

      <p
        v-if="!r.installable"
        class="flex gap-2 rounded-card bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:bg-amber-500/10 dark:text-amber-100"
      >
        <AppIcon name="alert" :size="16" class="mt-0.5 shrink-0" />
        {{ r.min_upgrade_from
          ? t('updates.versions.needsFrom', { version: r.min_upgrade_from, current: current || '—' })
          : t('updates.versions.notInstallable') }}
      </p>
      <p v-if="r.failed_before" class="flex gap-2 text-sm text-rose-700 dark:text-rose-300">
        <AppIcon name="alert" :size="16" class="mt-0.5 shrink-0" />{{ t('updates.versions.failedBefore') }}
      </p>

      <div>
        <button
          type="button"
          class="text-sm text-primary hover:underline"
          :aria-expanded="isOpen(r.version, i)"
          @click="toggle(r.version, i)"
        >
          {{ isOpen(r.version, i) ? t('updates.notes.hide') : t('updates.notes.show') }}
        </button>
        <UpdatesNotes v-if="isOpen(r.version, i)" class="mt-2" :markdown="r.notes_md" />
      </div>
    </article>
  </section>
</template>

<script setup>
import { formatDate } from '~/utils/format.js'

defineProps({
  releases: { type: Array, required: true },
  current: { type: String, default: '' },
  canInstall: { type: Boolean, default: true },
  installing: { type: String, default: '' },
})
defineEmits(['install'])
const { t, locale } = useI18n()

// The newest release shows its notes right away; the rest open on click.
const toggled = ref({})
const isOpen = (version, index) => (version in toggled.value ? toggled.value[version] : index === 0)
const toggle = (version, index) => { toggled.value = { ...toggled.value, [version]: !isOpen(version, index) } }
</script>
