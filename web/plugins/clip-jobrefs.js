// Clip editor hooks into the jobs list: "Open" on a clip job leads back to the
// project in the editor, and the three clip jobs get readable names.
import { registerJobKind, registerJobRef } from '~/utils/jobRefs.js'

export default defineNuxtPlugin(() => {
  registerJobRef('clip', '/clip/:id')
  registerJobKind('clip.export', 'clip.jobs.export')
  registerJobKind('clip.preview', 'clip.jobs.preview')
  registerJobKind('clip.transcribe', 'clip.jobs.transcribe')
})
