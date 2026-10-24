/**
 * Cliente de la API interna de Race Center.
 *
 * El frontend habla **solo** con nuestra API. Todas las peticiones son
 * relativas (`/api/...`), de modo que en desarrollo el proxy de Vite las
 * reenvia al backend local y ninguna URL externa queda expuesta en el
 * navegador.
 */
import type { HealthPayload, Snapshot } from '@/types'

const BASE = '/api'

async function request<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    headers: { Accept: 'application/json' },
    signal,
  })
  if (!response.ok) {
    throw new Error(`La API respondio HTTP ${response.status} en ${path}`)
  }
  return (await response.json()) as T
}

export const api = {
  health: (signal?: AbortSignal) => request<HealthPayload>('/health/', signal),
  currentSession: (signal?: AbortSignal) => request<Snapshot>('/sessions/current/', signal),
  providerStatus: (signal?: AbortSignal) => request<any>('/providers/status/', signal),
  providers: (signal?: AbortSignal) => request<any>('/providers/', signal),
  sessions: (signal?: AbortSignal) => request<any>('/sessions/', signal),
  trackOutline: (circuitKey: number, signal?: AbortSignal) =>
    request<any>(`/track/outlines/${circuitKey}/`, signal),
  sessionCatalog: (query = '', signal?: AbortSignal) =>
    request<any>(`/sessions/catalog/${query}`, signal),
  historicalSnapshot: (sessionKey: string, signal?: AbortSignal) =>
    request<any>(`/sessions/historical/${sessionKey}/`, signal),
  weatherForecast: (hours = 48, signal?: AbortSignal) =>
    request<any>(`/weather/forecast/?hours=${hours}`, signal),
}
