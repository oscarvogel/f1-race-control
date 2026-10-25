<script setup lang="ts">
/**
 * Detalle de un piloto seguido.
 *
 * Modal con todo lo que hay del piloto en el snapshot en vivo y, debajo, la
 * comparacion con los otros pilotos que se estan siguiendo: es la razon de
 * seguir a dos o tres a la vez (delta de mejor vuelta, vueltas de diferencia
 * y cuanto se separan entre ellos).
 */
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { Flag, Gauge, Star, TriangleAlert, X } from '@lucide/vue'
import { useRaceStore } from '@/stores/race'
import { tyreStyle } from '@/utils/tyres'
import type { Driver, TimingEntry } from '@/types'

const props = defineProps<{ driverNumber: string | null }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const store = useRaceStore()

/** Escape cierra el modal: es lo que se espera de una ventana emergente. */
function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') emit('close')
}

onMounted(() => document.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => document.removeEventListener('keydown', onKeydown))

const entry = computed<TimingEntry | null>(() => {
  if (!props.driverNumber) return null
  return store.timing.find((item) => item.driver_number === props.driverNumber) ?? null
})

const driver = computed<Driver | null>(
  () =>
    entry.value?.driver ??
    store.drivers.find((item) => item.number === props.driverNumber) ??
    null,
)

const color = computed(() => {
  const value = driver.value?.team_colour
  if (!value) return '#2b3b60'
  return value.startsWith('#') ? value : `#${value}`
})

/** Velocidad instantanea: solo si el proveedor manda el canal de telemetry. */
const velocidad = computed<number | null>(() => {
  if (!props.driverNumber) return null
  const posicion = store.positions.find((item) => item.driver_number === props.driverNumber)
  return posicion?.speed ?? null
})

function gapDe(value: TimingEntry | null): string {
  if (!value) return '—'
  return value.gap_to_leader || value.time_diff_to_fastest || '—'
}

function intervaloDe(value: TimingEntry | null): string {
  if (!value) return '—'
  return value.interval_to_ahead || value.time_diff_to_position_ahead || '—'
}

const etiquetaParadas = computed(() => (store.isQualifying ? 'Cambios de neu' : 'Paradas'))

/**
 * Comparacion entre los pilotos seguidos.
 *
 * El delta de la mejor vuelta es contra el mas rapido del grupo: es la
 * diferencia que importa cuando se sigue a mas de un piloto.
 */
const comparacion = computed(() => {
  const filas = store.followedEntries
  const tiempos = filas
    .map((item) => item.best_lap_time)
    .filter((value): value is number => value != null)
  const mejor = tiempos.length ? Math.min(...tiempos) : null
  return filas.map((item) => ({
    entry: item,
    delta:
      item.best_lap_time != null && mejor != null ? item.best_lap_time - mejor : null,
  }))
})

function formatoDelta(valor: number | null): string {
  if (valor == null) return '—'
  if (Math.abs(valor) < 0.0005) return '0.000'
  return `${valor > 0 ? '+' : '-'}${Math.abs(valor).toFixed(3)}`
}
</script>

