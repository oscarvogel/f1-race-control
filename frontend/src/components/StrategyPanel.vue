<script setup lang="ts">
/**
 * Estrategia de neumaticos: los tramos de vueltas de cada piloto.
 *
 * Un tramo (stint) es un grupo de vueltas con el mismo compuesto. De cada uno
 * se dice el compuesto, de que vuelta a que vuelta, cuantas vueltas, la edad
 * del neumatico al empezar y cual fue su mejor vuelta.
 *
 * En una carrera, cada cambio de tramo es una parada en boxes. En la
 * clasificacion, los tramos son los cambios de neumatico entre segmentos (Q1,
 * Q2, Q3), no paradas: por eso el panel no los llama "paradas".
 */
import { computed, onMounted } from 'vue'
import SearchSelect from '@/components/SearchSelect.vue'
import { useSessionOptions } from '@/composables/useSessionOptions'
import { useAnalysisStore } from '@/stores/analysis'
import { useRaceStore } from '@/stores/race'
import type { StrategyRow, StrategyStint } from '@/types'

const analysis = useAnalysisStore()
const store = useRaceStore()
const { opciones, sesionDelPanel } = useSessionOptions()

const COMPOUND: Record<string, { label: string; short: string; color: string }> = {
  SOFT: { label: 'SOFT', short: 'S', color: '#ff5a6e' },
  MEDIUM: { label: 'MEDIUM', short: 'M', color: '#f5a623' },
  HARD: { label: 'HARD', short: 'H', color: '#e2e8f0' },
  INTERMEDIATE: { label: 'INTER', short: 'I', color: '#2ecc71' },
  WET: { label: 'WET', short: 'W', color: '#60a5fa' },
}

function estilo(compound: string | null) {
  if (!compound) return { label: '—', short: '·', color: '#64748b' }
  return COMPOUND[compound.toUpperCase()] ?? { label: compound, short: '?', color: '#94a3b8' }
}

function colorDe(row: StrategyRow): string {
  const colour = row.team_colour
  if (!colour) return '#2b3b60'
  return colour.startsWith('#') ? colour : `#${colour}`
}

const rows = computed<StrategyRow[]>(() => analysis.strategy?.rows ?? [])

/** Los compuestos que aparecen en la sesion, para la leyenda. */
const compuestosUsados = computed(() => {
  const vistos = new Set<string>()
  for (const row of rows.value) {
    for (const tramo of row.stints) {
      if (tramo.compound) vistos.add(tramo.compound.toUpperCase())
    }
  }
  return [...vistos].map((compuesto) => estilo(compuesto))
})

/** Cuantas vueltas ocupa cada tramo en la barra (proporcional a su largo). */
function peso(tramo: StrategyStint, total: number): number {
  if (!total) return 1
  return Math.max(1, (tramo.laps / total) * 100)
}

function seleccionar(numero: string) {
  store.selectDriver(numero)
}

/** Cambia la sesion: la comparten los tres paneles post-sesion. */
async function cambiarSesion(valor: string | null) {
  if (valor === analysis.sessionKey) return
  await analysis.setSession(valor)
}

onMounted(() => {
  if (!analysis.sessionKey && opciones.value.length) {
    void analysis.setSession(sesionDelPanel.value ?? opciones.value[0].value)
  }
})
</script>

<template>
  <section class="panel flex min-h-0 flex-col overflow-hidden">
    <header class="panel-title justify-between">
      <span>Estrategia de neumaticos</span>
      <span class="chip">{{ analysis.strategy?.source ?? '—' }}</span>
    </header>

    <!-- Sesion: la misma que miran los otros paneles post-sesion -->
    <div class="border-b border-race-800/60 px-4 py-2">
      <SearchSelect
        :options="opciones"
        :model-value="analysis.sessionKey"
        placeholder="Sesion"
        @update:model-value="cambiarSesion"
      />
    </div>

    <div class="min-h-0 flex-1 overflow-auto">
      <!-- Leyenda de compuestos -->
      <div
        v-if="compuestosUsados.length"
        class="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-race-800/60 px-4 py-2"
      >
        <span
          v-for="compuesto in compuestosUsados"
          :key="compuesto.label"
          class="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-slate-400"
        >
          <span
            class="h-2.5 w-2.5 rounded-sm"
            :style="{ backgroundColor: compuesto.color }"
          />
          {{ compuesto.label }}
        </span>
      </div>

      <ul class="divide-y divide-race-800/60">
        <li
          v-for="row in rows"
          :key="row.driver_number"
          class="flex cursor-pointer items-center gap-2.5 px-4 py-1.5 transition-colors hover:bg-race-800/40"
          :class="row.driver_number === store.selectedDriver ? 'bg-race-800/50' : ''"
          @click="seleccionar(row.driver_number)"
        >
          <span class="h-6 w-1 shrink-0 rounded-full" :style="{ backgroundColor: colorDe(row) }" />
          <span class="num w-7 shrink-0 text-[11px] text-slate-500">#{{ row.driver_number }}</span>
          <span class="w-24 shrink-0 truncate text-[12px] text-slate-300">
            {{ row.code ?? row.full_name ?? '—' }}
          </span>

          <!-- Tramos: cada bloque es un stint, con su compuesto -->
          <span class="flex min-w-0 flex-1 items-center gap-px">
            <span
              v-for="(tramo, index) in row.stints"
              :key="index"
              class="flex h-5 items-center justify-center rounded-sm text-[9px] font-bold text-race-950/90"
              :style="{
                backgroundColor: estilo(tramo.compound).color,
                flexGrow: peso(tramo, row.total_laps),
                flexBasis: 0,
                minWidth: '14px',
                opacity: tramo.is_out_lap ? 0.55 : 1,
              }"
              :title="`${estilo(tramo.compound).label} · vueltas ${tramo.lap_start}-${tramo.lap_end} · ${tramo.laps} v · edad ${tramo.tyre_age_at_start ?? '—'} · mejor ${tramo.best_lap_time_display ?? '—'}`"
            >
              {{ estilo(tramo.compound).short }}
            </span>
            <span v-if="!row.stints.length" class="text-[11px] text-slate-600">sin tramos</span>
          </span>

          <span class="num w-16 shrink-0 text-right text-[10px] text-slate-500">
            {{ row.stint_count }} tramos
          </span>
          <span class="num w-16 shrink-0 text-right text-[10px] text-slate-500">
            {{ row.total_laps }} v
          </span>
          <span class="num w-16 shrink-0 text-right text-[11px] text-slate-300">
            {{ row.best_lap_time_display ?? '—' }}
          </span>
        </li>
      </ul>

      <p
        v-if="analysis.strategyLoading"
        class="px-4 py-6 text-center text-xs text-slate-500"
      >
        Cargando la estrategia...
      </p>
      <p
        v-else-if="analysis.strategyError"
        class="px-4 py-6 text-center text-xs text-slate-500"
      >
        {{ analysis.strategyError }}
      </p>
      <p
        v-else-if="!rows.length"
        class="px-4 py-6 text-center text-xs text-slate-500"
      >
        No hay datos de neumaticos para esta sesion.
      </p>

      <p
        v-if="rows.length"
        class="border-t border-race-800/60 px-4 py-2 text-[10px] leading-relaxed text-slate-600"
      >
        Cada bloque es un tramo con el mismo compuesto (la letra). Un bloque mas
        claro es la vuelta de salida de boxes. En la clasificacion los tramos
        son los cambios de neumatico entre Q1, Q2 y Q3, no paradas.
      </p>
    </div>
  </section>
</template>
