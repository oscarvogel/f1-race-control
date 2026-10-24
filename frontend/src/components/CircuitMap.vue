<script setup lang="ts">
/**
 * Vista del circuito con la posicion de cada piloto.
 *
 * El trazado proviene de posiciones GPS reales (ver
 * `manage.py build_track_outline`). Los puntos de los autos vienen del canal
 * CarData del feed de cronometraje, en el mismo sistema de coordenadas, y se
 * proyectan sobre ese trazado con los mismos limites.
 *
 * Si el proveedor no entrega posiciones, se lo dice: no se inventan autos.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { Flag, LocateFixed } from '@lucide/vue'
import { useRaceStore } from '@/stores/race'
import { api } from '@/services/api'
import type { TrackOutline } from '@/types'

const store = useRaceStore()
const outline = ref<TrackOutline | null>(null)
const outlineError = ref<string | null>(null)

/** Clave de circuito: el feed no la expone, se usa Austin por defecto. */
const CIRCUIT_KEY = 9

onMounted(async () => {
  try {
    const response = await api.trackOutline(CIRCUIT_KEY)
    outline.value = response as unknown as TrackOutline
  } catch (error) {
    outlineError.value =
      error instanceof Error ? error.message : 'No se pudo cargar el trazado del circuito.'
  }
})

const positions = computed(() => store.positions ?? [])

/** Proyecta una coordenada del feed al lienzo del trazado. */
function project(x: number, y: number): { px: number; py: number } | null {
  const o = outline.value
  if (!o) return null
  const { min_x, max_x, min_y, max_y } = o.bounds
  const width = max_x - min_x || 1
  const height = max_y - min_y || 1
  const scale = o.size / Math.max(width, height)
  const offsetX = (o.size - width * scale) / 2
  const offsetY = (o.size - height * scale) / 2
  return {
    px: (x - min_x) * scale + offsetX,
    py: o.size - ((y - min_y) * scale + offsetY),
  }
}

interface Dot {
  driver_number: string
  px: number
  py: number
  speed: number | null
  colour: string
  code: string
  selected: boolean
}

const dots = computed<Dot[]>(() =>
  positions.value
    .map((position) => {
      const point = project(position.x, position.y)
      if (!point) return null
      const entry = store.timing.find((item) => item.driver_number === position.driver_number)
      const colour = entry?.driver?.team_colour
      return {
        driver_number: position.driver_number,
        px: point.px,
        py: point.py,
        speed: position.speed,
        colour: colour ? (colour.startsWith('#') ? colour : `#${colour}`) : '#2b3b60',
        code: entry?.driver?.code ?? position.driver_number,
        selected: store.selectedDriver === position.driver_number,
      } as Dot
    })
    .filter((dot): dot is Dot => dot !== null),
)

const polyline = computed(() =>
  (outline.value?.points ?? []).map((point) => point.join(',')).join(' '),
)

const trackStatusLabel = computed(() => {
  const status = store.trackStatus?.status
  if (!status) return null
  return status
})

const trackStatusTone = computed(() => {
  const status = (store.trackStatus?.status ?? '').toUpperCase()
  if (status.includes('RED')) return 'text-bad'
  if (status.includes('YELLOW') || status.includes('SC')) return 'text-warn'
  if (status.includes('GREEN')) return 'text-ok'
  return 'text-slate-400'
})

/**
 * Límites reales del trazado dentro del lienzo.
 *
 * El viewBox por defecto es 0 0 1000 1000, pero el circuito solo ocupa una
 * banda: recortarlo al trazado real hace que el mapa llene el panel en vez
 * de flotar en el centro con los lados vacios.
 */
const trackBounds = computed(() => {
  const points = outline.value?.points ?? []
  if (!points.length) return null
  let minX = Infinity
  let maxX = -Infinity
  let minY = Infinity
  let maxY = -Infinity
  for (const point of points) {
    const [px, py] = point
    if (px < minX) minX = px
    if (px > maxX) maxX = px
    if (py < minY) minY = py
    if (py > maxY) maxY = py
  }
  const margin = 30
  return {
    x: minX - margin,
    y: minY - margin,
    width: maxX - minX + margin * 2,
    height: maxY - minY + margin * 2,
  }
})

