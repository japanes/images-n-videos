// Sections of the left menu. Creation happens in chats (module 15, listed above
// these); everything here is management. An item shows only once its page
// exists, so modules can land one by one. `labelKey` is a locale key.
export const NAV_SECTIONS = [
  {
    key: 'work',
    items: [
      { to: '/media', icon: 'media', labelKey: 'nav.media' },
      { to: '/library', icon: 'library', labelKey: 'nav.library' },
      { to: '/brand', icon: 'brand', labelKey: 'nav.brand' },
    ],
  },
  {
    key: 'manage',
    items: [
      { to: '/spend', icon: 'spend', labelKey: 'nav.spend' },
      { to: '/jobs', icon: 'jobs', labelKey: 'nav.jobs' },
      { to: '/connection', icon: 'key', labelKey: 'nav.connection' },
      { to: '/models', icon: 'models', labelKey: 'nav.models' },
      { to: '/settings', icon: 'settings', labelKey: 'nav.settings' },
      { to: '/updates', icon: 'update', labelKey: 'nav.updates' },
    ],
  },
]
