/**
 * Estado de la sesion del sitio.
 *
 * El sitio desplegado esta en un repo publico, asi que la API pide sesion.
 * El login es de la propia aplicacion (pantalla propia, en espanol) y la
 * proteccion la aplica nginx consultando a `/api/auth/check/`.
 *
 * En desarrollo local no hay credenciales configuradas: el backend responde
 * `required: false` y la app entra directo, sin pedir nada.
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/services/api'

export const useAuthStore = defineStore('auth', () => {
  /** El sitio pide usuario y contrasena. */
  const required = ref(false)
  /** Hay sesion iniciada. */
  const authenticated = ref(true)
  const username = ref<string | null>(null)
  /** Se esta consultando el estado de la sesion. */
  const checking = ref(true)
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function check(): Promise<void> {
    checking.value = true
    try {
      const data = await api.authSession()
      required.value = Boolean(data.required)
      authenticated.value = Boolean(data.authenticated)
      username.value = data.username ?? null
      error.value = null
    } catch (err) {
      // Si ni siquiera se puede consultar el estado, se sigue con la app:
      // es el modo de desarrollo local, donde la API esta abierta.
      required.value = false
      authenticated.value = true
      error.value = err instanceof Error ? err.message : String(err)
    } finally {
      checking.value = false
    }
  }

  async function login(user: string, password: string): Promise<boolean> {
    loading.value = true
    error.value = null
    try {
      const data = await api.login(user, password)
      if (data.ok) {
        authenticated.value = true
        required.value = true
        username.value = data.username ?? user
        return true
      }
      error.value = data.error ?? 'No se pudo iniciar sesion.'
      return false
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
      return false
    } finally {
      loading.value = false
    }
  }

  async function logout(): Promise<void> {
    try {
      await api.logout()
    } catch {
      // Si el cierre falla, la cookie se borra igual al recargar.
    }
    authenticated.value = false
    username.value = null
  }

  /** La API respondio 401: la sesion vencio o no hay. */
  function markUnauthenticated(): void {
    if (!required.value) return
    authenticated.value = false
    username.value = null
  }

  return {
    required,
    authenticated,
    username,
    checking,
    loading,
    error,
    check,
    login,
    logout,
    markUnauthenticated,
  }
})
