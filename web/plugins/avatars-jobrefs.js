// Avatars (module 09) in the jobs list: the two avatar jobs get readable names
// and «Open» leads to the message of the avatar chat the job belongs to.
import { registerJobKind, registerJobRef } from '~/utils/jobRefs.js'
import { avatarsJobRoute } from '~/utils/avatarsView.js'

export default defineNuxtPlugin(() => {
  registerJobKind('avatar.photo', 'avatars.jobs.photo')
  registerJobKind('avatar.describe', 'avatars.jobs.describe')
  registerJobRef('avatar', avatarsJobRoute)
  registerJobRef('avatar_photo', avatarsJobRoute)
})
