import globals from 'globals'
import pluginVue from 'eslint-plugin-vue'

const noNativeDialogs = {
  'no-restricted-globals': ['error',
    { name: 'confirm', message: 'Use useConfirm() — the app has one confirmation dialog.' },
    { name: 'alert', message: 'Use useConfirm({ hideCancel: true }) or a toast.' },
    { name: 'prompt', message: 'Use an app modal.' },
  ],
  'no-restricted-properties': ['error',
    { object: 'window', property: 'confirm', message: 'Use useConfirm() — the app has one confirmation dialog.' },
    { object: 'window', property: 'alert', message: 'Use useConfirm({ hideCancel: true }) or a toast.' },
    { object: 'window', property: 'prompt', message: 'Use an app modal.' },
  ],
}

export default [
  { ignores: ['.nuxt/**', '.output/**', 'dist/**', 'node_modules/**'] },
  ...pluginVue.configs['flat/essential'],
  {
    files: ['**/*.{js,vue}'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: { ...globals.browser, ...globals.node },
    },
    rules: {
      ...noNativeDialogs,
      'no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      'no-undef': 'off', // Nuxt auto-imports (ref, computed, useI18n…) are globals at build time
      'vue/multi-word-component-names': 'off',
      'vue/no-v-html': 'error',
    },
  },
]
