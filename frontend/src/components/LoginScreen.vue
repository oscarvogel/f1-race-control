<script setup lang="ts">
import { computed, ref } from 'vue'
import { AlertCircle, Eye, EyeOff, Lock, LogIn } from '@lucide/vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()

const usuario = ref('')
const clave = ref('')
const mostrarClave = ref(false)

const puedeEnviar = computed(() => usuario.value.trim().length > 0 && clave.value.length > 0)

async function enviar() {
  if (!puedeEnviar.value || auth.loading) return
  await auth.login(usuario.value, clave.value)
}
</script>

<template>
  <div class="flex min-h-screen items-center justify-center px-4 py-10">
    <div class="w-full max-w-[400px]">
      <!-- Marca -->
      <div class="mb-6 text-center">
        <div class="mb-3 flex items-center justify-center gap-2">
          <span class="h-6 w-1.5 rounded-sm bg-accent" />
          <span class="text-[26px] font-bold uppercase tracking-[0.18em] text-slate-100">
            Race<span class="text-accent">Center</span>
          </span>
        </div>
        <p class="text-[12px] uppercase tracking-[0.16em] text-slate-500">
          Panel de cronometraje de Formula 1
        </p>
      </div>

      <!-- Formulario -->
      <form class="panel px-6 py-6" @submit.prevent="enviar">
        <h1 class="mb-5 flex items-center gap-2 text-[13px] font-semibold uppercase tracking-[0.14em] text-slate-300">
          <Lock class="h-4 w-4 text-accent" />
          Acceso
        </h1>

        <label class="mb-1.5 block text-[11px] font-medium uppercase tracking-[0.12em] text-slate-500">
          Usuario
        </label>
        <input
          v-model="usuario"
          type="text"
          name="username"
          autocomplete="username"
          autofocus
          :disabled="auth.loading"
          class="num mb-4 w-full rounded-md border border-race-700 bg-race-850/80 px-3 py-2 text-[14px] text-slate-200 outline-none transition focus:border-accent/70 focus:ring-1 focus:ring-accent/40 disabled:opacity-60"
          placeholder="piloto"
        />

        <label class="mb-1.5 block text-[11px] font-medium uppercase tracking-[0.12em] text-slate-500">
          Contrasena
        </label>
        <div class="relative mb-4">
          <input
            v-model="clave"
            :type="mostrarClave ? 'text' : 'password'"
            name="password"
            autocomplete="current-password"
            :disabled="auth.loading"
            class="num w-full rounded-md border border-race-700 bg-race-850/80 px-3 py-2 pr-10 text-[14px] text-slate-200 outline-none transition focus:border-accent/70 focus:ring-1 focus:ring-accent/40 disabled:opacity-60"
            placeholder="••••••••"
          />
          <button
            type="button"
            class="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-1.5 text-slate-500 transition hover:text-slate-300"
            :aria-label="mostrarClave ? 'Ocultar contrasena' : 'Mostrar contrasena'"
            @click="mostrarClave = !mostrarClave"
          >
            <EyeOff v-if="mostrarClave" class="h-4 w-4" />
            <Eye v-else class="h-4 w-4" />
          </button>
        </div>

        <p
          v-if="auth.error"
          class="mb-4 flex items-start gap-2 rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-[12px] text-bad"
        >
          <AlertCircle class="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{{ auth.error }}</span>
        </p>

        <button
          type="submit"
          :disabled="!puedeEnviar || auth.loading"
          class="flex w-full items-center justify-center gap-2 rounded-md bg-accent px-4 py-2.5 text-[13px] font-semibold uppercase tracking-[0.12em] text-white transition hover:bg-accent-soft disabled:cursor-not-allowed disabled:opacity-50"
        >
          <LogIn class="h-4 w-4" />
          {{ auth.loading ? 'Entrando...' : 'Entrar' }}
        </button>
      </form>

      <p class="mt-4 text-center text-[11px] leading-relaxed text-slate-600">
        Acceso personal. Los datos provienen del feed publico de cronometraje
        de Formula 1 y de su proveedor historico.
      </p>
    </div>
  </div>
</template>
