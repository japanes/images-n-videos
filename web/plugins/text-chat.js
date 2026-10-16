// Text on a picture (module 06) in the chat: «Text on the picture» under a
// finished picture opens the tool full screen. The chat has no place for
// windows of other modules, so the tool is mounted here, on the page body, with
// the app's context (i18n, router, components) and closed when the page changes.
import { createVNode, render } from 'vue'
import { chatRegisterImageAction } from '~/utils/chatView.js'
import TextTool from '~/components/text/TextTool.vue'

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
    const { room, message, item } = ctx || {}
    if (!room?.chatId || !message?.id || !item?.frame_id || !item?.file_id) return
    host = document.createElement('div')
    document.body.appendChild(host)
    const vnode = createVNode(TextTool, { room, message, item, onClose: close })
    vnode.appContext = nuxtApp.vueApp._context
    render(vnode, host)
  }

  chatRegisterImageAction({ id: 'text', icon: 'text', labelKey: 'text.chat.action', order: 20, onClick: open })
  nuxtApp.$router.afterEach((to, from) => {
    if (to.path !== from.path) close()
  })
})
