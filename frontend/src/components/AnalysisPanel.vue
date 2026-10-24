<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { AlertCircle, RefreshCw, Timer } from '@lucide/vue'
import SearchSelect from '@/components/SearchSelect.vue'
import { useAnalysisStore } from '@/stores/analysis'
import { useRaceStore } from '@/stores/race'
import type { AnalysisRow } from '@/types'

const store = useRaceStore()
const analysis = useAnalysisStore()

/* ------------------------------------------------------------------ */
/* Sesiones disponibles                                                */
/* ------------------------------------------------------------------ */

/** Sesiones del Gran Premio que se pueden analizar. */
const opcionesSesion = computed(() =>
  store.sessionCatalog
    .filter((option) => option.session_key)
    .map((option) => ({
      value: option.session_key,
      label: option.session_name || option.session_type || option.session_key,
      hint: option.start_time_utc
        ? new Date(option.start_time_utc).toLocaleDateString('es-AR', {
            day: '2-digit',
            month: '2-digit',
          })
        : undefined,
    })),
)

/** La sesion que se mira ahora en el dashboard: la analizada por defecto. */
const sesionDelPanel = computed(() => {
  if (store.activeSessionKey) return store.activeSessionKey
  return store.session?.provider_session_id ?? null
})

/* ------------------------------------------------------------------ */
/* Pilotos y sesion de comparacion                                     */
/* ------------------------------------------------------------------ */

/** Pilotos de la sesion analizada, para elegir contra quien comparar. */
const opcionesPiloto = computed(() =>
  analysis.rows.map((row) => ({
    value: row.driver_number,
    label: row.code ?? row.full_name ?? `#${row.driver_number}`,
    hint: row.team ?? undefined,
  })),
)

/** Sesiones contra las que comparar la vuelta. */
const opcionesComparacion = computed(() =>
  store.sessionCatalog
    .filter((option) => option.session_key && option.session_key !== analysis.sessionKey)
    .map((option) => ({
      value: option.session_key,
      label: option.session_name || option.session_type || option.session_key,
    })),
)

const nombreComparacion = computed(() => {
  const clave = analysis.compareSessionKey
  if (!clave) return ''
  const opcion = store.sessionCatalog.find((item) => item.session_key === clave)
  return opcion?.session_name ?? clave
})

/* ------------------------------------------------------------------ */
/* Selecciones                                                         */
/* ------------------------------------------------------------------ */

const sesionElegida = ref<string | null>(null)
const pilotoElegido = ref<string | null>(null)
const comparacionElegida = ref<string | null>(null)

watch(sesionElegida, (valor) => {
  if (valor === analysis.sessionKey) return
  // Cambia la sesion: la referencia y la comparacion tambien se recalculan.
  pilotoElegido.value = null
  comparacionElegida.value = null
  analysis.referenceDriver = null
  analysis.compareSessionKey = null
  void analysis.setSession(valor)
})

watch(pilotoElegido, (valor) => {
  if (valor === analysis.referenceDriver) return
  void analysis.setReference(valor)
})

watch(comparacionElegida, (valor) => {
  if (valor === analysis.compareSessionKey) return
  void analysis.setCompare(valor)
})

/** Cuando llega la tabla, el piloto de referencia por defecto es el mas rapido. */
watch(
  () => analysis.rows.length,
  (total) => {
    if (total > 0 && pilotoElegido.value === null) {
      pilotoElegido.value = analysis.payload?.reference_driver ?? null
    }
  },
)

onMounted(() => {
  void analysis.loadChampionship()
  // Si el catalogo de sesiones ya esta, se arranca de una; si no, se espera
  // a que llegue (el watcher de abajo).
  if (opcionesSesion.value.length) {
    sesionElegida.value = sesionDelPanel.value ?? opcionesSesion.value[0].value
  }
})

