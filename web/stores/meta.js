/**
 * What the shell needs to know about the backend: version, stub mode, whether
 * a Google key is connected, whether new jobs are paused (an update is going on).
 */
import { defineStore } from 'pinia'

export const useMetaStore = defineStore('meta', {
  state: () => ({
    loaded: false,
    offline: false,
    version: '',
    googleMode: 'live',
    stub: false,
    hasKey: false,
    jobsPaused: null,
    repo: '',
  }),
  actions: {
    async load() {
      try {
        const m = await useApi().get('/api/meta')
        this.version = m.version
        this.googleMode = m.google_mode
        this.stub = !!m.stub
        this.hasKey = !!m.has_key
        this.jobsPaused = m.jobs_paused || null
        this.repo = m.repo || ''
        this.offline = false
      } catch {
        this.offline = true
      } finally {
        this.loaded = true
      }
    },
    listen() {
      const { on } = useEvents()
      on('google.key_changed', () => this.load())
      on('jobs.paused', (d) => { this.jobsPaused = d.reason || null })
      on('reconnect', () => this.load())
    },
  },
})
