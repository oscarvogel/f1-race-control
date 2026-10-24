<script setup lang="ts">
import { computed } from 'vue'
import { CloudRain, Droplets, Gauge, Thermometer, Wind } from '@lucide/vue'
import { useRaceStore } from '@/stores/race'

const store = useRaceStore()
const weather = computed(() => store.weather)

const items = computed(() => {
  const w = weather.value
  if (!w) return []
  return [
    {
      icon: Thermometer,
      label: 'Aire',
      value: w.air_temperature != null ? `${w.air_temperature.toFixed(1)}°C` : '—',
    },
    {
      icon: Gauge,
      label: 'Pista',
      value: w.track_temperature != null ? `${w.track_temperature.toFixed(1)}°C` : '—',
    },
    {
      icon: Droplets,
      label: 'Humedad',
      value: w.humidity != null ? `${Math.round(w.humidity)}%` : '—',
    },
    {
      icon: Wind,
      label: 'Viento',
      value:
        w.wind_speed != null
          ? `${w.wind_speed.toFixed(1)} m/s${w.wind_direction != null ? ` · ${Math.round(w.wind_direction)}°` : ''}`
          : '—',
    },
    {
      icon: CloudRain,
      label: 'Lluvia',
      value: w.rainfall != null ? (w.rainfall > 0 ? 'Si' : 'No') : '—',
    },
    {
      icon: Gauge,
      label: 'Presion',
      value: w.pressure != null ? `${w.pressure.toFixed(1)} hPa` : '—',
    },
  ]
})

/**
 * Prevision del circuito (Open-Meteo).
 *
 * Es una fuente distinta a la del clima observado: el feed de F1 dice como
 * esta el circuito ahora, la prevision dice como va a estar. Se muestran
 * separadas y cada una con su origen.
 */
const forecast = computed(() => store.forecast)
const window = computed(() => store.forecastWindow)

/** Las horas de la proxima sesion, si ya se connuen. */
const forecastRows = computed(() => {
  const rows = window.value?.hourly ?? forecast.value?.hourly ?? []
  return rows.slice(0, 12)
})

/** La prevision resumida para la proxima sesion: la pregunta util. */
const windowSummary = computed(() => window.value?.summary ?? null)

const pad = (value: number) => String(value).padStart(2, '0')

/** Hora local del circuito para cada franja de la prevision. */
function localHour(iso: string): string {
  const stamp = new Date(iso.endsWith('Z') ? iso : `${iso}Z`)
  if (Number.isNaN(stamp.getTime())) return '--:--'
  const offset = store.gmtOffset
  const match = offset ? /^([+-])(\d{1,2}):?(\d{2})/.exec(offset.trim()) : null
  const minutes = match
    ? (match[1] === '-' ? -1 : 1) * (Number(match[2]) * 60 + Number(match[3]))
    : 0
  const shifted = new Date(stamp.getTime() + minutes * 60000)
  return `${pad(shifted.getUTCHours())}:${pad(shifted.getUTCMinutes())}`
}
</script>

<template>
  <section class="panel overflow-hidden">
    <header class="panel-title justify-between">
      <span>Clima</span>
      <span class="chip">{{ store.sources.weather ?? '—' }}</span>
    </header>
    <div v-if="!weather" class="px-4 py-6 text-center text-xs text-slate-500">
      Sin lectura de clima disponible.
    </div>
    <div v-else class="grid grid-cols-2 gap-x-4 gap-y-3 px-4 py-3 sm:grid-cols-3">
      <div v-for="item in items" :key="item.label" class="min-w-0">
        <div class="flex items-center gap-1.5 text-[9px] uppercase tracking-[0.14em] text-slate-500">
          <component :is="item.icon" class="h-3 w-3" />
          {{ item.label }}
        </div>
        <div class="num mt-0.5 truncate text-[14px] font-semibold text-slate-100">
          {{ item.value }}
        </div>
      </div>
    </div>

    <!-- Prevision: fuente distinta, dato distinto -->
    <div v-if="forecast" class="border-t border-race-800/60 px-4 pb-3 pt-3">
      <div class="mb-2 flex items-center justify-between gap-2">
        <span class="text-[10px] font-bold uppercase tracking-[0.16em] text-slate-400">
          Prevision del circuito
        </span>
        <span class="chip">{{ forecast.display_name }}</span>
      </div>

      <!-- Condiciones de la proxima sesion -->
      <div
        v-if="windowSummary"
        class="mb-2.5 rounded-lg border border-race-750/70 bg-race-900/60 px-3 py-2"
      >
        <div class="flex items-center justify-between gap-2">
          <span class="text-[10px] uppercase tracking-[0.12em] text-slate-500">
            {{ store.nextSessionAt(Date.now())?.session_name ?? 'Proxima sesion' }}
          </span>
          <span class="text-[11px] font-semibold text-slate-200">
            {{ windowSummary.condition }}
          </span>
        </div>
        <div class="mt-1.5 grid grid-cols-3 gap-2">
          <div>
            <div class="text-[9px] uppercase tracking-[0.12em] text-slate-500">Temp</div>
            <div class="num text-[13px] font-semibold text-slate-100">
              <template v-if="windowSummary.temperature_min != null">
                {{ windowSummary.temperature_min.toFixed(0) }}–{{
                  windowSummary.temperature_max?.toFixed(0)
                }}°C
              </template>
              <template v-else>—</template>
            </div>
          </div>
          <div>
            <div class="text-[9px] uppercase tracking-[0.12em] text-slate-500">Lluvia</div>
            <div
              class="num text-[13px] font-semibold"
              :class="
                (windowSummary.precipitation_probability_max ?? 0) > 30
                  ? 'text-warn'
                  : 'text-slate-100'
              "
            >
              <template v-if="windowSummary.precipitation_probability_max != null">
                {{ Math.round(windowSummary.precipitation_probability_max) }}%
              </template>
              <template v-else>—</template>
            </div>
          </div>
          <div>
            <div class="text-[9px] uppercase tracking-[0.12em] text-slate-500">Viento</div>
            <div class="num text-[13px] font-semibold text-slate-100">
              <template v-if="windowSummary.wind_speed_max != null">
                {{ Math.round(windowSummary.wind_speed_max) }} km/h
              </template>
              <template v-else>—</template>
            </div>
          </div>
        </div>
      </div>

      <!-- Franja horaria -->
      <div class="grid grid-cols-4 gap-x-2 gap-y-1.5 sm:grid-cols-6">
        <div v-for="row in forecastRows" :key="row.time_utc" class="min-w-0 text-center">
          <div class="num text-[10px] text-slate-500">{{ localHour(row.time_utc) }}</div>
          <div
            class="num text-[12px] font-semibold"
            :class="(row.precipitation_probability ?? 0) > 30 ? 'text-warn' : 'text-slate-100'"
          >
            {{ row.temperature != null ? `${Math.round(row.temperature)}°` : '—' }}
          </div>
          <div class="num text-[9px]" :class="(row.precipitation_probability ?? 0) > 30 ? 'text-warn' : 'text-slate-600'">
            {{ row.precipitation_probability != null ? `${Math.round(row.precipitation_probability)}%` : '—' }}
          </div>
        </div>
      </div>

      <p class="mt-2 text-[9px] leading-relaxed text-slate-600">
        Prevision de {{ forecast.display_name }} · coordenadas de {{ forecast.coordinates_source }} ·
        no es el clima observado, que viene de {{ store.sources.weather ?? 'el proveedor en vivo' }}.
      </p>
    </div>
  </section>
</template>
