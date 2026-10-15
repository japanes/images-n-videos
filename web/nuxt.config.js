import { readdirSync } from 'node:fs'
import { defineNuxtConfig } from 'nuxt/config'

// The app is a single-page application served as static files by the Python
// backend (app/Dockerfile copies `.output/public` next to it). In development
// `nuxt dev` proxies the API to a backend on 127.0.0.1:8787.
const backend = process.env.VF_DEV_BACKEND || 'http://127.0.0.1:8787'

// Every module keeps its strings in its own i18n/locales/<code>/<module>.json;
// all files of a locale are merged (tests/locales.test.js forbids overlaps).
const localeFiles = (code) =>
  readdirSync(new URL(`./i18n/locales/${code}`, import.meta.url))
    .filter((name) => name.endsWith('.json'))
    .sort()
    .map((name) => `${code}/${name}`)

export default defineNuxtConfig({
  compatibilityDate: '2024-11-01',
  ssr: false,
  devtools: { enabled: false },
  telemetry: false,

  css: ['~/assets/css/app.css', '~/assets/css/transitions.css'],

  imports: {
    dirs: ['composables/**', 'stores/**'],
  },

  // Editors save atomically through `<file>.tmp.*`; never build from those.
  ignore: ['**/*.tmp.*'],

  components: [
    { path: '~/components', pathPrefix: false },
  ],

  modules: ['@nuxtjs/tailwindcss', '@pinia/nuxt', '@nuxtjs/i18n', '@vueuse/nuxt'],

  app: {
    head: {
      title: 'Vertex AI Factory',
      charset: 'utf-8',
      viewport: 'width=device-width, initial-scale=1',
      meta: [{ name: 'theme-color', content: '#141B3B' }],
      // No web fonts from Google's CDN: the app runs offline-first and sends
      // nothing anywhere except the Vertex AI requests the user starts.
      link: [{ rel: 'icon', type: 'image/svg+xml', href: '/favicon.svg' }],
    },
  },

  nitro: {
    devProxy: {
      '/api': { target: `${backend}/api`, changeOrigin: true },
      '/files': { target: `${backend}/files`, changeOrigin: true },
      '/health': { target: `${backend}/health`, changeOrigin: true },
    },
  },

  vite: {
    server: { watch: { ignored: ['**/*.tmp.*'] } },
  },

  i18n: {
    locales: [
      { code: 'ru', name: 'Русский', files: localeFiles('ru') },
      { code: 'uk', name: 'Українська', files: localeFiles('uk') },
      { code: 'en', name: 'English', files: localeFiles('en') },
    ],
    defaultLocale: 'en',
    strategy: 'no_prefix',
    detectBrowserLanguage: {
      useCookie: true,
      cookieKey: 'vf_lang',
      fallbackLocale: 'en',
      redirectOn: 'root',
    },
    vueI18n: 'i18n.config.js', // relative to i18n/
  },
})
