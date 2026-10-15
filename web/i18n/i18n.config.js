// vue-i18n runtime options. The messages themselves come from
// i18n/locales/<code>/*.json, listed in nuxt.config.js (one file per module).
// Plural forms for ru/uk: see utils/plural.js.
import { slavicPlural } from '~/utils/plural.js'

export default defineI18nConfig(() => ({
  legacy: false,
  fallbackLocale: 'en',
  pluralRules: { ru: slavicPlural, uk: slavicPlural },
  missingWarn: false,
  fallbackWarn: false,
}))