<template>
  <div
    v-if="driverNumber"
    class="fixed inset-0 z-50 flex items-center justify-center bg-race-950/85 p-4 backdrop-blur-sm"
    @click.self="emit('close')"
  >
    <section
      class="panel flex max-h-[88vh] w-full max-w-3xl flex-col overflow-hidden"
      role="dialog"
      aria-modal="true"
    >
      <!-- Cabecera -->
      <header class="flex items-center gap-3 border-b border-race-750/70 px-4 py-3">
        <span class="h-12 w-1.5 shrink-0 rounded-full" :style="{ backgroundColor: color }" />
        <div class="min-w-0 flex-1">
          <p class="truncate text-lg font-bold text-white">
            {{ driver?.full_name ?? `#${driverNumber}` }}
          </p>
          <p class="truncate text-[11px] uppercase tracking-[0.12em] text-slate-400">
            {{ driver?.team_name ?? '—' }} · #{{ driverNumber }}
            <span v-if="driver?.code" class="text-slate-600">· {{ driver.code }}</span>
          </p>
        </div>
        <div class="text-right">
          <div class="num text-3xl font-black leading-none text-white">
            {{ entry?.position ?? '—' }}
          </div>
          <div class="text-[9px] uppercase tracking-[0.14em] text-slate-500">pos</div>
        </div>
        <button
          type="button"
          class="rounded p-1.5 text-slate-500 hover:bg-race-800 hover:text-slate-200"
          title="Cerrar"
          @click="emit('close')"
        >
          <X class="h-4 w-4" />
        </button>
      </header>

      <div class="min-h-0 flex-1 overflow-auto">
        <!-- Estado -->
        <div
          v-if="entry && (entry.retired || (store.sessionIsActive && (entry.in_pit || entry.pit_out || entry.stopped)))"
          class="flex flex-wrap gap-2 border-b border-race-800/70 px-4 py-2.5"
        >
          <span v-if="entry.retired" class="chip border-bad/40 text-bad">
            <Flag class="h-3 w-3" /> Retirado
          </span>
          <span v-if="entry.in_pit && store.sessionIsActive" class="chip border-warn/40 text-warn">
            <TriangleAlert class="h-3 w-3" /> En boxes
          </span>
          <span v-if="entry.pit_out && store.sessionIsActive" class="chip border-warn/40 text-warn">
            Salida de boxes
          </span>
          <span v-if="entry.stopped && store.sessionIsActive" class="chip border-bad/40 text-bad">
            Parado en pista
          </span>
        </div>

        <!-- Datos -->
        <dl class="grid grid-cols-2 gap-x-4 gap-y-3 px-4 py-3 sm:grid-cols-3">
          <div class="min-w-0">
            <dt class="text-[9px] uppercase tracking-[0.14em] text-slate-500">Mejor vuelta</dt>
            <dd class="num truncate text-[15px] font-bold text-slate-100">
              {{ entry?.best_lap_time_display ?? '—' }}
              <span v-if="entry?.best_lap_number" class="text-[11px] font-normal text-slate-500">
                v{{ entry.best_lap_number }}
              </span>
            </dd>
          </div>
          <div class="min-w-0">
            <dt class="text-[9px] uppercase tracking-[0.14em] text-slate-500">Ultima vuelta</dt>
            <dd class="num truncate text-[15px] font-semibold text-slate-200">
              {{ entry?.last_lap_time_display ?? '—' }}
            </dd>
          </div>
          <div class="min-w-0">
            <dt class="text-[9px] uppercase tracking-[0.14em] text-slate-500">Gap al lider</dt>
            <dd class="num truncate text-[15px] font-semibold text-slate-200">
              {{ gapDe(entry) }}
            </dd>
          </div>
          <div class="min-w-0">
            <dt class="text-[9px] uppercase tracking-[0.14em] text-slate-500">Intervalo</dt>
            <dd class="num truncate text-[15px] text-slate-300">{{ intervaloDe(entry) }}</dd>
          </div>
          <div class="min-w-0">
            <dt class="text-[9px] uppercase tracking-[0.14em] text-slate-500">Vueltas</dt>
            <dd class="num text-[15px] text-slate-200">{{ entry?.number_of_laps ?? '—' }}</dd>
          </div>
          <div class="min-w-0">
            <dt class="text-[9px] uppercase tracking-[0.14em] text-slate-500">
              {{ etiquetaParadas }}
            </dt>
            <dd class="num text-[15px] text-slate-200">
              {{ entry?.number_of_pit_stops != null ? entry.number_of_pit_stops : '—' }}
            </dd>
          </div>
          <div class="min-w-0">
            <dt class="text-[9px] uppercase tracking-[0.14em] text-slate-500">Neumatico</dt>
            <dd class="flex items-center gap-1.5">
              <span
                class="flex h-6 w-6 items-center justify-center rounded-md text-[11px] font-bold"
                :style="{
                  backgroundColor: tyreStyle(entry?.tyre_compound).bg,
                  color: tyreStyle(entry?.tyre_compound).color,
                }"
              >
                {{ tyreStyle(entry?.tyre_compound).label }}
              </span>
              <span class="text-[13px] text-slate-300">
                {{ tyreStyle(entry?.tyre_compound).name }}
              </span>
            </dd>
          </div>
          <div class="min-w-0">
            <dt class="text-[9px] uppercase tracking-[0.14em] text-slate-500">Vueltas de neu</dt>
            <dd class="num text-[15px] text-slate-200">
              {{ entry?.tyre_age != null ? entry.tyre_age : '—' }}
            </dd>
          </div>
          <div class="min-w-0">
            <dt class="text-[9px] uppercase tracking-[0.14em] text-slate-500">Velocidad</dt>
            <dd class="num text-[15px] text-slate-200">
              {{ velocidad != null ? `${velocidad} km/h` : '—' }}
            </dd>
          </div>
        </dl>

        <!-- Sectores -->
        <div class="border-t border-race-800/70 px-4 py-3">
          <div class="mb-2 flex items-center gap-1.5 text-[10px] uppercase tracking-[0.14em] text-slate-500">
            <Gauge class="h-3.5 w-3.5" /> Sectores
          </div>
          <div v-if="entry?.sectors?.length" class="grid grid-cols-3 gap-2">
            <div
              v-for="sector in entry.sectors"
              :key="sector.index"
              class="rounded-lg border px-2 py-1.5 text-center"
              :class="
                sector.overall_fastest
                  ? 'border-sector-overall/50 bg-sector-overall/10'
                  : sector.personal_fastest
                    ? 'border-sector-best/40 bg-sector-best/10'
                    : 'border-race-750/70 bg-race-850/50'
              "
            >
              <div class="text-[9px] uppercase tracking-[0.14em] text-slate-500">
                S{{ sector.index + 1 }}
              </div>
              <div
                class="num text-[13px] font-bold"
                :class="
                  sector.overall_fastest
                    ? 'text-sector-overall'
                    : sector.personal_fastest
                      ? 'text-sector-best'
                      : 'text-slate-200'
                "
              >
                {{ sector.time_display ?? '—' }}
              </div>
            </div>
          </div>
          <p v-else class="text-xs text-slate-600">Sin datos de sectores.</p>
        </div>

        <!-- Comparacion entre los pilotos seguidos -->
        <div class="border-t border-race-800/70 px-4 py-3">
          <div class="mb-2 flex items-center gap-1.5 text-[10px] uppercase tracking-[0.14em] text-slate-500">
            <Star class="h-3.5 w-3.5" /> Comparacion de los pilotos seguidos
          </div>

          <table v-if="comparacion.length" class="w-full border-collapse">
            <thead>
              <tr class="border-b border-race-800/70">
                <th class="th">Piloto</th>
                <th class="th w-12">Pos</th>
                <th class="th w-24">Mejor vuelta</th>
                <th class="th w-20">Delta</th>
                <th class="th w-24">Ultima</th>
                <th class="th w-16">Vueltas</th>
                <th class="th w-20">Gap</th>
                <th class="th w-16">Neu</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="fila in comparacion"
                :key="fila.entry.driver_number"
                class="border-b border-race-850/60"
                :class="fila.entry.driver_number === driverNumber ? 'bg-accent/10' : ''"
              >
                <td class="td truncate text-[13px] text-slate-200">
                  {{ fila.entry.driver?.full_name ?? fila.entry.driver_number }}
                </td>
                <td class="td num text-[13px] text-slate-300">{{ fila.entry.position ?? '—' }}</td>
                <td class="td num text-[13px] text-slate-100">
                  {{ fila.entry.best_lap_time_display ?? '—' }}
                </td>
                <td
                  class="td num text-[12px]"
                  :class="
                    fila.delta == null
                      ? 'text-slate-600'
                      : fila.delta <= 0
                        ? 'text-sector-best'
                        : 'text-accent-soft'
                  "
                >
                  {{ formatoDelta(fila.delta) }}
                </td>
                <td class="td num text-[13px] text-slate-300">
                  {{ fila.entry.last_lap_time_display ?? '—' }}
                </td>
                <td class="td num text-[13px] text-slate-300">
                  {{ fila.entry.number_of_laps ?? '—' }}
                </td>
                <td class="td num text-[13px] text-slate-300">{{ gapDe(fila.entry) }}</td>
                <td class="td">
                  <span
                    class="flex h-5 w-5 items-center justify-center rounded text-[10px] font-bold"
                    :style="{
                      backgroundColor: tyreStyle(fila.entry.tyre_compound).bg,
                      color: tyreStyle(fila.entry.tyre_compound).color,
                    }"
                  >
                    {{ tyreStyle(fila.entry.tyre_compound).label }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
          <p v-else class="text-xs text-slate-600">
            Sin datos de los pilotos seguidos en esta sesion.
          </p>

          <p class="mt-2 text-[10px] text-slate-600">
            El delta es la diferencia de mejor vuelta contra el mas rapido del grupo.
          </p>
        </div>
      </div>

      <!-- Pie -->
      <footer class="flex items-center justify-between gap-3 border-t border-race-750/70 px-4 py-2.5">
        <span class="text-[10px] uppercase tracking-[0.12em] text-slate-600">
          Datos del snapshot en vivo
        </span>
        <button
          type="button"
          class="chip border-bad/40 text-bad hover:bg-bad/10"
          @click="store.toggleFollow(driverNumber); emit('close')"
        >
          Dejar de seguir
        </button>
      </footer>
    </section>
  </div>
</template>
