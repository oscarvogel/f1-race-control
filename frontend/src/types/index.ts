/**
 * Tipos del dominio, alineados con el modelo normalizado del backend.
 * El frontend nunca ve el formato crudo de ninguna API externa.
 */

export type DataState = 'LIVE' | 'DELAYED' | 'HISTORICAL' | 'REPLAY' | 'WAITING' | 'OFFLINE' | 'ERROR'

export interface Sector {
  index: number
  time: number | null
  time_display: string | null
  personal_fastest: boolean
  overall_fastest: boolean
  stopped: boolean
  valid: boolean
}

export interface Driver {
  provider_id: string
  number: string
  code: string | null
  full_name: string | null
  broadcast_name: string | null
  first_name: string | null
  last_name: string | null
  team_name: string | null
  team_colour: string | null
  country_code: string | null
  line: number | null
  headshot_url: string | null
  source_timestamp: string | null
}

export interface BestLapTime {
  time: number | null
  time_display: string | null
}

export interface TimingEntry {
  provider_id: string
  driver_number: string
  driver: Driver | null
  position: number | null
  show_position: boolean
  best_lap_time: number | null
  best_lap_time_display: string | null
  best_lap_number: number | null
  best_lap_overall_fastest: boolean
  last_lap_time: number | null
  last_lap_time_display: string | null
  sectors: Sector[]
  gap_to_leader: string | null
  interval_to_ahead: string | null
  time_diff_to_fastest: string | null
  time_diff_to_position_ahead: string | null
  number_of_laps: number | null
  number_of_pit_stops: number | null
  in_pit: boolean
  pit_out: boolean
  stopped: boolean
  retired: boolean
  status_code: number | null
  tyre_compound: string | null
  tyre_age: number | null
  tyre_new: boolean | null
  grid_position: number | null
  best_lap_times: Record<string, BestLapTime>
  speeds: Record<string, number | null>
  source_timestamp: string | null
}

/** Posicion de un auto sobre el circuito, en coordenadas del feed. */
export interface CarPosition {
  provider_id: string
  driver_number: string
  x: number
  y: number
  z: number | null
  speed: number | null
  gear: number | null
  status: string | null
  source_timestamp: string | null
}

export interface TrackStatus {
  provider_id: string
  status: string | null
  message: string | null
  source_timestamp: string | null
}

export interface TrackOutline {
  circuit_key: number
  circuit_name: string
  source_session_key: number | null
  source_driver: number | null
  source: string
  point_count: number
  points: [number, number][]
  bounds: { min_x: number; max_x: number; min_y: number; max_y: number }
  size: number
}

export interface SessionInfo {
  provider_id: string
  provider_session_id: string
  meeting_name: string | null
  official_name: string | null
  circuit_name: string | null
  location: string | null
  country_name: string | null
  country_code: string | null
  season: string | null
  round_number: number | null
  meeting_key: number | null
  circuit_key: number | null
  session_type: string | null
  session_name: string | null
  session_number: number | null
  start_time_utc: string | null
  end_time_utc: string | null
  state: string | null
  archive_status: string | null
  gmt_offset: string | null
  qualifying_segment: string | null
  source_timestamp: string | null
}

export interface WeatherReport {
  provider_id: string
  air_temperature: number | null
  track_temperature: number | null
  humidity: number | null
  pressure: number | null
  rainfall: number | null
  wind_speed: number | null
  wind_direction: number | null
  source_timestamp: string | null
}

export interface RaceControlEvent {
  provider_id: string
  message: string
  category: string | null
  flag: string | null
  scope: string | null
  utc: string | null
  source_timestamp: string | null
}

export interface Stint {
  provider_id: string
  driver_number: string
  stint_number: number | null
  compound: string | null
  lap_start: number | null
  lap_end: number | null
  tyre_age_at_start: number | null
  total_laps: number | null
  is_new: boolean | null
  source_timestamp: string | null
}

