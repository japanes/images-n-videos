/**
 * Background jobs that are queued or running, kept live from SSE. The jobs
 * indicator in the sidebar and any screen showing progress read from here.
 */
import { defineStore } from 'pinia'

const ACTIVE = new Set(['queued', 'running'])

export const useJobsStore = defineStore('jobs', {
  state: () => ({ active: [], loaded: false }),
  getters: {
    running: (s) => s.active.filter((j) => j.status === 'running'),
    count: (s) => s.active.length,
    byRef: (s) => (refType, refId) => s.active.filter((j) => j.ref_type === refType && j.ref_id === refId),
  },
  actions: {
    async load() {
      try {
        const res = await useApi().get('/api/jobs', { active: true })
        this.active = res.items
      } finally {
        this.loaded = true
      }
    },
    upsert(job) {
      const i = this.active.findIndex((j) => j.id === job.id)
      if (!ACTIVE.has(job.status)) {
        if (i >= 0) this.active.splice(i, 1)
        return
      }
      if (i >= 0) this.active[i] = { ...this.active[i], ...job }
      else this.active.unshift(job)
    },
    listen() {
      const { on } = useEvents()
      on('job.updated', (job) => this.upsert(job))
      on('job.progress', (p) => {
        const j = this.active.find((x) => x.id === p.id)
        if (j) { j.progress = p.progress; j.progress_note = p.note }
      })
      on('reconnect', () => this.load())
    },
    async cancel(id) {
      const job = await useApi().post(`/api/jobs/${id}/cancel`)
      this.upsert(job)
      return job
    },
  },
})