/** Seguimiento: centra la vista en el piloto seleccionado. */
const followSelected = ref(true)
const viewBox = computed(() => {
  const base = trackBounds.value
  if (!base) return '0 0 1000 1000'
  if (!followSelected.value) return `${base.x} ${base.y} ${base.width} ${base.height}`

  const dot = dots.value.find((item) => item.selected)
  if (!dot) return `${base.x} ${base.y} ${base.width} ${base.height}`

  // Ventana de zoom centrada en el piloto, sin salirse del trazado.
  const size = Math.min(base.width, base.height) * 0.6
  const half = size / 2
  const x = Math.min(Math.max(dot.px, base.x + half), base.x + base.width - half)
  const y = Math.min(Math.max(dot.py, base.y + half), base.y + base.height - half)
  return `${x - half} ${y - half} ${size} ${size}`
})

watch(
  () => store.selectedDriver,
  () => {
    /* el seguimiento se recalcula solo por la dependencia de viewBox */
  },
)
</script>

<template>
  <section class="panel flex flex-col overflow-hidden">
    <header class="panel-title justify-between">
      <span class="flex items-center gap-1.5">
        <LocateFixed class="h-3.5 w-3.5" /> Circuito
      </span>
      <span class="flex items-center gap-2">
        <span v-if="trackStatusLabel" class="chip" :class="trackStatusTone">
          <Flag class="h-3 w-3" /> {{ trackStatusLabel }}
        </span>
        <span class="chip">{{ outline?.circuit_name ?? 'Austin' }}</span>
      </span>
    </header>

    <div class="relative flex items-center justify-center bg-race-950/60">
      <svg
        v-if="outline"
        :viewBox="viewBox"
        class="block h-[300px] w-full transition-[view-box] duration-500"
        preserveAspectRatio="xMidYMid meet"
      >
        <defs>
          <filter id="rc-glow" x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="4" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        <!-- Trazado -->
        <polyline
          :points="polyline"
          fill="none"
          stroke="#1d2a47"
          stroke-width="18"
          stroke-linejoin="round"
          stroke-linecap="round"
        />
        <polyline
          :points="polyline"
          fill="none"
          stroke="#2b3b60"
          stroke-width="11"
          stroke-linejoin="round"
          stroke-linecap="round"
        />

        <!-- Autos -->
        <g v-for="dot in dots" :key="dot.driver_number">
          <circle
            v-if="dot.selected"
            :cx="dot.px"
            :cy="dot.py"
            r="15"
            fill="none"
            :stroke="dot.colour"
            stroke-width="2"
            opacity="0.8"
            filter="url(#rc-glow)"
          />
          <circle
            :cx="dot.px"
            :cy="dot.py"
            :r="dot.selected ? 8 : 6"
            :fill="dot.colour"
            stroke="#05080f"
            stroke-width="1.5"
          />
          <text
            :x="dot.px"
            :y="dot.py + 3"
            text-anchor="middle"
            font-size="7"
            font-weight="700"
            fill="#05080f"
            pointer-events="none"
          >
            {{ dot.code }}
          </text>
        </g>
      </svg>

      <div
        v-else
        class="flex h-[300px] items-center justify-center px-6 text-center text-xs text-slate-500"
      >
        {{ outlineError ?? 'Cargando trazado del circuito...' }}
      </div>

      <!-- Leyenda -->
      <div
        v-if="dots.length"
        class="absolute bottom-2 left-3 rounded-md border border-race-750/70 bg-race-900/85 px-2.5 py-1.5 backdrop-blur"
      >
        <p class="text-[10px] uppercase tracking-[0.12em] text-slate-500">
          {{ dots.length }} autos en pista
        </p>
        <p class="text-[10px] text-slate-600">
          Trazado derivado de posiciones GPS reales
        </p>
      </div>

      <button
        type="button"
        class="absolute bottom-2 right-3 rounded-md border border-race-750/70 bg-race-900/85 px-2.5 py-1 text-[10px] uppercase tracking-[0.1em] text-slate-400 backdrop-blur transition hover:border-accent/60 hover:text-white"
        @click="followSelected = !followSelected"
      >
        {{ followSelected ? 'Todo el circuito' : 'Seguir piloto' }}
      </button>
    </div>

    <p
      v-if="!dots.length && outline"
      class="px-4 py-3 text-center text-[11px] text-slate-500"
    >
      Sin posiciones en vivo. El proveedor no entrega coordenadas mientras la
      sesion no esta activa.
    </p>
  </section>
</template>
