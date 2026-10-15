<template>
  <a
    :href="href"
    target="_blank"
    rel="noopener noreferrer"
    class="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
  >{{ t(`connection.links.${id}`) }}<AppIcon name="external" :size="12" /></a>
</template>

<script setup>
// A Google Cloud console page; project pages open for the user's project.
import { consoleUrl } from '~/utils/connectionView.js'

const props = defineProps({
  id: { type: String, required: true },
  projectId: { type: String, default: '' },
})
const { t } = useI18n()
const href = computed(() => consoleUrl(props.id, props.projectId))
</script>
