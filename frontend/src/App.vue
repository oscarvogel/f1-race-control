<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import DashboardView from '@/views/DashboardView.vue'
import LoginScreen from '@/components/LoginScreen.vue'
import { useAuthStore } from '@/stores/auth'
import { UNAUTHORIZED_EVENT } from '@/services/api'

const auth = useAuthStore()

/**
 * La API responde 401 cuando la sesion vencio: en ese caso se vuelve a la
 * pantalla de acceso en lugar de dejar el dashboard mostrando errores.
 */
function onUnauthorized() {
  auth.markUnauthenticated()
}

onMounted(() => {
  window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
  void auth.check()
})

onUnmounted(() => {
  window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
})
</script>

<template>
  <!--
    Mientras se consulta el estado de la sesion no se muestra ni el login ni
    el dashboard: pintar el dashboard sin sesion haria saltar errores de 401
    en todas las peticiones.
  -->
  <div v-if="auth.checking" class="flex min-h-screen items-center justify-center">
    <div class="flex items-center gap-2 text-[11px] uppercase tracking-[0.2em] text-slate-600">
      <span class="live-dot h-1.5 w-1.5 rounded-full bg-accent" />
      Race Center
    </div>
  </div>

  <LoginScreen v-else-if="auth.required && !auth.authenticated" />

  <DashboardView v-else />
</template>
