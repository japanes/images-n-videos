// Load what the shell needs once and keep it live from server events.
export default defineNuxtPlugin(() => {
  const meta = useMetaStore()
  const jobs = useJobsStore()
  meta.listen()
  jobs.listen()
  meta.load()
  jobs.load().catch(() => {})
})
