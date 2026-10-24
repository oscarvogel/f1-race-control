<script setup lang="ts">
import { computed } from 'vue'
import { Flag, Gauge, Timer, TriangleAlert } from '@lucide/vue'
import { useRaceStore } from '@/stores/race'

const store = useRaceStore()

const entry = computed(() => store.selectedEntry)
const compare = computed(() => store.compareEntry)

const teamColour = computed(() => {
  const colour = entry.value?.driver?.team_colour
  if (!colour) return '#2b3b60'
  return colour.startsWith('#') ? colour : `#${colour}`
})

const rows = computed(() => {
  const e = entry.value
  if (!e) return []
  return [
    { label: 'Posicion', value: e.position != null ? `P${e.position}` : '—' },
    { label: 'Mejor vuelta', value: e.best_lap_time_display ?? '—' },
    { label: 'Ultima vuelta', value: e.last_lap_time_display ?? '—' },
    { label: 'Gap al lider', value: e.gap_to_leader ?? e.time_diff_to_fastest ?? '—' },
    { label: 'Intervalo', value: e.interval_to_ahead ?? e.time_diff_to_position_ahead ?? '—' },
    { label: 'Vueltas', value: e.number_of_laps != null ? String(e.number_of_laps) : '—' },
    { label: 'Paradas', value: e.number_of_pit_stops != null ? String(e.number_of_pit_stops) : '—' },
    { label: 'Neumatico', value: e.tyre_compound ?? '—' },
    { label: 'Vueltas de pneu', value: e.tyre_age != null ? String(e.tyre_age) : '—' },
  ]
})

const sectorRows = computed(() => {
  const e = entry.value
  if (!e?.sectors?.length) return []
  return e.sectors.map((sector) => ({
    index: sector.index,
    display: sector.time_display ?? '—',
    personal: sector.personal_fastest,
    overall: sector.overall_fastest,
  }))
})

/** Diferencia de mejor vuelta entre el piloto y el comparador. */
const comparison = computed(() => {
  if (!entry.value || !compare.value) return null
  const a = entry.value.best_lap_time
  const b = compare.value.best_lap_time
  if (a == null || b == null) return null
  const delta = a - b
  return {
    delta,
    display: `${delta >= 0 ? '+' : '-'}${Math.abs(delta).toFixed(3)} s`,
    faster: delta < 0,
  }
})
</script>

<template>
  <section class="panel overflow-hidden">
    <header class="panel-title justify-between">
      <span>Piloto seleccionado</span>
      <span v-if="entry" class="chip">#{{ entry.driver_number }}</span>
    </header>

    <div v-if="!entry" class="px-4 py-8 text-center text-sm text-slate-500">
      Selecciona un piloto en la clasificacion.
    </div>

    <div v-else>
      <!-- Identidad -->
      <div class="flex items-center gap-3 border-b border-race-800/70 px-4 py-3">
        <span class="h-10 w-1.5 shrink-0 rounded-full" :style="{ backgroundColor: teamColour }" />
        <div class="min-w-0 flex-1">
          <p class="truncate text-base font-bold text-white">
            {{ entry.driver?.full_name ?? entry.driver_number }}
          </p>
          <p class="truncate text-[12px] text-slate-400">
            {{ entry.driver?.team_name ?? '—' }}
            <span v-if="entry.driver?.code" class="text-slate-600"> · {{ entry.driver.code }}</span>
          </p>
        </div>
        <div class="text-right">
          <div class="num text-2xl font-black text-white">{{ entry.position ?? '—' }}</div>
          <div class="text-[9px] uppercase tracking-[0.14em] text-slate-500">pos</div>
        </div>
      </div>

      <!-- Avisos -->
      <div
        v-if="store.sessionIsActive && (entry.in_pit || entry.retired || entry.stopped)"
        class="flex flex-wrap gap-2 px-4 py-2.5"
      >
        <span v-if="entry.in_pit" class="chip border-warn/40 text-warn">
          <TriangleAlert class="h-3 w-3" /> En boxes
        </span>
        <span v-if="entry.retired" class="chip border-bad/40 text-bad">
          <Flag class="h-3 w-3" /> Retirado
        </span>
        <span v-if="entry.stopped" class="chip border-bad/40 text-bad">Parado en pista</span>
      </div>

      <!-- Datos -->
      <dl class="grid grid-cols-2 gap-x-4 gap-y-2.5 px-4 py-3 sm:grid-cols-3">
        <div v-for="row in rows" :key="row.label" class="min-w-0">
          <dt class="text-[9px] uppercase tracking-[0.14em] text-slate-500">{{ row.label }}</dt>
          <dd class="num truncate text-[13px] font-semibold text-slate-100">{{ row.value }}</dd>
        </div>
      </dl>

      <!-- Sectores -->
      <div class="border-t border-race-800/70 px-4 py-3">
        <div class="mb-2 flex items-center gap-1.5 text-[10px] uppercase tracking-[0.14em] text-slate-500">
          <Gauge class="h-3.5 w-3.5" /> Sectores
        </div>
        <div v-if="sectorRows.length" class="grid grid-cols-3 gap-2">
          <div
            v-for="sector in sectorRows"
            :key="sector.index"
            class="rounded-lg border px-2 py-1.5 text-center"
            :class="
              sector.overall
                ? 'border-sector-overall/50 bg-sector-overall/10'
                : sector.personal
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
                sector.overall
                  ? 'text-sector-overall'
                  : sector.personal
                    ? 'text-sector-best'
                    : 'text-slate-200'
              "
            >
              {{ sector.display }}
            </div>
          </div>
        </div>
        <p v-else class="text-xs text-slate-600">Sin datos de sectores.</p>
      </div>

      <!-- Comparacion -->
      <div v-if="compare && compare.driver_number !== entry.driver_number" class="border-t border-race-800/70 px-4 py-3">
        <div class="mb-2 flex items-center gap-1.5 text-[10px] uppercase tracking-[0.14em] text-slate-500">
          <Timer class="h-3.5 w-3.5" /> Comparacion con {{ compare.driver?.full_name ?? compare.driver_number }}
        </div>
        <div class="grid grid-cols-3 gap-2 text-center">
          <div class="rounded-lg border border-race-750/70 bg-race-850/50 px-2 py-2">
            <div class="text-[9px] uppercase tracking-[0.14em] text-slate-500">Mejor vuelta</div>
            <div class="num text-[13px] font-bold text-slate-100">
              {{ entry.best_lap_time_display ?? '—' }}
            </div>
            <div class="num text-[10px] text-slate-500">
              {{ compare.best_lap_time_display ?? '—' }}
            </div>
          </div>
          <div class="rounded-lg border border-race-750/70 bg-race-850/50 px-2 py-2">
            <div class="text-[9px] uppercase tracking-[0.14em] text-slate-500">Vueltas</div>
            <div class="num text-[13px] font-bold text-slate-100">
              {{ entry.number_of_laps ?? '—' }}
            </div>
            <div class="num text-[10px] text-slate-500">
              {{ compare.number_of_laps ?? '—' }}
            </div>
          </div>
          <div class="rounded-lg border border-race-750/70 bg-race-850/50 px-2 py-2">
            <div class="text-[9px] uppercase tracking-[0.14em] text-slate-500">Diferencia</div>
            <div
              class="num text-[13px] font-bold"
              :class="comparison ? (comparison.faster ? 'text-sector-best' : 'text-accent-soft') : 'text-slate-600'"
            >
              {{ comparison?.display ?? '—' }}
            </div>
            <div class="text-[10px] text-slate-500">mejor vuelta</div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
