/**
 * State of the "Models" screen: the registry, the roles and what each kind
 * really uses now. Reloads on `models.changed` (another tab, the connection
 * check) and after the live connection comes back.
 *
 *   const m = useModels()
 *   await m.load()
 *   m.byKind('image'), m.find(id), m.effective.value.text
 */
import { useDebounceFn } from '@vueuse/core'
import { computed, ref } from 'vue'

export const useModels = () => {
  const api = useApi()
  const { on } = useEvents()

  const items = ref([])
  const roles = ref([])
  const overview = ref({ effective: {}, checked_at: null, check_region: '' })
  const loading = ref(false)
  const loaded = ref(false)
  const error = ref(null)

  async function load() {
    loading.value = true
    try {
      const [models, roleList, ov] = await Promise.all([
        api.get('/api/models'),
        api.get('/api/models/roles'),
        api.get('/api/models/overview'),
      ])
      items.value = models.items || []
      roles.value = roleList.items || []
      overview.value = ov || overview.value
      error.value = null
      loaded.value = true
    } catch (err) {
      error.value = err
    } finally {
      loading.value = false
    }
  }

  const reload = useDebounceFn(load, 250)
  on('models.changed', reload)
  on('reconnect', reload)

  const byId = computed(() => new Map(items.value.map((m) => [m.id, m])))
  const find = (id) => byId.value.get(id) || null
  const byKind = (kind) => items.value.filter((m) => m.kind === kind)
  const effective = computed(() => overview.value?.effective || {})

  /** Put a changed model (as the API returns it) in place without a reload. */
  function replace(model) {
    if (!model?.id) return
    items.value = items.value.map((m) => (m.id === model.id ? model : m))
  }

  return { items, roles, overview, loading, loaded, error, load, reload, find, byKind, effective, replace }
}