/** Cuando llega el catalogo de sesiones, se elige la que se esta mirando. */
watch(
  () => store.sessionCatalog.length,
  (total) => {
    if (total > 0 && !sesionElegida.value) {
      sesionElegida.value = sesionDelPanel.value ?? opcionesSesion.value[0]?.value ?? null
    }
  },
)

/* ------------------------------------------------------------------ */
/* Presentacion                                                        */
/* ------------------------------------------------------------------ */

/** Un delta negativo es mas rapido: verde. Positivo, mas lento: rojo. */
function colorDelta(valor: number | null): string {
  if (valor == null) return 'text-slate-600'
  if (valor < 0) return 'text-ok'
  if (valor > 0) return 'text-bad'
  return 'text-slate-500'
}

function delta(valor: number | null): string {
  if (valor == null) return '—'
  if (valor === 0) return '0.000'
  return `${valor > 0 ? '+' : ''}${valor.toFixed(3)}`
}

function colorEquipo(row: AnalysisRow): string {
  const color = row.team_colour
  if (!color) return '#2b3b60'
  return color.startsWith('#') ? color : `#${color}`
}

const COMPOUND: Record<string, string> = {
  SOFT: '#ff5a6e',
  MEDIUM: '#f5a623',
  HARD: '#e2e8f0',
  INTERMEDIATE: '#2ecc71',
  WET: '#60a5fa',
}

function colorNeumatico(compound: string | null): string {
  if (!compound) return '#64748b'
  return COMPOUND[compound.toUpperCase()] ?? '#94a3b8'
}
</script>

