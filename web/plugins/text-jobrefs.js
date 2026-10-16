// Text on a picture (module 06) in the jobs list: the background job gets a
// readable name and «Open» leads to the chat message the tool was opened from.
import { registerJobKind, registerJobRef } from '~/utils/jobRefs.js'
import { textJobRoute } from '~/utils/textView.js'

export default defineNuxtPlugin(() => {
  registerJobKind('text.background', 'text.jobs.background')
  registerJobRef('text_design', textJobRoute)
})
