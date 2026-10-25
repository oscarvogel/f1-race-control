/**
 * Opciones del selector de sesiones del Gran Premio.
 *
 * Se usa en los paneles post-sesion (analisis, evolucion de posiciones y
 * estrategia): todas miran la misma sesion, la que guarda el store de
 * analisis.
 */
import { computed } from 'vue'
import { useRaceStore } from '@/stores/race'

export interface SessionOptionItem {
  value: string
  label: string
  hint?: string
}

export function useSessionOptions() {
  const store = useRaceStore()

  const opciones = computed<SessionOptionItem[]>(() =>
    store.sessionCatalog
      .filter((option) => option.session_key)
      .map((option) => ({
        value: option.session_key,
        label: option.session_name || option.session_type || option.session_key,
        hint: option.start_time_utc
          ? new Date(option.start_time_utc).toLocaleDateString('es-AR', {
              day: '2-digit',
              month: '2-digit',
            })
          : undefined,
      })),
  )

  /** La sesion que se esta mirando ahora en el dashboard. */
  const sesionDelPanel = computed<string | null>(() => {
    if (store.activeSessionKey) return store.activeSessionKey
    return store.session?.provider_session_id ?? null
  })

  return { opciones, sesionDelPanel }
}