<template>
  <section class="panel flex min-h-0 flex-col overflow-hidden">
    <header class="panel-title justify-between">
      <span class="flex items-center gap-2">
        <Timer class="h-3.5 w-3.5" :stroke-width="2" />
        Analisis
      </span>
      <div class="flex items-center gap-2">
        <span class="chip">{{ analysis.payload?.source ?? '—' }}</span>
        <button
          type="button"
          class="rounded p-1 text-slate-500 transition hover:text-white"
          title="Volver a pedir el analisis"
          @click="analysis.loadAnalysis(analysis.sessionKey)"
        >
          <RefreshCw class="h-3.5 w-3.5" :class="{ 'animate-spin': analysis.loading }" />
        </button>
      </div>
    </header>

    <!-- Selectores -->
    <div class="grid grid-cols-1 gap-3 border-b border-race-750/60 px-4 py-3 sm:grid-cols-3">
      <div>
        <label class="mb-1 block text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500">
          Sesion
        </label>
        <SearchSelect
          v-model="sesionElegida"
          :options="opcionesSesion"
          placeholder="Sesion a analizar"
          :disabled="analysis.loading"
        />
      </div>
      <div>
        <label class="mb-1 block text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500">
          Comparar contra
        </label>
        <SearchSelect
          v-model="pilotoElegido"
          :options="opcionesPiloto"
          placeholder="Piloto"
          allow-empty
          empty-label="El mas rapido"
          :disabled="analysis.loading"
        />
      </div>
      <div>
        <label class="mb-1 block text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500">
          Comparar sesion
        </label>
        <SearchSelect
          v-model="comparacionElegida"
          :options="opcionesComparacion"
          placeholder="Sin comparacion"
          allow-empty
          empty-label="Sin comparacion"
          :disabled="analysis.loading"
        />
      </div>
    </div>

    <!-- Errores -->
    <p
      v-if="analysis.error"
      class="flex items-start gap-2 border-b border-bad/30 bg-bad/10 px-4 py-2 text-[12px] text-bad"
    >
      <AlertCircle class="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <span>{{ analysis.error }}</span>
    </p>

    <!-- Tabla -->
    <div class="min-h-0 flex-1 overflow-auto">
      <table class="w-full border-collapse">
        <thead class="sticky top-0 z-10 bg-race-900/95 backdrop-blur">
          <tr class="border-b border-race-750/60">
            <th class="th w-8">P</th>
            <th class="th">Piloto</th>
            <th class="th text-right">Mejor vuelta</th>
            <th class="th text-right">Δ</th>
            <th class="th text-right">S1</th>
            <th class="th text-right">S2</th>
            <th class="th text-right">S3</th>
            <th v-if="nombreComparacion" class="th text-right">Δ {{ nombreComparacion }}</th>
            <th class="th w-14 text-right">Neu</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in analysis.rows"
            :key="row.driver_number"
            class="border-b border-race-800/50 transition hover:bg-race-800/30"
            :class="row.driver_number === analysis.payload?.reference_driver ? 'bg-race-800/40' : ''"
          >
            <td class="td num text-slate-500">{{ row.position }}</td>
            <td class="td">
              <div class="flex items-center gap-2">
                <span
                  class="h-5 w-1 shrink-0 rounded-full"
                  :style="{ backgroundColor: colorEquipo(row) }"
                />
                <span class="num w-6 shrink-0 text-[11px] text-slate-500">
                  #{{ row.driver_number }}
                </span>
                <span class="truncate text-[12px] text-slate-200">
                  {{ row.code ?? row.full_name ?? '—' }}
                </span>
                <span class="hidden truncate text-[11px] text-slate-500 lg:inline">
                  {{ row.team ?? '' }}
                </span>
              </div>
            </td>
            <td class="td num text-right text-[13px] text-white">
              {{ row.lap_time_display ?? '—' }}
              <span class="ml-1 text-[10px] text-slate-500">v{{ row.lap_number ?? '?' }}</span>
            </td>
            <td class="td num text-right text-[12px]" :class="colorDelta(row.delta_to_fastest)">
              {{ delta(row.delta_to_fastest) }}
            </td>

            <!-- Sectores: tiempo y delta contra el piloto de referencia -->
            <td
              v-for="sector in row.sectors"
              :key="sector.index"
              class="td text-right"
            >
              <div
                class="num text-[13px]"
                :class="sector.is_fastest ? 'text-fastest' : 'text-slate-200'"
              >
                {{ sector.display ?? '—' }}
              </div>
              <div class="num text-[10px]" :class="colorDelta(sector.delta_to_reference)">
                {{ delta(sector.delta_to_reference) }}
              </div>
            </td>

            <td v-if="nombreComparacion" class="td num text-right text-[12px]">
              <div :class="colorDelta(row.compare?.delta_lap ?? null)">
                {{ delta(row.compare?.delta_lap ?? null) }}
              </div>
              <div class="num text-[10px] text-slate-600">
                {{ row.compare?.lap_time_display ?? '—' }}
              </div>
            </td>

            <td class="td text-right">
              <span
                class="inline-flex items-center gap-1 text-[10px]"
                :title="`${row.compound ?? '—'} · edad ${row.tyre_age ?? '—'}`"
              >
                <span
                  class="h-2.5 w-2.5 rounded-full ring-1 ring-race-700"
                  :style="{ backgroundColor: colorNeumatico(row.compound) }"
                />
                <span class="num text-slate-500">{{ row.tyre_age ?? '—' }}</span>
              </span>
            </td>
          </tr>
        </tbody>
      </table>

      <p
        v-if="!analysis.rows.length && !analysis.loading"
        class="px-4 py-10 text-center text-[12px] text-slate-500"
      >
        Sin datos de analisis para esta sesion.
      </p>
      <p v-if="analysis.loading" class="px-4 py-10 text-center text-[12px] text-slate-500">
        Calculando el analisis...
      </p>
    </div>

    <!-- Pie: de donde salen los datos -->
    <footer
      v-if="analysis.payload?.fastest"
      class="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-race-750/60 px-4 py-2 text-[11px] text-slate-500"
    >
      <span>
        Mas rapido:
        <span class="num text-slate-300">
          {{ analysis.payload.fastest.lap_time_display ?? '—' }}
        </span>
      </span>
      <span class="hidden sm:inline">
        Sectores de OpenF1: suman exactamente el tiempo de la vuelta.
      </span>
    </footer>
  </section>
</template>
