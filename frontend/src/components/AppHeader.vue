<script setup lang="ts">
import { computed } from 'vue'
import { Activity, Clock, LogOut, MapPin, Radio, Settings2, Wifi, WifiOff } from '@lucide/vue'
import StatusBadge from './StatusBadge.vue'
import SessionSelector from './SessionSelector.vue'
import { useClock } from '@/composables/useClock'
import { useRaceStore } from '@/stores/race'
import { useAuthStore } from '@/stores/auth'

const store = useRaceStore()
const auth = useAuthStore()

/** Reloj compartido con el resto de la interfaz. */
const now = useClock()

const pad = (value: number) => String(value).padStart(2, '0')

/** Hora de Argentina (America/Argentina/Cordoba), independiente de la del navegador. */
const argentinaTime = computed(() => {
  try {
    return new Intl.DateTimeFormat('es-AR', {
      timeZone: 'America/Argentina/Cordoba',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    }).format(now.value)
  } catch {
    return now.value.toLocaleTimeString('es-AR', { hour12: false })
  }
})

const argentinaDate = computed(() => {
  try {
    return new Intl.DateTimeFormat('es-AR', {
      timeZone: 'America/Argentina/Cordoba',
      weekday: 'short',
      day: '2-digit',
      month: 'short',
    }).format(now.value)
  } catch {
    return now.value.toLocaleDateString('es-AR')
  }
})

/**
 * Minutos de desfase del circuito.
 *
 * El valor viene del feed de F1 (`GmtOffset`) y de OpenF1 (`gmt_offset`): es
 * el dato real de la organizacion, no una zona horaria deducida por el nombre
 * del circuito (que cambia con el horario de verano).
 */
function offsetMinutes(offset: string | null): number | null {
  if (!offset) return null
  const match = /^([+-])(\d{1,2}):?(\d{2})/.exec(offset.trim())
  if (!match) return null
  const sign = match[1] === '-' ? -1 : 1
  return sign * (Number(match[2]) * 60 + Number(match[3]))
}

/** Hora en el circuito, con su desfase. */
const circuitTime = computed(() => {
  const minutes = offsetMinutes(store.gmtOffset)
  if (minutes === null) return null
  const shifted = new Date(now.value.getTime() + minutes * 60000)
  return {
    clock: `${pad(shifted.getUTCHours())}:${pad(shifted.getUTCMinutes())}:${pad(shifted.getUTCSeconds())}`,
    label: `UTC${minutes >= 0 ? '+' : '-'}${pad(Math.floor(Math.abs(minutes) / 60))}:${pad(Math.abs(minutes) % 60)}`,
    place: store.session?.circuit_name ?? store.session?.location ?? '',
  }
})

/** Proxima sesion: la primera del catalogo que todavia no empezo. */
const nextSession = computed(() => store.nextSessionAt(now.value.getTime()))

