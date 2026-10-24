<script setup lang="ts">
import { computed } from 'vue'
import { CircleDot } from '@lucide/vue'
import { useRaceStore } from '@/stores/race'
import type { TimingEntry } from '@/types'

const store = useRaceStore()

const COMPOUND: Record<string, { label: string; color: string }> = {
  SOFT: { label: 'SOFT', color: '#ff5a6e' },
  MEDIUM: { label: 'MEDIUM', color: '#f5a623' },
  HARD: { label: 'HARD', color: '#e2e8f0' },
  INTERMEDIATE: { label: 'INTER', color: '#2ecc71' },
  WET: { label: 'WET', color: '#60a5fa' },
}

function style(compound: string | null) {
  if (!compound) return { label: '—', color: '#64748b' }
  return COMPOUND[compound.toUpperCase()] ?? { label: compound, color: '#94a3b8' }
}

function teamColour(entry: TimingEntry): string {
  const colour = entry.driver?.team_colour
  if (!colour) return '#2b3b60'
  return colour.startsWith('#') ? colour : `#${colour}`
}

/** Stints por piloto, ordenados para el grafico de estrategia. */
const stintsByDriver = computed(() => {
  const map: Record<string, { compound: string | null; total: number | null }[]> = {}
  for (const stint of store.snapshot?.tyres ?? []) {
    if (!map[stint.driver_number]) map[stint.driver_number] = []
    map[stint.driver_number].push({
      compound: stint.compound,
      total: stint.total_laps ?? stint.tyre_age_at_start,
    })
  }
  return map
})

const rows = computed(() =>
  store.timing.map((entry) => ({
    entry,
    // En el historico el compuesto no viene en la entrada de clasificacion:
    // se resuelve desde los stints de la sesion.
    tyre: style(entry.tyre_compound ?? store.compoundByDriver[entry.driver_number] ?? null),
    stints: stintsByDriver.value[entry.driver_number] ?? [],
  })),
)
</script>

<template>
  <section class="panel flex min-h-0 flex-col overflow-hidden">
    <header class="panel-title justify-between">
      <span>Neumaticos</span>
      <span class="chip">{{ store.sources.tyres ?? '—' }}</span>
    </header>
    <div class="min-h-0 flex-1 overflow-auto">
      <ul class="divide-y divide-race-800/60">
        <li v-for="row in rows" :key="row.entry.driver_number" class="flex items-center gap-2.5 px-4 py-1.5">
          <span class="h-6 w-1 shrink-0 rounded-full" :style="{ backgroundColor: teamColour(row.entry) }" />
          <span class="num w-7 shrink-0 text-[11px] text-slate-500">#{{ row.entry.driver_number }}</span>
          <span class="w-28 shrink-0 truncate text-[12px] text-slate-300">
            {{ row.entry.driver?.code ?? row.entry.driver?.full_name ?? '—' }}
          </span>

          <!-- Secuencia de stints -->
          <span class="flex min-w-0 flex-1 items-center gap-0.5">
            <span
              v-for="(stint, index) in row.stints"
              :key="index"
              class="h-2.5 min-w-[6px] rounded-sm"
              :style="{
                backgroundColor: style(stint.compound).color,
                flexGrow: Math.max(1, stint.total ?? 1),
                opacity: stint.compound === row.entry.tyre_compound ? 1 : 0.35,
              }"
              :title="`${stint.compound ?? '—'} · ${stint.total ?? '?'} vueltas`"
            />
            <span v-if="!row.stints.length" class="text-[11px] text-slate-600">sin stints</span>
          </span>

          <span class="flex shrink-0 items-center gap-1">
            <CircleDot
              class="h-3.5 w-3.5"
              :style="{ color: row.tyre.color }"
            />
            <span class="num text-[10px] text-slate-500">
              {{ row.entry.tyre_age != null ? `v${row.entry.tyre_age}` : '' }}
            </span>
          </span>
        </li>
      </ul>
      <p v-if="!rows.length" class="px-4 py-8 text-center text-xs text-slate-500">
        Sin datos de pneumaticos.
      </p>
    </div>
  </section>
</template>
