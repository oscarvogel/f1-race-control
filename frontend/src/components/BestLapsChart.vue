<script setup lang="ts">
/**
 * Grafico comparativo de mejores vueltas por piloto.
 *
 * Usa Apache ECharts. Los datos salen de la clasificacion normalizada, asi
 * que son los mismos que muestra la tabla (misma fuente, misma antiguedad).
 */
import { onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  MarkLineComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useRaceStore } from '@/stores/race'

echarts.use([BarChart, GridComponent, TooltipComponent, MarkLineComponent, CanvasRenderer])

const store = useRaceStore()
const container = ref<HTMLDivElement | null>(null)
const chart = shallowRef<echarts.ECharts | null>(null)
let observer: ResizeObserver | null = null

function buildOption(): echarts.EChartsCoreOption {
  const rows = store.timing
    .filter((entry) => entry.best_lap_time != null)
    .slice(0, 15)
    .sort((a, b) => (a.best_lap_time ?? 0) - (b.best_lap_time ?? 0))

  const names = rows.map(
    (entry) => `${entry.driver?.code ?? entry.driver_number}`,
  )
  const values = rows.map((entry) => Number((entry.best_lap_time ?? 0).toFixed(3)))
  const colours = rows.map((entry) => {
    const colour = entry.driver?.team_colour
    return colour ? (colour.startsWith('#') ? colour : `#${colour}`) : '#2b3b60'
  })

  const fastest = values.length ? Math.min(...values) : 0

  return {
    grid: { left: 44, right: 16, top: 16, bottom: 26 },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      backgroundColor: 'rgba(10,15,28,0.96)',
      borderColor: '#1d2a47',
      textStyle: { color: '#cbd5e1', fontSize: 11 },
      formatter: (params: any) => {
        const item = Array.isArray(params) ? params[0] : params
        const index = item?.dataIndex ?? 0
        const entry = rows[index]
        if (!entry) return ''
        return [
          `<strong>${entry.driver?.full_name ?? entry.driver_number}</strong>`,
          `Mejor vuelta: ${entry.best_lap_time_display ?? '—'}`,
          `Vuelta ${entry.best_lap_number ?? '—'} · ${entry.number_of_laps ?? '—'} vueltas`,
          `Neumatico: ${entry.tyre_compound ?? '—'}`,
        ].join('<br/>')
      },
    },
    xAxis: {
      type: 'value',
      scale: true,
      min: (value: any) => (fastest ? Math.floor(fastest - 1.5) : 0),
      axisLabel: {
        color: '#64748b',
        fontSize: 10,
        formatter: (value: number) => value.toFixed(1),
      },
      splitLine: { lineStyle: { color: 'rgba(29,42,71,0.5)' } },
    },
    yAxis: {
      type: 'category',
      data: names,
      inverse: true,
      axisLabel: { color: '#94a3b8', fontSize: 11 },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    series: [
      {
        type: 'bar',
        data: values.map((value, index) => ({
          value,
          itemStyle: { color: colours[index], borderRadius: [0, 3, 3, 0] },
        })),
        barMaxWidth: 16,
        label: {
          show: true,
          position: 'right',
          color: '#94a3b8',
          fontSize: 10,
          formatter: (params: any) => {
            const value = Number(params?.value ?? 0)
            const minutes = Math.floor(value / 60)
            const rest = value - minutes * 60
            return `${minutes}:${rest.toFixed(3).padStart(6, '0')}`
          },
        },
        markLine: fastest
          ? {
              silent: true,
              symbol: 'none',
              lineStyle: { color: '#b14aff', type: 'dashed', width: 1 },
              data: [{ xAxis: fastest }],
            }
          : undefined,
      },
    ],
  }
}

function render() {
  if (!container.value) return
  if (!chart.value) {
    chart.value = echarts.init(container.value, undefined, { renderer: 'canvas' })
  }
  chart.value.setOption(buildOption(), true)
}

onMounted(() => {
  render()
  observer = new ResizeObserver(() => chart.value?.resize())
  if (container.value) observer.observe(container.value)
})

onBeforeUnmount(() => {
  observer?.disconnect()
  chart.value?.dispose()
  chart.value = null
})

watch(
  () => store.timing.map((entry) => `${entry.driver_number}:${entry.best_lap_time}`).join(','),
  () => render(),
)
</script>

<template>
  <section class="panel overflow-hidden">
    <header class="panel-title justify-between">
      <span>Mejores vueltas</span>
      <span class="chip">ECharts</span>
    </header>
    <div ref="container" class="h-[320px] w-full" />
    <p v-if="!store.timing.length" class="px-4 pb-3 text-center text-xs text-slate-500">
      Sin datos de vueltas para graficar.
    </p>
  </section>
</template>
