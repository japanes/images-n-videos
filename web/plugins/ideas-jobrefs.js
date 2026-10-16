// Shot ideas (module 05) in the jobs list: the job gets a readable name and
// «Open» leads to its card in the chat (known once the job is done).
import { registerJobKind, registerJobRef } from '~/utils/jobRefs.js'
import { ideasJobRoute } from '~/utils/ideasView.js'

export default defineNuxtPlugin(() => {
  registerJobKind('ideas.write', 'ideas.jobs.write')
  registerJobRef('ideas_set', ideasJobRoute)
})
