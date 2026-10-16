// Shot ideas (module 05) in the chat: a composer button in picture mode opens
// the «Ideas» window. The chat has no place for windows of other modules, so the
// window is mounted here, on the page body, with the app's context (i18n,
// router, components) and closed when the page changes.
import { createVNode, render } from 'vue'
import { chatRegisterComposerButton } from '~/utils/chatView.js'
import IdeasBriefModal from '~/components/ideas/IdeasBriefModal.vue'

export default defineNuxtPlugin((nuxtApp) => {
  let host = null

  function close() {
    if (!host) return
    render(null, host)
    host.remove()
    host = null
  }

  function open(ctx) {
    close()
    if (!ctx?.room?.chatId) return
    host = document.createElement('div')
    document.body.appendChild(host)
    const vnode = createVNode(IdeasBriefModal, { room: ctx.room, text: ctx.text || '', onClose: close })
    vnode.appContext = nuxtApp.vueApp._context
    render(vnode, host)
  }

  chatRegisterComposerButton({ id: 'ideas', icon: 'sparkles', labelKey: 'ideas.chat.button', modes: ['image'], order: 10, onClick: open })
  nuxtApp.$router.afterEach((to, from) => {
    if (to.path !== from.path) close()
  })
})
