/**
 * Estado del analisis post-sesion y del campeonato.
 *
 * Son dos fuentes distintas y no cambian cada 2 s como el snapshot en vivo:
 * una sesion terminada no cambia mas, y el campeonato se actualiza una vez
 * por ronda. Por eso se piden solo cuando el usuario cambia de sesion, de
 * piloto de referencia o de sesion de comparacion.
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '@/services/api'
import type {
  Championship,
  PositionHistory,
  SectorAnalysis,
  Strategy,
} from '@/types'

export const useAnalysisStore = defineStore('analysis', () => {
  const payload = ref<SectorAnalysis | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  /** Sesion que se esta analizando. */
  const sessionKey = ref<string | null>(null)
  /** Piloto contra el que se mide el delta (null = el mas rapido). */
  const referenceDriver = ref<string | null>(null)
  /** Sesion de comparacion (null = sin comparacion). */
  const compareSessionKey = ref<string | null>(null)

  const championship = ref<Championship | null>(null)
  const championshipLoading = ref(false)
  const championshipError = ref<string | null>(null)

  /** Evolucion de posiciones por vuelta. */
  const positions = ref<PositionHistory | null>(null)
  const positionsLoading = ref(false)
  const positionsError = ref<string | null>(null)

  /** Estrategia de neumaticos. */
  const strategy = ref<Strategy | null>(null)
  const strategyLoading = ref(false)
  const strategyError = ref<string | null>(null)

  /** Filas del analisis, ordenadas por tiempo de vuelta (ya llegan asi). */
  const rows = computed(() => payload.value?.rows ?? [])

  /** El piloto de referencia, con su fila. */
  const referenceRow = computed(
    () => rows.value.find((row) => row.driver_number === referenceDriver.value) ?? null,
  )

  async function loadAnalysis(
    key: string | null,
    options: { reference?: string | null; compare?: string | null } = {},
  ): Promise<void> {
    if (!key) {
      payload.value = null
      return
    }
    loading.value = true
    error.value = null
    try {
      const data = await api.sectorAnalysis(key, {
        reference: options.reference ?? referenceDriver.value,
        compare: options.compare ?? compareSessionKey.value,
      })
      if (data.found === false) {
        payload.value = null
        error.value = data.error ?? data.reason ?? 'No hay datos para analizar.'
        return
      }
      payload.value = data as SectorAnalysis
      // El backend devuelve el piloto de referencia que uso (por defecto, el
      // mas rapido de la sesion). Se sincroniza para no volver a pedir lo
      // mismo cuando el panel elige ese piloto.
      referenceDriver.value = (data.reference_driver as string | undefined) ?? referenceDriver.value
    } catch (err) {
      payload.value = null
      error.value = err instanceof Error ? err.message : String(err)
    } finally {
      loading.value = false
    }
  }

  /** Cambia el piloto de referencia y recalcula los deltas. */
  async function setReference(driver: string | null): Promise<void> {
    referenceDriver.value = driver
    await loadAnalysis(sessionKey.value, { reference: driver })
  }

  /** Cambia la sesion de comparacion. */
  async function setCompare(session: string | null): Promise<void> {
    compareSessionKey.value = session
    await loadAnalysis(sessionKey.value, { compare: session })
  }

  /**
   * Cambia la sesion analizada.
   *
   * Los tres paneles post-sesion (sectores, evolucion de posiciones y
   * estrategia) miran la misma sesion: al cambiarla se recargan todos y se
   * limpian la referencia y la sesion de comparacion, que son de la sesion
   * anterior.
   */
  async function setSession(key: string | null): Promise<void> {
    sessionKey.value = key
    referenceDriver.value = null
    compareSessionKey.value = null
    await Promise.all([loadAnalysis(key), loadPositions(key), loadStrategy(key)])
  }

  /** Evolucion de posiciones: la posicion de cada piloto al final de cada vuelta. */
  async function loadPositions(key: string | null): Promise<void> {
    if (!key) {
      positions.value = null
      positionsError.value = null
      return
    }
    positionsLoading.value = true
    positionsError.value = null
    try {
      const data = await api.positionHistory(key)
      if (data.found === false) {
        positions.value = null
        positionsError.value = data.error ?? data.reason ?? 'No hay datos de posiciones.'
        return
      }
      positions.value = data as PositionHistory
    } catch (err) {
      positions.value = null
      positionsError.value = err instanceof Error ? err.message : String(err)
    } finally {
      positionsLoading.value = false
    }
  }

  /** Estrategia de neumaticos: stints, paradas y mejor vuelta de cada tramo. */
  async function loadStrategy(key: string | null): Promise<void> {
    if (!key) {
      strategy.value = null
      strategyError.value = null
      return
    }
    strategyLoading.value = true
    strategyError.value = null
    try {
      const data = await api.strategy(key)
      if (data.found === false) {
        strategy.value = null
        strategyError.value = data.error ?? data.reason ?? 'No hay datos de neumaticos.'
        return
      }
      strategy.value = data as Strategy
    } catch (err) {
      strategy.value = null
      strategyError.value = err instanceof Error ? err.message : String(err)
    } finally {
      strategyLoading.value = false
    }
  }

  async function loadChampionship(): Promise<void> {
    if (championshipLoading.value) return
    championshipLoading.value = true
    championshipError.value = null
    try {
      const data = await api.championship()
      if (data.found === false) {
        championship.value = null
        championshipError.value = data.error ?? 'No se pudo leer el campeonato.'
        return
      }
      championship.value = data as Championship
    } catch (err) {
      championship.value = null
      championshipError.value = err instanceof Error ? err.message : String(err)
    } finally {
      championshipLoading.value = false
    }
  }

  return {
    payload,
    loading,
    error,
    sessionKey,
    referenceDriver,
    compareSessionKey,
    championship,
    championshipLoading,
    championshipError,
    positions,
    positionsLoading,
    positionsError,
    strategy,
    strategyLoading,
    strategyError,
    rows,
    referenceRow,
    loadAnalysis,
    setReference,
    setCompare,
    setSession,
    loadPositions,
    loadStrategy,
    loadChampionship,
  }
})
