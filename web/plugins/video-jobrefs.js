// Video hooks into the jobs list: "Open" on a video job leads to the video in
// the chat (module 15 opens it there), and the three video jobs get readable
// names. The jobs page hides the link until /chat exists.
import { registerJobKind, registerJobRef } from '~/utils/jobRefs.js'

export default defineNuxtPlugin(() => {
  registerJobRef('video_run', '/chat?video=:id')
  registerJobKind('video.take', 'video.jobs.take')
  registerJobKind('video.extend', 'video.jobs.extend')
  registerJobKind('video.continue', 'video.jobs.continue')
})
