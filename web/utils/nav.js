// Sections of the left menu. Creation happens in chats (module 15, listed above
// these); everything here is management. An item shows only once its page
// exists, so modules can land one by one. `labelKey` is a locale key.
export const NAV_SECTIONS = [
  {
    key: 'work',
    items: [
      { to: '/media', icon: 'media', labelKey: 'nav.media' },
      { to: '/brand', icon: 'brand', labelKey: 'nav.brand' },
    ],
  },
  {
    key: 'manage',
    items: [
      { to: '/settings', icon: 'settings', labelKey: 'nav.settings' },
    ],
  },
]

// Tabs of the Settings screen; the label is `settings.tabs.<key>`.
export const SETTINGS_TABS = [
  { key: 'general', to: '/settings', icon: 'settings' },
  { key: 'spend', to: '/settings/spend', icon: 'spend' },
  { key: 'jobs', to: '/settings/jobs', icon: 'jobs' },
  { key: 'connection', to: '/settings/connection', icon: 'key' },
  { key: 'models', to: '/settings/models', icon: 'models' },
]

/** The Settings tab a path belongs to; "general" for /settings itself. */
export function settingsTabKey(path) {
  const tab = SETTINGS_TABS.find((t) => t.key !== 'general' && (path === t.to || path.startsWith(`${t.to}/`)))
  return tab ? tab.key : 'general'
}

// Screens that used to be menu items and now are Settings tabs: old links and
// bookmarks still open the right tab.
export const MOVED_PATHS = {
  '/spend': '/settings/spend',
  '/jobs': '/settings/jobs',
  '/connection': '/settings/connection',
  '/models': '/settings/models',
}
