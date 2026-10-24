/**
 * Cliente de la API interna de Race Center.
 *
 * El frontend habla **solo** con nuestra API. Todas las peticiones son
 * relativas (`/api/...`), de modo que en desarrollo el proxy de Vite las
 * reenvia al backend local y ninguna URL externa queda expuesta en el
 * navegador.
 *
 * La cookie de sesion se manda siempre (`credentials: 'include'`): es la que
 * prueba el `auth_request` de nginx antes de dejar pasar cada peticion.
 */
import type { HealthPayload, Snapshot } from '@/types'

const BASE = '/api'

/**
 * Evento que se dispara cuando la API responde 401 (sesion vencida o
 * inexistente). Lo escucha el App para volver a la pantalla de acceso.
 */
export const UNAUTHORIZED_EVENT = 'race-center:unauthorized'

async function request<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    headers: { Accept: 'application/json' },
    credentials: 'include',
    signal,
  })
  if (response.status === 401) {
    window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT))
  }
  if (!response.ok) {
    throw new Error(`La API respondio HTTP ${response.status} en ${path}`)
  }
  return (await response.json()) as T
}

/** Login: devuelve el ok o el motivo del rechazo. */
async function post<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    credentials: 'include',
    body: JSON.stringify(body),
  })
  const data = (await response.json().catch(() => ({}))) as T
  if (response.status === 401) {
    window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT))
  }
  if (!response.ok && response.status !== 401) {
    throw new Error(`La API respondio HTTP ${response.status} en ${path}`)
  }
  return data
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

  // -- Analisis post-sesion ---------------------------------------------- //
  sectorAnalysis: (
    sessionKey: string,
    params: { reference?: string | null; compare?: string | null } = {},
    signal?: AbortSignal,
  ) => {
    const query = new URLSearchParams()
    if (params.reference) query.set('reference', params.reference)
    if (params.compare) query.set('compare', params.compare)
    const suffix = query.toString() ? `?${query.toString()}` : ''
    return request<any>(`/analysis/sectors/${sessionKey}/${suffix}`, signal)
  },
  championship: (season?: number | null, signal?: AbortSignal) =>
    request<any>(season ? `/championship/?season=${season}` : '/championship/', signal),

  // -- Sesion del sitio -------------------------------------------------- //
  authSession: (signal?: AbortSignal) => request<any>('/auth/session/', signal),
  login: (username: string, password: string) =>
    post<{ ok: boolean; username?: string; error?: string }>('/auth/login/', {
      username,
      password,
    }),
  logout: () => post<{ ok: boolean }>('/auth/logout/', {}),
}
