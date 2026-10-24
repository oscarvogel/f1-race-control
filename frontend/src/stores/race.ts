/**
 * Estado del dashboard (Pinia).
 *
 * Concentra el snapshot normalizado, la seleccion de piloto, el orden de la
 * tabla y el seguimiento de cambios entre actualizaciones, para poder
 * resaltar en la interfaz los valores que **realmente** cambiaron.
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '@/services/api'
import type {
  CircuitForecast,
  DataState,
  ForecastWindow,
  SessionOption,
  Snapshot,
  Stint,
  TimingEntry,
} from '@/types'

export type SortKey =
  | 'position'
  | 'driver'
  | 'team'
  | 'q1'
  | 'q2'
  | 'q3'
  | 'gap'
  | 'laps'
  | 'tyre'
  | 'best'

export const useRaceStore = defineStore('race', () => {
  const liveSnapshot = ref<Snapshot | null>(null)
  const historicalSnapshot = ref<Snapshot | null>(null)
  const sessionCatalog = ref<SessionOption[]>([])
  /** 'live' = sesion en curso; 'historical' = sesion elegida del catalogo. */
  const viewMode = ref<'live' | 'historical'>('live')
  const activeSessionKey = ref<string | null>(null)
  const loadingHistorical = ref(false)

  /** Prevision del circuito (Open-Meteo). Fuente distinta al clima observado. */
  const forecast = ref<CircuitForecast | null>(null)
  const forecastWindow = ref<ForecastWindow | null>(null)
  const forecastError = ref<string | null>(null)

  /** Cerrojos para no pedir dos veces lo mismo mientras vuela la peticion. */
  const catalogLoading = ref(false)
  const forecastLoading = ref(false)
  /** El catalogo ya llego: sirve para no decir "sin sesiones" mientras carga. */
  const catalogLoaded = ref(false)

  const loading = ref(false)
  const error = ref<string | null>(null)
  const lastUpdated = ref<Date | null>(null)
  const selectedDriver = ref<string | null>(null)
  const compareDriver = ref<string | null>(null)
  const sortKey = ref<SortKey>('position')
  const sortAsc = ref(true)
  const diagnosticsOpen = ref(false)

  /** Huella por piloto de los valores mostrados, para detectar cambios. */
  const fingerprints = ref<Record<string, string>>({})
  /** Pilotos cuyo valor cambio en la ultima actualizacion. */
  const changedDrivers = ref<Record<string, string[]>>({})

  /**
   * El snapshot que se muestra: el de la sesion en vivo o el historico
   * elegido. El resto de la interfaz no distingue entre los dos: siempre
   * consume el modelo normalizado.
   */
  const snapshot = computed<Snapshot | null>(() =>
    viewMode.value === 'historical' ? historicalSnapshot.value : liveSnapshot.value,
  )

  const dataState = computed<DataState>(
    () => snapshot.value?.data_state ?? 'OFFLINE',
  )

  const session = computed(() => snapshot.value?.session ?? null)

  const timing = computed<TimingEntry[]>(() => snapshot.value?.timing ?? [])

  const drivers = computed(() => snapshot.value?.drivers ?? [])

  const raceControl = computed(() => snapshot.value?.race_control ?? [])

  const weather = computed(() => snapshot.value?.weather ?? null)

  /** Posicion de cada auto sobre el circuito (canal CarData). */
  const positions = computed(() => snapshot.value?.positions ?? [])

  /** Estado de pista (banderas, safety car). */
  const trackStatus = computed(() => snapshot.value?.track_status ?? null)

  /** Stints de pneumaticos de la sesion mostrada. */
  const tyres = computed<Stint[]>(() => snapshot.value?.tyres ?? [])

  /**
   * Neumatico vigente de cada piloto.
   *
   * En el feed en vivo el compuesto viene en la propia entrada de
   * clasificacion. En el historico de OpenF1 no: el compuesto esta en los
   * stints. Sin esta resolucion la columna de pneumatico salia vacia para
   * todos los pilotos de un FP1, aunque el panel de neumaticos si mostraba
   * los stints reales.
   */
  const compoundByDriver = computed<Record<string, string>>(() => {
    const ultimo: Record<string, { compound: string; fin: number }> = {}
    for (const stint of tyres.value) {
      if (!stint.compound || !stint.driver_number) continue
      const fin = stint.lap_end ?? 0
      const previo = ultimo[stint.driver_number]
      if (!previo || fin >= previo.fin) {
        ultimo[stint.driver_number] = { compound: stint.compound, fin }
      }
    }
    const result: Record<string, string> = {}
    for (const [driver, info] of Object.entries(ultimo)) {
      result[driver] = info.compound
    }
    return result
  })

  const providerStatus = computed(() => snapshot.value?.provider_status ?? [])

  const diagnostics = computed(() => snapshot.value?.diagnostics ?? null)

  const sources = computed(() => snapshot.value?.sources ?? {})

  /** Fuente real de cada conjunto de datos, para mostrarla en la interfaz. */
  const liveProvider = computed(
    () => sources.value.timing ?? sources.value.session ?? null,
  )

  /**
   * Desfase horario del circuito.
   *
   * Dato real del feed (`GmtOffset`) y de OpenF1 (`gmt_offset`): permite
   * mostrar la hora en el circuito sin deducir la zona horaria por el nombre
   * del trazado, que cambia con el horario de verano.
   */
  const gmtOffset = computed<string | null>(() => {
    const fromSession = session.value?.gmt_offset
    if (fromSession) return fromSession
    for (const option of sessionCatalog.value) {
      if (option.gmt_offset) return option.gmt_offset
    }
    return null
  })

  /**
   * Proxima sesion del Gran Premio.
   *
   * Es una funcion y no un valor calculado porque depende de la hora actual:
   * cuando empieza la sesion que estaba en cuenta, la siguiente tiene que
   * cambiar sola.
   */
  function nextSessionAt(nowMs: number): SessionOption | null {
    let best: { option: SessionOption; start: number } | null = null
    for (const option of sessionCatalog.value) {
      if (!option.start_time_utc) continue
      const start = new Date(option.start_time_utc).getTime()
      if (Number.isNaN(start) || start <= nowMs) continue
      if (!best || start < best.start) best = { option, start }
    }
    return best?.option ?? null
  }

  const sessionLabel = computed(() => {
    const s = session.value
    if (!s) return 'Sesion no detectada'
    const type = s.session_name || s.session_type || ''
    return type
  })

  const isQualifying = computed(() => {
    const type = session.value?.session_type?.toLowerCase() ?? ''
    return type.includes('qualifying') || type.includes('shootout')
  })

  /**
   * ¿La sesión está en curso?
   *
   * Importa porque los indicadores transitorios (En boxes, Parado, Pit out)
   * solo tienen sentido mientras se corre. Cuando la sesión terminó, el feed
   * deja el último estado de cada auto y aparece, por ejemplo, "en boxes" para
   * los 22 pilotos: es el dato real del feed, pero presentarlo como si fuera
   * el estado actual sería engañoso.
   */
  const sessionIsActive = computed(() => {
    const state = (session.value?.state ?? '').toLowerCase()
    if (state && ['finalised', 'finished', 'ended', 'completed'].includes(state)) return false
    return ['LIVE', 'DELAYED', 'WAITING'].includes(dataState.value)
  })

  /** Segmento de clasificacion vigente (Q1/Q2/Q3) cuando el proveedor lo dice. */
  const qualifyingSegment = computed(() => session.value?.qualifying_segment ?? null)

  /**
   * Partes del snapshot que no se pudieron leer.
   *
   * Un snapshot historico puede quedar incompleto (por ejemplo, sin clima
   * porque el proveedor externo agoto su cuota). Se muestra en pantalla en
   * lugar de dejar un panel vacio sin explicacion.
   */
  const warnings = computed<string[]>(() => snapshot.value?.warnings ?? [])

  const selectedEntry = computed(
    () => timing.value.find((entry) => entry.driver_number === selectedDriver.value) ?? null,
  )

  const compareEntry = computed(
    () => timing.value.find((entry) => entry.driver_number === compareDriver.value) ?? null,
  )

  /** Mejor vuelta absoluta de la sesion. */
  const sessionFastestLap = computed<number | null>(() => {
    let best: number | null = null
    for (const entry of timing.value) {
      const value = entry.best_lap_time
      if (value == null) continue
      if (best == null || value < best) best = value
    }
    return best
  })

  /** Indices de sector que son el mejor absoluto de la sesion. */
  const overallBestSectors = computed<Record<number, Set<string>>>(() => {
    const result: Record<number, Set<string>> = { 0: new Set(), 1: new Set(), 2: new Set() }
    const best: Record<number, number> = {}
    for (const entry of timing.value) {
      for (const sector of entry.sectors ?? []) {
        if (sector.time == null || !sector.valid) continue
        const current = best[sector.index]
        if (current == null || sector.time < current) best[sector.index] = sector.time
      }
    }
    for (const entry of timing.value) {
      for (const sector of entry.sectors ?? []) {
        if (sector.time == null || !sector.valid) continue
        if (best[sector.index] === sector.time) result[sector.index].add(entry.driver_number)
      }
    }
    return result
  })

  function fingerprintOf(entry: TimingEntry): string {
    return JSON.stringify([
      entry.position,
      entry.best_lap_time,
      entry.last_lap_time,
      entry.gap_to_leader,
      entry.time_diff_to_fastest,
      entry.time_diff_to_position_ahead,
      entry.number_of_laps,
      entry.tyre_compound,
      entry.tyre_age,
      entry.best_lap_times,
      (entry.sectors ?? []).map((s) => [s.time, s.personal_fastest, s.overall_fastest]),
      entry.in_pit,
      entry.retired,
    ])
  }

  /** Detecta que celdas cambiaron realmente entre dos snapshots. */
  function trackChanges(entries: TimingEntry[]) {
    const changed: Record<string, string[]> = {}
    for (const entry of entries) {
      const fingerprint = fingerprintOf(entry)
      const previous = fingerprints.value[entry.driver_number]
      if (previous !== undefined && previous !== fingerprint) {
        changed[entry.driver_number] = ['*']
      }
      fingerprints.value[entry.driver_number] = fingerprint
    }
    changedDrivers.value = changed
    window.setTimeout(() => {
      changedDrivers.value = {}
    }, 1600)
  }

  async function refresh(): Promise<void> {
    loading.value = true
    try {
      const data = await api.currentSession()
      if (data.found === false) {
        error.value =
          data.reason ?? 'Todavia no hay datos. El proceso de ingesta debe estar corriendo.'
        return
      }
      error.value = null
      const previousFingerprints = { ...fingerprints.value }
      fingerprints.value = {}
      trackChanges(data.timing ?? [])
      if (Object.keys(previousFingerprints).length === 0) {
        // Primer snapshot: no hay "cambio" que resaltar.
        changedDrivers.value = {}
      }
      liveSnapshot.value = data
      lastUpdated.value = new Date()

      if (selectedDriver.value === null && (data.timing ?? []).length > 0) {
        selectedDriver.value = data.timing[0].driver_number
      }
      // El catalogo de sesiones se carga una vez: la API lo cachea y no hace
      // falta pedirlo en cada refresco.
      if (sessionCatalog.value.length === 0) void loadCatalog()
      // La prevision del circuito tampoco cambia segundo a segundo: el
      // backend la cachea, asi que se pide de tanto en tanto.
      if (!forecast.value && !forecastError.value) void loadForecast()
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
    } finally {
      loading.value = false
    }
  }

  /** Carga la prevision meteorologica del circuito (Open-Meteo). */
  async function loadForecast(): Promise<void> {
    if (forecastLoading.value) return
    forecastLoading.value = true
    try {
      const data = await api.weatherForecast(48)
      if (data.found === false) {
        forecastError.value = data.reason ?? 'Sin prevision para este circuito.'
        return
      }
      forecastError.value = null
      forecast.value = data.forecast ?? null
      forecastWindow.value = data.next_session_window ?? null
    } catch (err) {
      forecastError.value = err instanceof Error ? err.message : String(err)
    } finally {
      forecastLoading.value = false
    }
  }

  /** Carga el catalogo de sesiones del Gran Premio en curso. */
  async function loadCatalog(): Promise<void> {
    // Cerrojo: el refresco corre cada 2 s y puede pedir el catalogo dos
    // veces antes de que llegue la primera respuesta.
    if (catalogLoading.value) return
    catalogLoading.value = true
    try {
      const meetingKey = liveSnapshot.value?.session?.meeting_key
      const query = meetingKey ? `?meeting_key=${meetingKey}` : ''
      const data = await api.sessionCatalog(query)
      sessionCatalog.value = data.results ?? []
      catalogLoaded.value = true
    } catch {
      sessionCatalog.value = []
    } finally {
      catalogLoading.value = false
    }
  }

  /** Cambia a una sesion historica (FP1, FP2, FP3, Sprint, Carrera...). */
  async function selectHistoricalSession(sessionKey: string | null): Promise<void> {
    if (!sessionKey) {
      viewMode.value = 'live'
      activeSessionKey.value = null
      return
    }
    loadingHistorical.value = true
    try {
      const data = await api.historicalSnapshot(sessionKey)
      if (data.found === false) {
        error.value = data.reason ?? 'No hay datos para esa sesion.'
        return
      }
      error.value = null
      historicalSnapshot.value = data as unknown as Snapshot
      viewMode.value = 'historical'
      activeSessionKey.value = sessionKey
      selectedDriver.value = (data.timing?.[0]?.driver_number as string) ?? null
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
    } finally {
      loadingHistorical.value = false
    }
  }

  function selectDriver(number: string | null) {
    selectedDriver.value = number
  }

  function toggleCompare(number: string) {
    if (compareDriver.value === number) {
      compareDriver.value = null
      return
    }
    if (compareDriver.value === null) {
      compareDriver.value = number
      return
    }
    compareDriver.value = number
    selectedDriver.value = number
  }

  function setSort(key: SortKey) {
    if (sortKey.value === key) {
      sortAsc.value = !sortAsc.value
    } else {
      sortKey.value = key
      sortAsc.value = true
    }
  }

  return {
    snapshot,
    liveSnapshot,
    historicalSnapshot,
    sessionCatalog,
    viewMode,
    activeSessionKey,
    loadingHistorical,
    loading,
    error,
    lastUpdated,
    selectedDriver,
    compareDriver,
    sortKey,
    sortAsc,
    diagnosticsOpen,
    dataState,
    session,
    sessionLabel,
    isQualifying,
    sessionIsActive,
    qualifyingSegment,
    timing,
    drivers,
    raceControl,
    weather,
    positions,
    trackStatus,
    providerStatus,
    diagnostics,
    sources,
    liveProvider,
    selectedEntry,
    compareEntry,
    sessionFastestLap,
    overallBestSectors,
    changedDrivers,
    warnings,
    tyres,
    compoundByDriver,
    gmtOffset,
    nextSessionAt,
    forecast,
    forecastWindow,
    forecastError,
    catalogLoaded,
    loadForecast,
    refresh,
    loadCatalog,
    selectHistoricalSession,
    selectDriver,
    toggleCompare,
    setSort,
  }
})
