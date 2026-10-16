<template>
  <ChatRoom :chat-id="chatId" :focus-message="focusMessage" />
</template>

<script setup>
import { chatQueryId } from '~/utils/chatView.js'

// One chat. `?message=<id>` scrolls to that message and marks it for a moment.
const route = useRoute()
const chatId = computed(() => chatQueryId(route.params.id))
const focusMessage = computed(() => chatQueryId(route.query.message))
</script>