/** Tiempo que falta para que empiece, en formato de reloj. */
const countdown = computed(() => {
  const session = nextSession.value
  if (!session?.start_time_utc) return null
  const start = new Date(session.start_time_utc).getTime()
  const remaining = Math.max(0, start - now.value.getTime())
  const total = Math.floor(remaining / 1000)
  const days = Math.floor(total / 86400)
  const hours = Math.floor((total % 86400) / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = total % 60
  const clock = `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`
  return days > 0 ? `${days}d ${clock}` : clock
})

/** Cuando falta poco, la cuenta regresiva se marca: es lo que hay que mirar. */
const countdownUrgent = computed(() => {
  const session = nextSession.value
  if (!session?.start_time_utc) return false
  const start = new Date(session.start_time_utc).getTime()
  return start - now.value.getTime() <= 15 * 60 * 1000
})

/** Hora de inicio de la proxima sesion, en Argentina y en el circuito. */
const nextStart = computed(() => {
  const session = nextSession.value
  if (!session?.start_time_utc) return null
  const start = new Date(session.start_time_utc)
  const minutes = offsetMinutes(store.gmtOffset)
  let circuit = ''
  if (minutes !== null) {
    const shifted = new Date(start.getTime() + minutes * 60000)
    circuit = `${pad(shifted.getUTCHours())}:${pad(shifted.getUTCMinutes())}`
  }
  let local = ''
  try {
    local = new Intl.DateTimeFormat('es-AR', {
      timeZone: 'America/Argentina/Cordoba',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    }).format(start)
  } catch {
    local = ''
  }
  return { local, circuit }
})

const lastUpdate = computed(() => {
  if (!store.lastUpdated) return '--:--:--'
  return store.lastUpdated.toLocaleTimeString('es-AR', { hour12: false })
})

const isConnected = computed(() =>
  store.providerStatus.some((provider) => provider.is_connected),
)

const liveProviderName = computed(() => {
  const id = store.liveProvider
  if (!id) return '—'
  const provider = store.providerStatus.find((item) => item.provider_id === id)
  return provider ? provider.name : id
})

/**
 * Antiguedad del dato mostrado.
 *
 * En vivo es la edad del ultimo mensaje del proveedor. En historico es la
 * edad del snapshot: la edad del proveedor en vivo no corresponde a la
 * sesion que se esta mirando.
 */
const dataAge = computed(() => {
  if (store.viewMode === 'historical') {
    const generated = store.snapshot?.generated_at
    if (!generated) return null
    const stamp = new Date(generated).getTime()
    if (Number.isNaN(stamp)) return null
    return Math.max(0, (now.value.getTime() - stamp) / 1000)
  }
  const id = store.liveProvider
  if (!id) return null
  const provider = store.providerStatus.find((item) => item.provider_id === id)
  return provider?.data_age_seconds ?? null
})

const ageLabel = computed(() => {
  if (dataAge.value === null) return 'sin dato'
  if (dataAge.value < 1) return 'ahora'
  if (dataAge.value < 60) return `hace ${Math.round(dataAge.value)}s`
  if (dataAge.value < 3600) return `hace ${Math.round(dataAge.value / 60)} min`
  return `hace ${Math.round(dataAge.value / 3600)} h`
})

const ageTitle = computed(() =>
  store.viewMode === 'historical' ? 'Antiguedad del snapshot' : 'Ultimo dato del proveedor',
)

const sessionTitle = computed(() => store.session?.meeting_name ?? 'Race Center')
const sessionSubtitle = computed(() => {
  const s = store.session
  if (!s) return 'Esperando deteccion de sesion'
  const parts: string[] = []
  if (s.session_name) parts.push(s.session_name.toUpperCase())
  else if (s.session_type) parts.push(s.session_type.toUpperCase())
  if (s.location) parts.push(s.location)
  if (s.session_type?.toLowerCase().includes('qualifying')) parts.push('Q1 / Q2 / Q3')
  return parts.join(' · ')
})

const officialName = computed(() => store.session?.official_name ?? '')
</script>

<template>
  <header class="sticky top-0 z-30 border-b border-race-750/70 bg-race-950/85 backdrop-blur-md">
    <div class="mx-auto flex max-w-[1800px] flex-wrap items-center gap-x-5 gap-y-3 px-4 py-3 lg:px-6">
      <!-- Identidad -->
      <div class="min-w-0 flex-1">
        <div class="flex items-center gap-2.5">
          <span class="flex h-7 w-1.5 rounded-full bg-accent" />
          <h1 class="text-lg font-black tracking-[0.22em] text-white sm:text-xl">
            RACE<span class="text-accent">CENTER</span>
          </h1>
        </div>
        <p class="mt-1 truncate text-[13px] font-semibold uppercase tracking-[0.1em] text-slate-300">
          {{ sessionTitle }}
        </p>
        <p class="truncate text-[11px] uppercase tracking-[0.12em] text-slate-500">
          {{ sessionSubtitle }}
          <span v-if="officialName" class="hidden sm:inline"> · {{ officialName }}</span>
        </p>
      </div>

      <!-- Estado y metadatos -->
      <div class="flex flex-wrap items-center gap-2.5">
        <StatusBadge :state="store.dataState" size="md" />

        <SessionSelector />

        <div class="hidden items-center gap-2 rounded-lg border border-race-750/70 bg-race-900/70 px-3 py-1.5 sm:flex">
          <Radio
            class="h-3.5 w-3.5"
            :class="isConnected ? 'text-ok' : 'text-bad'"
            :stroke-width="2"
          />
          <div class="leading-tight">
            <div class="text-[9px] uppercase tracking-[0.14em] text-slate-500">Proveedor</div>
            <div class="max-w-[190px] truncate text-[11px] font-semibold text-slate-200">
              {{ liveProviderName }}
            </div>
          </div>
        </div>

        <div
          class="hidden items-center gap-2 rounded-lg border border-race-750/70 bg-race-900/70 px-3 py-1.5 md:flex"
          :title="ageTitle"
        >
          <Activity class="h-3.5 w-3.5 text-slate-500" :stroke-width="2" />
          <div class="leading-tight">
            <div class="text-[9px] uppercase tracking-[0.14em] text-slate-500">
              {{ store.viewMode === 'historical' ? 'Snapshot' : 'Ultimo dato' }}
            </div>
            <div class="num text-[11px] font-semibold text-slate-200">{{ ageLabel }}</div>
          </div>
        </div>

        <div class="rounded-lg border border-race-750/70 bg-race-900/70 px-3 py-1.5 text-right">
          <div class="text-[9px] uppercase tracking-[0.14em] text-slate-500">Argentina</div>
          <div class="num text-[15px] font-bold leading-tight text-white">{{ argentinaTime }}</div>
          <div class="text-[9px] uppercase text-slate-500">{{ argentinaDate }}</div>
        </div>

        <div class="hidden rounded-lg border border-race-750/70 bg-race-900/70 px-3 py-1.5 text-right xl:block">
          <div class="text-[9px] uppercase tracking-[0.14em] text-slate-500">Actualizado</div>
          <div class="num text-[12px] font-semibold text-slate-200">{{ lastUpdate }}</div>
        </div>

        <button
          type="button"
          class="flex items-center gap-1.5 rounded-lg border border-race-700 bg-race-850/80 px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400 transition hover:border-accent/60 hover:text-white"
          title="Panel de diagnostico"
          @click="store.diagnosticsOpen = true"
        >
          <Settings2 class="h-3.5 w-3.5" :stroke-width="2" />
          <span class="hidden sm:inline">Diagnostico</span>
        </button>

        <!-- Salir: solo aparece si el sitio pide sesion. -->
        <button
          v-if="auth.required"
          type="button"
          class="flex items-center gap-1.5 rounded-lg border border-race-700 bg-race-850/80 px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400 transition hover:border-accent/60 hover:text-white"
          :title="auth.username ? `Sesion de ${auth.username}` : 'Salir'"
          @click="auth.logout()"
        >
          <LogOut class="h-3.5 w-3.5" :stroke-width="2" />
          <span class="hidden sm:inline">Salir</span>
        </button>

        <span
          class="flex items-center gap-1.5 rounded-lg border px-2.5 py-2"
          :class="isConnected ? 'border-ok/40 bg-ok/10 text-ok' : 'border-bad/40 bg-bad/10 text-bad'"
          :title="isConnected ? 'Proveedor conectado' : 'Proveedor desconectado'"
        >
          <Wifi v-if="isConnected" class="h-4 w-4" :stroke-width="2" />
          <WifiOff v-else class="h-4 w-4" :stroke-width="2" />
        </span>
      </div>
    </div>

    <!-- Franja: hora del circuito y cuenta regresiva a la proxima sesion -->
    <div class="border-t border-race-800/70 bg-race-900/45">
      <div class="mx-auto flex max-w-[1800px] flex-wrap items-center gap-x-8 gap-y-2 px-4 py-2 lg:px-6">
        <!-- Hora del circuito -->
        <div class="flex items-center gap-2.5">
          <MapPin class="h-4 w-4 shrink-0 text-slate-500" :stroke-width="2" />
          <div class="leading-tight">
            <div class="text-[9px] uppercase tracking-[0.14em] text-slate-500">
              Hora del circuito{{ circuitTime?.place ? ` · ${circuitTime.place}` : '' }}
            </div>
            <div class="flex items-baseline gap-1.5">
              <span class="num text-[15px] font-bold leading-none text-white">
                {{ circuitTime?.clock ?? '—' }}
              </span>
              <span class="num text-[10px] text-slate-500">{{ circuitTime?.label ?? '' }}</span>
            </div>
          </div>
        </div>

        <!-- Cuenta regresiva a la proxima sesion -->
        <div v-if="nextSession" class="flex items-center gap-3">
          <Clock
            class="h-4 w-4 shrink-0"
            :class="countdownUrgent ? 'text-accent' : 'text-slate-500'"
            :stroke-width="2"
          />
          <div class="leading-tight">
            <div class="text-[9px] uppercase tracking-[0.14em] text-slate-500">Proxima sesion</div>
            <div class="text-[12px] font-semibold leading-tight text-slate-200">
              {{ nextSession.session_name }}
              <span v-if="nextStart" class="num text-slate-400">
                · {{ nextStart.local }} AR
                <template v-if="nextStart.circuit"> · {{ nextStart.circuit }} circuito</template>
              </span>
            </div>
          </div>
          <div class="leading-none">
            <div
              class="num text-[26px] font-black tracking-tight"
              :class="countdownUrgent ? 'text-accent' : 'text-white'"
            >
              {{ countdown }}
            </div>
            <div class="mt-1 text-center text-[9px] uppercase tracking-[0.18em] text-slate-500">
              faltan
            </div>
          </div>
        </div>

        <div v-else class="text-[12px] text-slate-500">
          {{ store.catalogLoaded ? 'Sin sesiones futuras en el catalogo.' : 'Cargando sesiones del Gran Premio...' }}
        </div>
      </div>
    </div>
  </header>
</template>
