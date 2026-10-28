/**
 * What the shell needs to know about the backend: version, stub mode, whether
 * a Google key is connected.
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
  }),
  actions: {
    async load() {
      try {
        const m = await useApi().get('/api/meta')
        this.version = m.version
        this.googleMode = m.google_mode
        this.stub = !!m.stub
        this.hasKey = !!m.has_key
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
      on('reconnect', () => this.load())
    },
  },
})
