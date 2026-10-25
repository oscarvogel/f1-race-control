<script setup lang="ts">
import { computed } from 'vue'
import { ChevronDown, ChevronUp, Clock } from '@lucide/vue'
import { useClock } from '@/composables/useClock'
import { useRaceStore, type SortKey } from '@/stores/race'
import type { TimingEntry } from '@/types'

const store = useRaceStore()

/** Reloj compartido: la cuenta regresiva no puede ir por detras de la cabecera. */
const now = useClock()

const pad = (value: number) => String(value).padStart(2, '0')

const COMPOUND_STYLE: Record<string, { label: string; bg: string; text: string }> = {
  SOFT: { label: 'S', bg: 'rgba(232,17,45,0.18)', text: '#ff5a6e' },
  MEDIUM: { label: 'M', bg: 'rgba(245,166,35,0.18)', text: '#f5a623' },
  HARD: { label: 'H', bg: 'rgba(226,232,240,0.14)', text: '#e2e8f0' },
  INTERMEDIATE: { label: 'I', bg: 'rgba(46,204,113,0.18)', text: '#2ecc71' },
  WET: { label: 'W', bg: 'rgba(59,130,246,0.18)', text: '#60a5fa' },
}

function compoundStyle(compound: string | null) {
  if (!compound) return { label: '—', bg: 'transparent', text: '#64748b' }
  return COMPOUND_STYLE[compound.toUpperCase()] ?? { label: compound.slice(0, 1), bg: 'transparent', text: '#94a3b8' }
}

/**
 * Neumatico de la fila.
 *
 * El feed en vivo lo trae en la propia entrada de clasificacion. En el
 * historico de OpenF1 hay que resolverlo desde los stints de la sesion.
 */
function compoundOf(entry: TimingEntry): string | null {
  return entry.tyre_compound ?? store.compoundByDriver[entry.driver_number] ?? null
}

function teamColour(entry: TimingEntry): string {
  const colour = entry.driver?.team_colour
  if (!colour) return '#2b3b60'
  return colour.startsWith('#') ? colour : `#${colour}`
}

function isOverallFastestSector(entry: TimingEntry, index: number): boolean {
  const set = store.overallBestSectors[index]
  return set ? set.has(entry.driver_number) : false
}

/** Distincion de gap: en clasificacion el feed usa TimeDiffToFastest. */
function gapOf(entry: TimingEntry): string {
  if (entry.gap_to_leader) return entry.gap_to_leader
  if (entry.time_diff_to_fastest) return entry.time_diff_to_fastest
  return '—'
}

function intervalOf(entry: TimingEntry): string {
  return entry.interval_to_ahead ?? entry.time_diff_to_position_ahead ?? '—'
}

/**
 * Segmento al que pertenece el gap (Q1/Q2/Q3).
 *
 * El feed publica los gaps por segmento de clasificacion. El indice llega
 * crudo ("0", "1", "2") y solo se traduce cuando la sesion **es** una
 * clasificacion: en carrera el indice "0" es la vuelta actual, y llamarle
 * Q1 seria mentir.
 *
 * Ademas se exige que el piloto tenga una vuelta **completada** en ese
 * segmento. Para quien esta en pista, el feed escribe el delta en vivo en
 * el primer slot aunque su segmento actual sea el segundo: etiquetar ese
 * valor "Q1" seria falso. Sin vuelta cerrada en ese segmento, el gap se
 * muestra igual pero sin etiqueta.
 */
const SEGMENT_LABELS: Record<string, string> = { '0': 'Q1', '1': 'Q2', '2': 'Q3' }

function gapSegmentOf(entry: TimingEntry): string | null {
  if (!store.isQualifying) return null
  const index = entry.time_diff_to_fastest_segment ?? entry.time_diff_to_position_ahead_segment
  if (!index) return null
  const label = SEGMENT_LABELS[index]
  if (!label) return null
  const lap = entry.best_lap_times?.[label]
  if (!lap || lap.time == null) return null
  return label
}

/**
 * Cuenta regresiva del final de la sesion en curso.
 *
 * El feed publica `SessionInfo.EndDate` en hora local del circuito, que el
 * backend convierte a UTC con el `GmtOffset` de la propia F1. En
 * clasificacion es el final del bloque Q1/Q2/Q3 completo.
 *
 * Solo se muestra mientras la sesion esta en curso: en una sesion ya
 * terminada (o en una que todavia no empezo) la cuenta seria enganosa.
 *
 * Cuando el horario se agota pero la sesion sigue en curso (el ultimo piloto
 * de Q3 todavia esta en pista), el contador no desaparece: pasa a "TIEMPO
 * AGOTADO", que es lo que dice el cronometro de la F1.
 */
