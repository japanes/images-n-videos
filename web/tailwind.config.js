import colors from 'tailwindcss/colors'

/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: [
    './components/**/*.{js,vue}',
    './layouts/**/*.vue',
    './pages/**/*.vue',
    './composables/**/*.js',
    './utils/**/*.js',
    './app.vue',
    './error.vue',
  ],
  theme: {
    extend: {
      colors: {
        // The dark end of slate is re-cut in the brand navy (same as factory):
        // dark surfaces use 700–950, light mode uses 600 and lighter for text.
        slate: {
          ...colors.slate,
          700: '#30385a',
          800: '#222a4f',
          900: '#141b3b',
          950: '#0c1022',
        },
        primary: { DEFAULT: '#3494E6', light: '#5DA9EC', dark: '#1C68AB' },
        secondary: { DEFAULT: '#EC6EAD', light: '#F3A5CC', dark: '#C94B8C' },
        accent: { DEFAULT: '#9081CA', light: '#B3A8DC', dark: '#6E5FA8' },
      },
      fontFamily: {
        body: ['Inter', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
      borderRadius: { card: '12px', button: '8px', input: '8px', modal: '16px', badge: '9999px' },
      boxShadow: {
        card: '0 1px 3px 0 rgba(0, 0, 0, 0.1), 0 1px 2px -1px rgba(0, 0, 0, 0.1)',
        'card-hover': '0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -2px rgba(0, 0, 0, 0.1)',
        modal: '0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.1)',
      },
    },
  },
  plugins: [],
}
