<script setup lang="ts">
/**
 * Evolucion de posiciones por vuelta.
 *
 * Cada linea es un piloto: la posicion que tenia **al final** de cada vuelta.
 * Los datos salen de OpenF1 (`/position`, que publica cada cambio de posicion
 * con su instante) cruzados con las vueltas (`/laps`, que traen el numero de
 * vuelta): el cambio se publica en el mismo instante en que arranca la vuelta
 * siguiente, asi que la posicion al final de la vuelta N es el ultimo cambio
 * publicado hasta el comienzo de la N+1.
 *
 * Con 22 pilotos el grafico es un marañon, asi que todas las lineas van
 * apagadas y se resalta la del piloto que se esta mirando en el panel lateral.
 */
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import SearchSelect from '@/components/SearchSelect.vue'
import { useSessionOptions } from '@/composables/useSessionOptions'
import { useAnalysisStore } from '@/stores/analysis'
import { useRaceStore } from '@/stores/race'
import type { PositionHistoryRow } from '@/types'

echarts.use([LineChart, GridComponent, TooltipComponent, CanvasRenderer])

const analysis = useAnalysisStore()
const store = useRaceStore()
const { opciones, sesionDelPanel } = useSessionOptions()

const container = ref<HTMLDivElement | null>(null)
const chart = shallowRef<echarts.ECharts | null>(null)
let observer: ResizeObserver | null = null

const rows = computed<PositionHistoryRow[]>(() => analysis.positions?.rows ?? [])

/** Cuantos pilotos cambiaron de posicion en cada vuelta. */
const cambiosPorVuelta = computed(() => {
  const porVuelta = new Map<number, number>()
  for (const row of rows.value) {
    let anterior: number | null = null
    for (const punto of row.points) {
      if (punto.lap == null) continue
      if (anterior !== null && punto.position !== null && punto.position !== anterior) {
        porVuelta.set(punto.lap, (porVuelta.get(punto.lap) ?? 0) + 1)
      }
      if (punto.position !== null) anterior = punto.position
    }
  }
  return porVuelta
})

function colorDe(row: PositionHistoryRow): string {
  const colour = row.team_colour
  if (!colour) return '#94a3b8'
  return colour.startsWith('#') ? colour : `#${colour}`
}

function buildOption(): echarts.EChartsCoreOption {
  const seleccion = store.selectedDriver
  const datos = rows.value

  const maximo = datos.reduce((mayor, row) => {
    const ultimo = row.points[row.points.length - 1]
    return Math.max(mayor, ultimo?.position ?? 0)
  }, 1)

  const series = datos.map((row) => {
    const esSeleccion = row.driver_number === seleccion
    const colour = colorDe(row)
    const nombre = row.code ?? `#${row.driver_number}`
    return {
      name: nombre,
      type: 'line',
      step: 'end',
      showSymbol: false,
      symbolSize: 5,
      z: esSeleccion ? 10 : 1,
      lineStyle: {
        width: esSeleccion ? 2.4 : 1,
        color: esSeleccion ? colour : 'rgba(100,116,139,0.25)',
        opacity: esSeleccion ? 1 : 0.9,
      },
      itemStyle: { color: esSeleccion ? colour : 'rgba(100,116,139,0.25)' },
      emphasis: {
        focus: 'series',
        lineStyle: { width: 2.4, color: colour },
      },
      // La etiqueta va solo al final de la linea: en todos los puntos seria
      // un bosque de etiquetas.
      endLabel: esSeleccion
        ? {
            show: true,
            formatter: nombre,
            color: colour,
            fontSize: 11,
            fontWeight: 600,
          }
        : { show: false },
      data: row.points.map((punto) => [punto.lap, punto.position]),
    }
  })

  const filaSeleccion = datos.find((row) => row.driver_number === seleccion) ?? null

  return {
    grid: { left: 42, right: 58, top: 18, bottom: 28 },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'line' },
      backgroundColor: 'rgba(10,15,28,0.96)',
      borderColor: '#1d2a47',
      textStyle: { color: '#cbd5e1', fontSize: 11 },
      formatter: (params: any) => {
        const items = Array.isArray(params) ? params : [params]
        if (!items.length) return ''
        const lap = items[0]?.axisValue
        const lineas: string[] = [`<strong>Vuelta ${lap}</strong>`]
        if (filaSeleccion) {
          const punto = filaSeleccion.points.find((p) => p.lap === lap)
          lineas.push(
            `${filaSeleccion.code ?? `#${filaSeleccion.driver_number}`}: P${punto?.position ?? '—'}`,
          )
        }
        const cambios = cambiosPorVuelta.value.get(Number(lap))
        if (cambios) {
          lineas.push(`${cambios} piloto${cambios === 1 ? '' : 's'} cambiaron de posicion`)
        }
        return lineas.join('<br/>')
      },
    },
    xAxis: {
      type: 'value',
      min: 1,
      name: 'vuelta',
      nameLocation: 'end',
      nameGap: 4,
      nameTextStyle: { color: '#475569', fontSize: 9 },
      axisLabel: { color: '#64748b', fontSize: 10 },
      splitLine: { lineStyle: { color: 'rgba(29,42,71,0.5)' } },
    },
    yAxis: {
      type: 'value',
      inverse: true,
      min: 1,
      max: maximo || 1,
      name: 'pos',
      nameTextStyle: { color: '#475569', fontSize: 9 },
      axisLabel: { color: '#64748b', fontSize: 10 },
      splitLine: { lineStyle: { color: 'rgba(29,42,71,0.5)' } },
    },
    series,
  }
}

