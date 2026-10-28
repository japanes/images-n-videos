import { MOVED_PATHS } from '~/utils/nav.js'

// Old menu addresses (/spend, /jobs, …) open the matching Settings tab, query included.
export default defineNuxtRouteMiddleware((to) => {
  const path = to.path.length > 1 ? to.path.replace(/\/+$/, '') : to.path
  const target = MOVED_PATHS[path]
  if (target) return navigateTo({ path: target, query: to.query, hash: to.hash }, { replace: true })
})