export interface ProviderCapabilities {
  provider_id: string
  live: boolean
  historical: boolean
  metadata: boolean
  timing: boolean
  laps: boolean
  sectors: boolean
  tyres: boolean
  weather: boolean
  race_control: boolean
  telemetry: boolean
  positions: boolean
  notes: string
}

export interface ProviderStatus {
  provider_id: string
  name: string
  endpoint: string
  state: string
  is_connected: boolean
  last_message_at: string | null
  data_age_seconds: number | null
  latency_ms: number | null
  last_error: string | null
  error_count: number
  reconnect_count: number
  capabilities: ProviderCapabilities | null
  updated_at: string | null
}

export interface Diagnostics {
  mode: string
  live_provider: string | null
  historical_provider: string | null
  metadata_provider: string | null
  thresholds: { live_max_age_seconds: number; delayed_max_age_seconds: number }
  providers: ProviderStatus[]
  last_error: Record<string, string>
}

export interface Snapshot {
  found?: boolean
  generated_at: string
  data_state: DataState
  scope: string
  session: SessionInfo | null
  drivers: Driver[]
  timing: TimingEntry[]
  weather: WeatherReport | null
  race_control: RaceControlEvent[]
  tyres: Stint[]
  positions: CarPosition[]
  track_status: TrackStatus | null
  sources: Record<string, string | null>
  provider_status: ProviderStatus[]
  diagnostics: Diagnostics
  /** Partes que no se pudieron leer (p. ej. limite de tasa del proveedor). */
  warnings?: string[]
  _snapshot_id?: number
  _snapshot_created_at?: string
  _session_pk?: number
  /** Origen del snapshot cuando se sirve desde cache: "db". */
  _from_cache?: string
}

export interface HealthPayload {
  status: string
  app: string
  mode: string
  server_time_utc: string
  timezone: string
  has_snapshot: boolean
  data_state: DataState | null
  last_ingestion: {
    started_at: string | null
    ok: boolean | null
    duration_ms: number | null
    entries_count: number | null
    changed: boolean | null
    error: string | null
  }
  providers: { provider_id: string; state: string; is_connected: boolean }[]
}

/** Sesion historica elegible (FP1/FP2/FP3/Sprint/Clasificacion/Carrera). */export interface SessionOption {
  provider_id: string
  session_key: string
  session_type: string
  session_name: string
  start_time_utc: string | null
  end_time_utc: string | null
  meeting_name: string | null
  circuit_name: string | null
  meeting_key: number | null
  /** Desfase horario del circuito (dato real, p.ej. "-05:00:00"). */
  gmt_offset: string | null
  is_live: boolean
}

/** Una hora de la prevision del circuito. */
export interface ForecastHour {
  time_utc: string
  temperature: number | null
  precipitation_probability: number | null
  precipitation: number | null
  weather_code: number | null
  condition: string
  wind_speed: number | null
  wind_gusts: number | null
}

/** Resumen de una ventana horaria de la prevision. */
export interface ForecastSummary {
  temperature_min: number | null
  temperature_max: number | null
  temperature_mean: number | null
  precipitation_probability_max: number | null
  precipitation_total: number
  wind_speed_max: number | null
  condition: string
  hours: number
}

/** Prevision del circuito (Open-Meteo). */
export interface CircuitForecast {
  provider_id: string
  display_name: string
  source_url: string
  fetched_at: string
  circuit_key: number
  circuit_name: string
  latitude: number
  longitude: number
  timezone: string
  coordinates_source: string
  summary: ForecastSummary
  hourly: ForecastHour[]
}

/** Prevision recortada a la ventana de una sesion. */
export interface ForecastWindow {
  start_utc: string
  end_utc: string | null
  summary: ForecastSummary
  hourly: ForecastHour[]
  session_key?: string
  session_name?: string
  session_type?: string
  start_time_utc?: string | null
  end_time_utc?: string | null
}