function render() {
  if (!container.value) return
  if (!chart.value) {
    chart.value = echarts.init(container.value, undefined, { renderer: 'canvas' })
  }
  chart.value.setOption(buildOption(), true)
}

/** Cambia la sesion: la comparten los tres paneles post-sesion. */
async function cambiarSesion(valor: string | null) {
  if (valor === analysis.sessionKey) return
  await analysis.setSession(valor)
}

onMounted(() => {
  render()
  observer = new ResizeObserver(() => chart.value?.resize())
  if (container.value) observer.observe(container.value)
  if (!analysis.sessionKey && opciones.value.length) {
    void analysis.setSession(sesionDelPanel.value ?? opciones.value[0].value)
  }
})

onBeforeUnmount(() => {
  observer?.disconnect()
  chart.value?.dispose()
  chart.value = null
})

watch(
  () => rows.value.map((row) => `${row.driver_number}:${row.points.length}`).join(','),
  () => render(),
)

watch(
  () => store.selectedDriver,
  () => render(),
)
</script>

<template>
  <section class="panel flex min-h-0 flex-col overflow-hidden">
    <header class="panel-title justify-between">
      <span>Evolucion de posiciones</span>
      <span class="chip">{{ analysis.positions?.source ?? '—' }}</span>
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

    <div class="min-h-0 flex-1 overflow-auto px-2 pb-2">
      <div ref="container" class="h-[340px] w-full" />

      <p
        v-if="analysis.positionsLoading"
        class="px-4 py-3 text-center text-xs text-slate-500"
      >
        Cargando la evolucion de posiciones...
      </p>
      <p
        v-else-if="analysis.positionsError"
        class="px-4 py-3 text-center text-xs text-slate-500"
      >
        {{ analysis.positionsError }}
      </p>
      <p
        v-else-if="!rows.length"
        class="px-4 py-3 text-center text-xs text-slate-500"
      >
        No hay datos de posiciones para esta sesion.
      </p>

      <!-- Movimientos: quien gano y perdio posiciones -->
      <div v-if="rows.length" class="px-2 pt-1">
        <div class="flex flex-wrap gap-x-3 gap-y-1">
          <span
            v-for="row in rows.slice(0, 10)"
            :key="row.driver_number"
            class="num flex items-center gap-1 text-[10px]"
            :class="row.driver_number === store.selectedDriver ? 'text-slate-200' : 'text-slate-500'"
          >
            <span
              class="h-2 w-2 rounded-full"
              :style="{ backgroundColor: colorDe(row) }"
            />
            {{ row.code ?? `#${row.driver_number}` }}
            <span class="text-emerald-400/80">+{{ row.positions_gained }}</span>
            <span class="text-rose-400/70">-{{ row.positions_lost }}</span>
          </span>
        </div>
        <p class="px-2 pt-1.5 text-[10px] leading-relaxed text-slate-600">
          Posicion al final de cada vuelta. Se resalta el piloto del panel lateral.
        </p>
      </div>
    </div>
  </section>
</template>