const sessionCountdown = computed<string | null>(() => {
  if (!store.sessionIsActive) return null
  const remaining = store.sessionEndsInMs(now.value.getTime())
  if (remaining === null) return null
  if (remaining <= 0) return '00:00:00'
  const total = Math.floor(remaining / 1000)
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = total % 60
  return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`
})

/** El tiempo se agota: el contador queda en rojo. */
const countdownUrgent = computed(() => {
  const remaining = store.sessionEndsInMs(now.value.getTime())
  if (remaining === null) return false
  return remaining <= 5 * 60 * 1000
})

/** Etiqueta del contador: el tiempo se cumplio o todavia queda. */
const countdownLabel = computed(() => {
  const remaining = store.sessionEndsInMs(now.value.getTime())
  if (remaining === null) return ''
  return remaining <= 0 ? 'TIEMPO AGOTADO' : 'FINALIZA EN'
})

function segmentTime(entry: TimingEntry, segment: 'Q1' | 'Q2' | 'Q3'): string {
  const value = entry.best_lap_times?.[segment]
  return value?.time_display ?? '—'
}

/**
 * Segmento del que viene el tiempo de clasificacion (Q1/Q2/Q3).
 *
 * En una eliminatoria el piloto se clasifica con el tiempo del **ultimo
 * segmento alcanzado**, no con el mas rapido de la sesion: en Austin 2026,
 * Leclerc se clasificó con su Q3 (1:34.267) aunque su Q2 (1:34.198) fuera mas
 * rapido, y Norris con su Q3 (1:35.049) aunque su mejor vuelta de la sesion
 * fuera una vuelta anulada de 1:34.379.
 *
 * Sin la etiqueta, un 1:34.267 de Q3 al lado de un 1:34.198 de Q2 parece un
 * error de la app. Se toma el **ultimo** segmento que coincide: si un piloto
 * repite un tiempo, el que cuenta es el del segmento mas avanzado.
 */
function bestLapSegmentOf(entry: TimingEntry): string | null {
  if (!store.isQualifying) return null
  if (entry.best_lap_time == null) return null
  let encontrado: string | null = null
  for (const segment of ['Q1', 'Q2', 'Q3'] as const) {
    const lap = entry.best_lap_times?.[segment]
    if (!lap || lap.time == null) continue
    if (Math.abs(lap.time - entry.best_lap_time) < 0.002) encontrado = segment
  }
  return encontrado
}

function isOverallFastestLap(entry: TimingEntry): boolean {
  return (
    entry.best_lap_time != null &&
    store.sessionFastestLap != null &&
    entry.best_lap_time === store.sessionFastestLap
  )
}

const showQualifyingColumns = computed(() => store.isQualifying)

const sorted = computed<TimingEntry[]>(() => {
  const rows = [...store.timing]
  const key = store.sortKey
  const dir = store.sortAsc ? 1 : -1

  const value = (entry: TimingEntry): number | string | null => {
    switch (key) {
      case 'position':
        return entry.position
      case 'driver':
        return entry.driver?.full_name ?? ''
      case 'team':
        return entry.driver?.team_name ?? ''
      case 'q1':
        return entry.best_lap_times?.Q1?.time ?? null
      case 'q2':
        return entry.best_lap_times?.Q2?.time ?? null
      case 'q3':
        return entry.best_lap_times?.Q3?.time ?? null
      case 'gap':
        return entry.time_diff_to_fastest ?? entry.gap_to_leader ?? null
      case 'laps':
        return entry.number_of_laps
      case 'tyre':
        return compoundOf(entry) ?? ''
      case 'best':
        return entry.best_lap_time
      default:
        return entry.position
    }
  }

  rows.sort((a, b) => {
    const va = value(a)
    const vb = value(b)
    // Los nulos siempre al final, sin importar la direccion.
    if (va === null && vb === null) return 0
    if (va === null) return 1
    if (vb === null) return -1
    if (typeof va === 'number' && typeof vb === 'number') return (va - vb) * dir
    return String(va).localeCompare(String(vb), 'es') * dir
  })
  return rows
})

function headerClick(key: SortKey) {
  store.setSort(key)
}

function sortIcon(key: SortKey) {
  if (store.sortKey !== key) return null
  return store.sortAsc ? 'up' : 'down'
}
</script>

<template>
  <section class="panel flex min-h-0 flex-col overflow-hidden">
    <header class="panel-title justify-between">
      <span>Clasificacion</span>
      <span class="flex items-center gap-2">
        <span
          v-if="sessionCountdown"
          class="chip num gap-1.5 border-warn/40 text-warn"
          :class="countdownUrgent ? 'border-bad/60 bg-bad/15 text-bad' : ''"
          title="Tiempo que falta para que termine la sesion"
        >
          <Clock class="h-3 w-3" />
          {{ countdownLabel }} {{ sessionCountdown }}
        </span>
        <span class="chip">{{ sorted.length }} pilotos</span>
        <span v-if="store.dataState === 'HISTORICAL'" class="chip text-sky-300">
          Sesion finalizada
        </span>
      </span>
    </header>

    <div class="min-h-0 flex-1 overflow-auto">
      <table class="w-full min-w-[860px] border-collapse">
        <thead class="sticky top-0 z-10 bg-race-900/95 backdrop-blur">
          <tr class="border-b border-race-750/70">
            <th class="th w-12 cursor-pointer select-none" @click="headerClick('position')">
              <span class="inline-flex items-center gap-1">
                POS
                <ChevronUp v-if="sortIcon('position') === 'up'" class="h-3 w-3 text-accent" />
                <ChevronDown v-if="sortIcon('position') === 'down'" class="h-3 w-3 text-accent" />
              </span>
            </th>
            <th class="th cursor-pointer select-none" @click="headerClick('driver')">
              <span class="inline-flex items-center gap-1">
                PILOTO
                <ChevronUp v-if="sortIcon('driver') === 'up'" class="h-3 w-3 text-accent" />
                <ChevronDown v-if="sortIcon('driver') === 'down'" class="h-3 w-3 text-accent" />
              </span>
            </th>
            <th class="th cursor-pointer select-none" @click="headerClick('team')">
              <span class="inline-flex items-center gap-1">
                EQUIPO
                <ChevronUp v-if="sortIcon('team') === 'up'" class="h-3 w-3 text-accent" />
                <ChevronDown v-if="sortIcon('team') === 'down'" class="h-3 w-3 text-accent" />
              </span>
            </th>
            <th v-if="showQualifyingColumns" class="th w-24 cursor-pointer select-none" @click="headerClick('q1')">
              Q1
            </th>
            <th v-if="showQualifyingColumns" class="th w-24 cursor-pointer select-none" @click="headerClick('q2')">
              Q2
            </th>
            <th v-if="showQualifyingColumns" class="th w-24 cursor-pointer select-none" @click="headerClick('q3')">
              Q3
            </th>
            <th class="th w-28 cursor-pointer select-none" @click="headerClick('best')">MEJOR VUELTA</th>
            <th class="th w-24 cursor-pointer select-none" @click="headerClick('gap')">GAP</th>
            <th class="th w-16 cursor-pointer select-none" @click="headerClick('laps')">VUELTAS</th>
            <th class="th w-24 cursor-pointer select-none" @click="headerClick('tyre')">NEUMATICO</th>
          </tr>
        </thead>

        <tbody>
          <tr
            v-for="entry in sorted"
            :key="entry.driver_number"
            class="cursor-pointer border-b border-race-800/60 transition-colors"
            :class="[
              store.selectedDriver === entry.driver_number
                ? 'bg-accent/10'
                : 'hover:bg-race-850/60',
              entry.retired ? 'opacity-55' : '',
            ]"
            @click="store.selectDriver(entry.driver_number)"
            @dblclick="store.toggleCompare(entry.driver_number)"
          >
            <td class="td">
              <div class="flex items-center gap-2">
                <span
                  class="h-7 w-1 shrink-0 rounded-full"
                  :style="{ backgroundColor: teamColour(entry) }"
                />
                <span
                  class="num text-[15px] font-bold"
                  :class="entry.position === 1 ? 'text-white' : 'text-slate-300'"
                >
                  {{ entry.position ?? '—' }}
                </span>
              </div>
            </td>

            <td class="td">
              <div class="flex items-center gap-2">
                <span class="num w-7 shrink-0 text-[11px] font-semibold text-slate-500">
                  #{{ entry.driver_number }}
                </span>
                <span class="truncate font-semibold text-slate-100">
                  {{ entry.driver?.full_name ?? entry.driver_number }}
                </span>
                <span
                  v-if="store.compareDriver === entry.driver_number"
                  class="chip border-accent/50 text-accent"
                >
                  COMPARAR
                </span>
                <span
                  v-if="entry.in_pit && store.sessionIsActive"
                  class="chip border-warn/40 text-warn"
                  title="En boxes"
                >
                  PIT
                </span>
                <span v-if="entry.retired" class="chip border-bad/40 text-bad">DNF</span>
              </div>
            </td>

            <td class="td">
              <span class="truncate text-[13px] text-slate-400">
                {{ entry.driver?.team_name ?? '—' }}
              </span>
            </td>

            <td v-if="showQualifyingColumns" class="td">
              <span
                class="num text-[13px]"
                :class="segmentTime(entry, 'Q1') === '—' ? 'text-slate-600' : 'text-slate-200'"
              >
                {{ segmentTime(entry, 'Q1') }}
              </span>
            </td>
            <td v-if="showQualifyingColumns" class="td">
              <span
                class="num text-[13px]"
                :class="segmentTime(entry, 'Q2') === '—' ? 'text-slate-600' : 'text-slate-200'"
              >
                {{ segmentTime(entry, 'Q2') }}
              </span>
            </td>
            <td v-if="showQualifyingColumns" class="td">
              <span
                class="num text-[13px]"
                :class="segmentTime(entry, 'Q3') === '—' ? 'text-slate-600' : 'text-slate-200'"
              >
                {{ segmentTime(entry, 'Q3') }}
              </span>
            </td>

            <td class="td">
              <div class="flex items-center gap-2">
                <span
                  class="num text-[13px] font-semibold"
                  :class="
                    isOverallFastestLap(entry)
                      ? 'text-fastest'
                      : entry.best_lap_time_display
                        ? 'text-slate-200'
                        : 'text-slate-600'
                  "
                >
                  {{ entry.best_lap_time_display ?? '—' }}
                </span>
                <span
                  v-if="bestLapSegmentOf(entry)"
                  class="rounded bg-race-800/80 px-1 py-0.5 text-[9px] font-bold uppercase tracking-wider text-slate-400"
                  :title="`Tiempo de clasificacion del segmento ${bestLapSegmentOf(entry)}`"
                >
                  {{ bestLapSegmentOf(entry) }}
                </span>
                <span
                  v-if="isOverallFastestLap(entry)"
                  class="rounded bg-fastest/20 px-1 py-0.5 text-[9px] font-bold uppercase tracking-wider text-fastest"
                >
                 mejor
                </span>
                <span
                  v-if="entry.best_lap_number"
                  class="num text-[10px] text-slate-600"
                >
                  v{{ entry.best_lap_number }}
                </span>
              </div>
            </td>

            <td class="td">
              <div class="flex items-center gap-1.5">
                <span class="num text-[12px] text-slate-300">
                  {{ gapOf(entry) }}
                </span>
                <span
                  v-if="gapSegmentOf(entry)"
                  class="rounded bg-race-800/80 px-1 py-0.5 text-[9px] font-bold uppercase tracking-wider text-slate-400"
                  :title="`Gap del segmento ${gapSegmentOf(entry)}`"
                >
                  {{ gapSegmentOf(entry) }}
                </span>
              </div>
              <div
                v-if="intervalOf(entry) !== gapOf(entry) && intervalOf(entry) !== '—'"
                class="num text-[10px] text-slate-600"
                title="Intervalo respecto del piloto de adelante"
              >
                {{ intervalOf(entry) }}
              </div>
            </td>

            <td class="td">
              <span class="num text-[13px] text-slate-300">{{ entry.number_of_laps ?? '—' }}</span>
            </td>

            <td class="td">
              <div class="flex items-center gap-1.5">
                <span
                  class="flex h-6 w-6 items-center justify-center rounded-md text-[11px] font-bold"
                  :style="{ backgroundColor: compoundStyle(compoundOf(entry)).bg, color: compoundStyle(compoundOf(entry)).text }"
                  :title="compoundOf(entry) ?? 'Sin pneumatico'"
                >
                  {{ compoundStyle(compoundOf(entry)).label }}
                </span>
                <span class="num text-[11px] text-slate-500">
                  {{ entry.tyre_age != null ? `v${entry.tyre_age}` : '' }}
                </span>
              </div>
            </td>
          </tr>

          <tr v-if="sorted.length === 0">
            <td :colspan="showQualifyingColumns ? 10 : 7" class="px-4 py-10 text-center">
              <p class="text-sm text-slate-500">
                Sin datos de clasificacion disponibles.
              </p>
              <p class="mt-1 text-xs text-slate-600">
                {{ store.error ?? 'El proceso de ingesta puede no estar corriendo todavia.' }}
              </p>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
