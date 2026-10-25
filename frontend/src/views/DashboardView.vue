<script setup lang="ts">
import { onMounted } from 'vue'
import { AlertCircle, RefreshCw } from '@lucide/vue'
import AppHeader from '@/components/AppHeader.vue'
import ClassificationTable from '@/components/ClassificationTable.vue'
import DriverPanel from '@/components/DriverPanel.vue'
import FollowedDriversBar from '@/components/FollowedDriversBar.vue'
import RaceControlPanel from '@/components/RaceControlPanel.vue'
import TyresPanel from '@/components/TyresPanel.vue'
import WeatherPanel from '@/components/WeatherPanel.vue'
import BestLapsChart from '@/components/BestLapsChart.vue'
import CircuitMap from '@/components/CircuitMap.vue'
import DiagnosticsPanel from '@/components/DiagnosticsPanel.vue'
import AnalysisPanel from '@/components/AnalysisPanel.vue'
import ChampionshipPanel from '@/components/ChampionshipPanel.vue'
import PositionHistoryChart from '@/components/PositionHistoryChart.vue'
import StrategyPanel from '@/components/StrategyPanel.vue'
import { useRaceStore } from '@/stores/race'
import { usePolling } from '@/composables/usePolling'

const store = useRaceStore()

// El backend actualiza cada 3 s: consultar cada 2 s da buena respuesta sin
// machacar la API.
const { start, stop } = usePolling(() => store.refresh(), 2000)

onMounted(() => {
  void store.refresh()
  start()
})
</script>

<template>
  <div class="flex min-h-screen flex-col">
    <AppHeader />

    <div v-if="store.error" class="border-b border-warn/30 bg-warn/10 px-4 py-2.5">
      <div class="mx-auto flex max-w-[1800px] items-center gap-2 text-[13px] text-warn">
        <AlertCircle class="h-4 w-4 shrink-0" />
        <span class="flex-1">{{ store.error }}</span>
        <button
          type="button"
          class="flex items-center gap-1.5 rounded-md border border-warn/40 px-2.5 py-1 text-[11px] uppercase tracking-wider hover:bg-warn/10"
          @click="store.refresh()"
        >
          <RefreshCw class="h-3 w-3" /> Reintentar
        </button>
      </div>
    </div>

    <div
      v-if="store.warnings.length"
      class="border-b border-amber-500/25 bg-amber-500/5 px-4 py-2"
    >
      <div class="mx-auto flex max-w-[1800px] items-start gap-2 text-[12px] text-amber-300/90">
        <AlertCircle class="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <div class="flex-1">
          <span class="font-semibold uppercase tracking-wider">Datos incompletos:</span>
          <span class="ml-1">{{ store.warnings.join(' · ') }}</span>
        </div>
      </div>
    </div>

    <!--
        El dock de pilotos seguidos va fijo abajo: cuando esta visible tapa la
        parte baja de la pagina, asi que el contenido principal deja un hueco
        abajo para que el ultimo panel no quede debajo.
    -->
    <main
      class="mx-auto w-full max-w-[1800px] flex-1 px-4 py-4 lg:px-6"
      :class="store.followedDrivers.length ? 'pb-[220px]' : ''"
    >
      <!--
        El circuito va en la columna derecha, pegado a la clasificacion en
        vivo: antes estaba al final de la pagina, abajo y perdido, y no se
        veía mientras se mira la clasificacion.
      -->
      <div class="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <!-- Clasificacion: ocupa 2 columnas y las 2 filas -->
        <div class="xl:col-span-2 xl:row-span-2">
          <ClassificationTable class="h-full" />
        </div>

        <!-- Circuito: junto a la clasificacion -->
        <CircuitMap />

        <!-- Piloto seleccionado -->
        <DriverPanel />
      </div>

      <div class="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <div class="xl:col-span-2">
          <RaceControlPanel class="h-[420px]" />
        </div>
        <div class="flex flex-col gap-4">
          <WeatherPanel />
        </div>
      </div>

      <div class="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <div class="xl:col-span-2">
          <TyresPanel class="h-[420px]" />
        </div>
        <BestLapsChart />
      </div>

      <!--
        Analisis post-sesion: comparacion por sectores de la mejor vuelta y
        clasificacion del campeonato. Los dos leen fuentes historicas (no
        cambian cada 2 s como el snapshot en vivo).
      -->
      <div class="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <div class="xl:col-span-2">
          <AnalysisPanel class="h-[520px]" />
        </div>
        <ChampionshipPanel class="h-[520px]" />
      </div>

      <!--
        Evolucion de posiciones y estrategia de neumaticos. Los dos leen la
        misma sesion que el panel de analisis (el store la comparte), asi que
        comparar la classificacion con lo que hizo cada piloto en la pista es
        question de mirar el mismo selects.
      -->
      <div class="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <div class="xl:col-span-2">
          <PositionHistoryChart class="h-[460px]" />
        </div>
        <StrategyPanel class="h-[460px]" />
      </div>
    </main>

    <footer class="border-t border-race-800/60 px-4 py-3 text-center text-[11px] text-slate-600">
      Race Center · aplicacion personal · datos de cronometraje:
      <span class="text-slate-500">{{ store.liveProvider ?? 'sin proveedor' }}</span>
    </footer>

    <FollowedDriversBar />
    <DiagnosticsPanel />
  </div>
</template>
