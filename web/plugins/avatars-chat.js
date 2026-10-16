// Avatars (module 09) in the chat: the «Avatars» button of the composer opens
// the list of avatars — call one into the request by its name (@Name), open
// its chat, or make a new one (from the attached photos too). The chat has no
// place for windows of other modules, so the window is mounted here, on the
// page body, with the app's context, and closed when the page changes.
// The avatar's own messages (kinds 'avatar.*') are components/chat/kinds/Avatar*.vue.
import { createVNode, render } from 'vue'
import { chatRegisterComposerButton } from '~/utils/chatView.js'
import AvatarsModal from '~/components/avatars/AvatarsModal.vue'

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
    const vnode = createVNode(AvatarsModal, { room: ctx.room, text: ctx.text || '', setText: ctx.setText, onClose: close })
    vnode.appContext = nuxtApp.vueApp._context
    render(vnode, host)
  }

  chatRegisterComposerButton({
    id: 'avatars', icon: 'user', labelKey: 'avatars.chat.button', modes: ['image', 'video'], order: 20, onClick: open,
  })
  nuxtApp.$router.afterEach((to, from) => {
    if (to.path !== from.path) close()
  })
})
