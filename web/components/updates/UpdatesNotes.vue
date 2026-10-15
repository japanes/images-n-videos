<template>
  <div class="space-y-2 text-sm leading-relaxed text-slate-700 dark:text-slate-200">
    <p v-if="!blocks.length" class="muted">{{ t('updates.notes.empty') }}</p>
    <template v-for="(b, i) in blocks" :key="i">
      <h3 v-if="b.type === 'heading'" class="pt-1 font-semibold text-slate-900 dark:text-white" :class="b.level <= 2 ? 'text-base' : 'text-sm'">
        <UpdatesInline :parts="b.parts" />
      </h3>
      <p v-else-if="b.type === 'paragraph'" class="break-words">
        <template v-for="(line, j) in b.lines" :key="j"><br v-if="j"><UpdatesInline :parts="line" /></template>
      </p>
      <component :is="b.ordered ? 'ol' : 'ul'" v-else-if="b.type === 'list'" class="space-y-1 pl-5" :class="b.ordered ? 'list-decimal' : 'list-disc'">
        <li v-for="(item, j) in b.items" :key="j" class="break-words" :style="item.depth ? { marginLeft: `${item.depth * 1.25}rem` } : null">
          <UpdatesInline :parts="item.parts" />
        </li>
      </component>
      <blockquote v-else-if="b.type === 'quote'" class="border-l-2 border-slate-300 pl-3 muted dark:border-slate-600">
        <p v-for="(line, j) in b.lines" :key="j" class="break-words"><UpdatesInline :parts="line" /></p>
      </blockquote>
      <pre v-else-if="b.type === 'code'" class="overflow-x-auto rounded-lg bg-slate-100 p-3 font-mono text-xs dark:bg-slate-900">{{ b.text }}</pre>
      <hr v-else-if="b.type === 'rule'" class="border-slate-200 dark:border-slate-700">
    </template>
  </div>
</template>

<script setup>
// Release notes from GitHub, shown as plain text blocks (no v-html anywhere).
import { parseNotes } from '~/utils/updatesView.js'

const props = defineProps({ markdown: { type: String, default: '' } })
const { t } = useI18n()
const blocks = computed(() => parseNotes(props.markdown))
</script>
