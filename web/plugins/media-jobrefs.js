// Media library hooks into the jobs list: "Open" on a file job leads to the
// file in the library, and the ingest job gets a readable name.
import { registerJobKind, registerJobRef } from '~/utils/jobRefs.js'

export default defineNuxtPlugin(() => {
  registerJobRef('file', '/media?file=:id')
  registerJobKind('media.ingest', 'media.jobs.ingest')
})
