<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { AlertCircle, Trophy } from '@lucide/vue'
import { useAnalysisStore } from '@/stores/analysis'

const analysis = useAnalysisStore()

/** 'drivers' = pilotos, 'teams' = constructores. */
const vista = ref<'drivers' | 'teams'>('drivers')

const campeonato = computed(() => analysis.championship)

const drivers = computed(() => campeonato.value?.drivers ?? [])
const teams = computed(() => campeonato.value?.teams ?? [])

/**
 * Diferencia con el lider.
 *
 * Viene en negativo (el lider es 0 y los demas, menos). Se muestra como
 * rezago, que es como se lee en una tabla de campeonato.
 */
function rezago(valor: number | null): string {
  if (valor == null) return '—'
  if (valor === 0) return '—'
  return `−${Math.abs(valor)}`
}

function posicion(valor: number): string {
  if (valor === 1) return '1'
  return String(valor)
}

onMounted(() => {
  if (!analysis.championship) void analysis.loadChampionship()
})
</script>

<template>
  <section class="panel flex min-h-0 flex-col overflow-hidden">
    <header class="panel-title justify-between">
      <span class="flex items-center gap-2">
        <Trophy class="h-3.5 w-3.5" :stroke-width="2" />
        Campeonato
      </span>
      <span class="chip">{{ campeonato?.source ?? '—' }}</span>
    </header>

    <!-- En que ronda esta la tabla -->
    <p class="border-b border-race-750/60 px-4 py-2 text-[11px] leading-snug text-slate-500">
      {{ campeonato?.note ?? 'Sin datos de campeonato.' }}
    </p>

    <!-- Pilotos / Constructores -->
    <div class="flex gap-1 border-b border-race-750/60 px-3 py-2">
      <button
        type="button"
        class="rounded px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] transition"
        :class="
          vista === 'drivers'
            ? 'bg-race-750/70 text-white'
            : 'text-slate-500 hover:text-slate-300'
        "
        @click="vista = 'drivers'"
      >
        Pilotos
      </button>
      <button
        type="button"
        class="rounded px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] transition"
        :class="
          vista === 'teams'
            ? 'bg-race-750/70 text-white'
            : 'text-slate-500 hover:text-slate-300'
        "
        @click="vista = 'teams'"
      >
        Constructores
      </button>
      <span v-if="campeonato" class="ml-auto self-center text-[10px] text-slate-600">
        Temporada {{ campeonato.season }}
      </span>
    </div>

    <div class="min-h-0 flex-1 overflow-auto">
      <!-- Pilotos -->
      <table v-if="vista === 'drivers'" class="w-full border-collapse">
        <thead class="sticky top-0 bg-race-900/95 backdrop-blur">
          <tr class="border-b border-race-750/60">
            <th class="th w-8">P</th>
            <th class="th">Piloto</th>
            <th class="th text-right">Pts</th>
            <th class="th text-right">Vict</th>
            <th class="th text-right">Pod</th>
            <th class="th text-right">Rezago</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="piloto in drivers"
            :key="piloto.driver_number || piloto.code || piloto.position"
            class="border-b border-race-800/50"
          >
            <td class="td num" :class="piloto.position <= 3 ? 'text-accent' : 'text-slate-500'">
              {{ posicion(piloto.position) }}
            </td>
            <td class="td">
              <div class="flex items-baseline gap-1.5">
                <span class="num text-[10px] text-slate-600">#{{ piloto.driver_number }}</span>
                <span class="truncate text-[12px] text-slate-200">
                  {{ piloto.code ?? piloto.full_name ?? '—' }}
                </span>
              </div>
              <div class="truncate text-[10px] text-slate-500">{{ piloto.team ?? '' }}</div>
            </td>
            <td class="td num text-right text-[13px] font-semibold text-white">
              {{ piloto.points }}
            </td>
            <td class="td num text-right text-[12px] text-slate-300">{{ piloto.wins }}</td>
            <td class="td num text-right text-[12px] text-slate-400">
              {{ piloto.podiums ?? '—' }}
            </td>
            <td class="td num text-right text-[12px] text-slate-500">
              {{ rezago(piloto.gap_to_leader) }}
            </td>
          </tr>
        </tbody>
      </table>

      <!-- Constructores -->
      <table v-else class="w-full border-collapse">
        <thead class="sticky top-0 bg-race-900/95 backdrop-blur">
          <tr class="border-b border-race-750/60">
            <th class="th w-8">P</th>
            <th class="th">Constructor</th>
            <th class="th text-right">Pts</th>
            <th class="th text-right">Vict</th>
            <th class="th text-right">Rezago</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="equipo in teams"
            :key="equipo.team || equipo.position"
            class="border-b border-race-800/50"
          >
            <td class="td num" :class="equipo.position <= 3 ? 'text-accent' : 'text-slate-500'">
              {{ posicion(equipo.position) }}
            </td>
            <td class="td truncate text-[12px] text-slate-200">{{ equipo.team ?? '—' }}</td>
            <td class="td num text-right text-[13px] font-semibold text-white">
              {{ equipo.points }}
            </td>
            <td class="td num text-right text-[12px] text-slate-300">{{ equipo.wins }}</td>
            <td class="td num text-right text-[12px] text-slate-500">
              {{ rezago(equipo.gap_to_leader) }}
            </td>
          </tr>
        </tbody>
      </table>

      <p
        v-if="analysis.championshipError"
        class="flex items-start gap-2 px-4 py-6 text-[12px] text-bad"
      >
        <AlertCircle class="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span>{{ analysis.championshipError }}</span>
      </p>
      <p
        v-else-if="!analysis.championship && !analysis.championshipLoading"
        class="px-4 py-10 text-center text-[12px] text-slate-500"
      >
        Sin datos de campeonato.
      </p>
      <p v-if="analysis.championshipLoading" class="px-4 py-10 text-center text-[12px] text-slate-500">
        Leyendo el campeonato...
      </p>
    </div>
  </section>
</template>
