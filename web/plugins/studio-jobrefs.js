// Image studio hooks into the jobs list: "Open" on a frame job leads to the
// frame in the chat (module 15 opens the studio there), and the drawing job
// gets a readable name. The jobs page hides the link until /chat exists.
import { registerJobKind, registerJobRef } from '~/utils/jobRefs.js'

export default defineNuxtPlugin(() => {
  registerJobRef('frame', '/chat?frame=:id')
  registerJobRef('work', '/chat?work=:id')
  registerJobKind('studio.frame', 'studio.jobs.frame')
})
