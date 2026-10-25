<script setup lang="ts">
/**
 * Dock inferior con los pilotos que el usuario sigue.
 *
 * Va fijo abajo de la pantalla, con los datos en vivo de cada piloto
 * (posicion, mejor vuelta, ultima vuelta, pneumatico, vueltas, gap). Es la
 * forma de seguir a dos o tres pilotos durante la carrera sin perder de vista
 * el resto del panel.
 *
 * El dock se dibuja solo cuando hay alguien seguido: sin pilotos seleccionados
 * no hay nada que mostrar y taparia la pagina.
 */
import { computed, onBeforeUnmount, ref } from 'vue'
import { ChevronDown, ChevronUp, Maximize2, Star, X } from '@lucide/vue'
import FollowDriverModal from '@/components/FollowDriverModal.vue'
import SearchSelect, { type SearchOption } from '@/components/SearchSelect.vue'
import { MAX_FOLLOWED_DRIVERS, useRaceStore } from '@/stores/race'
import { tyreStyle } from '@/utils/tyres'
import type { Driver, TimingEntry } from '@/types'

const store = useRaceStore()

/** Piloto abierto en el modal de detalle. */
const abierto = ref<string | null>(null)
/** Piloto elegido en el combo (se reinicia al agregar, para volver al texto). */
const elegido = ref<string | null>(null)
/** Aviso efimero (por ejemplo, que se llenaron los cupos). */
const aviso = ref<string | null>(null)
/** Dock plegado: deja solo la franja con el contador. */
const plegado = ref(false)

let temporizador: number | null = null

function avisar(texto: string) {
  aviso.value = texto
  if (temporizador !== null) window.clearTimeout(temporizador)
  temporizador = window.setTimeout(() => {
    aviso.value = null
  }, 2600)
}

onBeforeUnmount(() => {
  if (temporizador !== null) window.clearTimeout(temporizador)
})

/** Pilotos que todavia no se siguen, para el combo de busqueda. */
const opciones = computed<SearchOption[]>(() =>
  store.timing
    .filter((entry) => !store.isFollowing(entry.driver_number))
    .map((entry) => ({
      value: entry.driver_number,
      label: entry.driver?.full_name ?? `#${entry.driver_number}`,
      hint: entry.driver?.team_name ?? undefined,
    })),
)

interface Tarjeta {
  numero: string
  entry: TimingEntry | null
  nombre: string
  equipo: string | null
  color: string
}

function colorDe(color: string | null | undefined): string {
  if (!color) return '#2b3b60'
  return color.startsWith('#') ? color : `#${color}`
}

const tarjetas = computed<Tarjeta[]>(() =>
  store.followedDrivers.map((numero) => {
    const entry = store.timing.find((item) => item.driver_number === numero) ?? null
    const driver: Driver | null =
      entry?.driver ?? store.drivers.find((item) => item.number === numero) ?? null
    return {
      numero,
      entry,
      nombre: driver?.full_name ?? `#${numero}`,
      equipo: driver?.team_name ?? null,
      color: colorDe(driver?.team_colour),
    }
  }),
)

function agregar(numero: string | null) {
  if (!numero) return
  const resultado = store.toggleFollow(numero)
  elegido.value = null
  if (resultado === 'limit') {
    avisar(`Ya seguís a ${MAX_FOLLOWED_DRIVERS} pilotos: sacá uno antes de agregar otro.`)
    return
  }
  if (resultado === 'added' && store.followLimitReached) {
    avisar(`Cupo completo: ${MAX_FOLLOWED_DRIVERS} pilotos seguidos.`)
  }
}

/**
 * Gap con el lider.
 *
 * En el feed en vivo el gap llega en dos lugares según el tipo de sesión: en
 * eliminatoria viene dentro de `Stats` y en carrera puede venir en
 * `GapToLeader`. Se toma el que haya: sin dato se muestra "—", nunca 0.
 */
function gapDe(entry: TimingEntry | null): string {
  if (!entry) return '—'
  return entry.gap_to_leader || entry.time_diff_to_fastest || '—'
}

/** Intervalo con el auto de adelante. */
function intervaloDe(entry: TimingEntry | null): string {
  if (!entry) return '—'
  return entry.interval_to_ahead || entry.time_diff_to_position_ahead || '—'
}

/** El compuesto vigente: el feed en vivo lo trae en la propia entrada. */
function compuestoDe(entry: TimingEntry | null): string | null {
  if (!entry) return null
  return entry.tyre_compound ?? store.compoundByDriver[entry.driver_number] ?? null
}
</script>

<template>
  <aside
    v-if="store.followedDrivers.length"
    class="fixed inset-x-0 bottom-0 z-40 border-t border-race-750/80 bg-race-950/95 shadow-[0_-8px_28px_rgba(0,0,0,0.55)] backdrop-blur-md"
  >
    <!-- Cabecera: contador, alta de pilotos y estado de los datos -->
    <div class="mx-auto flex max-w-[1800px] flex-wrap items-center gap-x-4 gap-y-2 px-4 pt-2">
      <div class="flex items-center gap-2">
        <Star class="h-3.5 w-3.5 text-accent" fill="currentColor" />
        <span class="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
          Seguidos
        </span>
        <span class="chip num">{{ store.followedDrivers.length }}/{{ MAX_FOLLOWED_DRIVERS }}</span>
      </div>

      <div v-if="!plegado" class="w-64">
        <SearchSelect
          :model-value="elegido"
          :options="opciones"
          direction="up"
          placeholder="Seguir a un piloto..."
          @update:model-value="agregar"
        />
      </div>

      <span
        v-if="store.dataState === 'LIVE'"
        class="chip border-accent/50 text-accent"
        title="Datos del proveedor en vivo"
      >
        <span class="live-dot h-1.5 w-1.5 rounded-full bg-accent" />
        En vivo
      </span>
      <span v-else class="chip" :title="`Estado de los datos: ${store.dataState}`">
        {{ store.dataState === 'HISTORICAL' ? 'Sesion finalizada' : store.dataState }}
      </span>

      <p v-if="aviso" class="text-[11px] text-warn">{{ aviso }}</p>

      <button
        type="button"
        class="ml-auto flex items-center gap-1 text-[10px] uppercase tracking-[0.12em] text-slate-500 hover:text-slate-300"
        :title="plegado ? 'Desplegar el dock' : 'Plegar el dock'"
        @click="plegado = !plegado"
      >
        <ChevronDown v-if="plegado" class="h-3.5 w-3.5" />
        <ChevronUp v-else class="h-3.5 w-3.5" />
        {{ plegado ? 'Desplegar' : 'Plegar' }}
      </button>
    </div>

    <!-- Tarjetas -->
    <div v-if="!plegado" class="mx-auto max-w-[1800px] px-4 pb-3 pt-2">
      <div class="flex gap-3 overflow-x-auto">
        <article
          v-for="tarjeta in tarjetas"
          :key="tarjeta.numero"
          class="min-w-[290px] flex-1 rounded-lg border border-race-750/70 bg-race-900/85 p-2.5 transition-colors hover:border-race-700"
        >
          <!-- Identidad -->
          <header class="flex items-start gap-2">
            <span
              class="mt-0.5 h-10 w-1 shrink-0 rounded-full"
              :style="{ backgroundColor: tarjeta.color }"
            />
            <div class="min-w-0 flex-1">
              <div class="flex items-baseline gap-2">
                <span class="num text-xl font-black leading-none text-white">
                  {{ tarjeta.entry?.position ?? '—' }}
                </span>
                <span class="truncate text-[13px] font-bold text-slate-100">
                  {{ tarjeta.nombre }}
                </span>
              </div>
              <p class="truncate text-[10px] uppercase tracking-[0.12em] text-slate-500">
                {{ tarjeta.equipo ?? '—' }} · #{{ tarjeta.numero }}
              </p>
            </div>
            <button
              type="button"
              class="rounded p-1 text-slate-600 hover:bg-race-800 hover:text-bad"
              title="Dejar de seguir a este piloto"
              @click="store.toggleFollow(tarjeta.numero)"
            >
              <X class="h-3.5 w-3.5" />
            </button>
          </header>

          <!-- Datos en vivo -->
          <dl class="mt-2 grid grid-cols-3 gap-x-2 gap-y-1.5 sm:grid-cols-6">
            <div class="min-w-0">
              <dt class="truncate text-[9px] uppercase tracking-[0.1em] text-slate-500" title="Mejor vuelta">
                Mejor
              </dt>
              <dd class="num truncate text-[13px] font-bold text-slate-100">
                {{ tarjeta.entry?.best_lap_time_display ?? '—' }}
                <span
                  v-if="tarjeta.entry?.best_lap_number"
                  class="text-[10px] font-normal text-slate-500"
                >
                  v{{ tarjeta.entry.best_lap_number }}
                </span>
              </dd>
            </div>
            <div class="min-w-0">
              <dt class="truncate text-[9px] uppercase tracking-[0.1em] text-slate-500" title="Ultima vuelta">
                Ultima
              </dt>
              <dd class="num truncate text-[13px] font-semibold text-slate-200">
                {{ tarjeta.entry?.last_lap_time_display ?? '—' }}
              </dd>
            </div>
            <div class="min-w-0">
              <dt class="truncate text-[9px] uppercase tracking-[0.1em] text-slate-500" title="Gap con el lider">
                Gap
              </dt>
              <dd class="num truncate text-[13px] font-semibold text-slate-200">
                {{ gapDe(tarjeta.entry) }}
              </dd>
            </div>
            <div class="min-w-0">
              <dt class="truncate text-[9px] uppercase tracking-[0.1em] text-slate-500" title="Intervalo con el auto de adelante">
                Inter
              </dt>
              <dd class="num truncate text-[13px] text-slate-300">
                {{ intervaloDe(tarjeta.entry) }}
              </dd>
            </div>
            <div class="min-w-0">
              <dt class="truncate text-[9px] uppercase tracking-[0.1em] text-slate-500" title="Vueltas completadas">
                Vueltas
              </dt>
              <dd class="num text-[13px] text-slate-300">
                {{ tarjeta.entry?.number_of_laps ?? '—' }}
              </dd>
            </div>
            <div class="min-w-0">
              <dt class="truncate text-[9px] uppercase tracking-[0.1em] text-slate-500" title="Neumatico vigente">
                Neu
              </dt>
              <dd class="flex items-center gap-1">
                <span
                  class="flex h-5 w-5 items-center justify-center rounded text-[10px] font-bold"
                  :style="{
                    backgroundColor: tyreStyle(compuestoDe(tarjeta.entry)).bg,
                    color: tyreStyle(compuestoDe(tarjeta.entry)).color,
                  }"
                  :title="tyreStyle(compuestoDe(tarjeta.entry)).name"
                >
                  {{ tyreStyle(compuestoDe(tarjeta.entry)).label }}
                </span>
                <span class="num text-[11px] text-slate-500">
                  {{ tarjeta.entry?.tyre_age != null ? `v${tarjeta.entry.tyre_age}` : '' }}
                </span>
              </dd>
            </div>
          </dl>

          <!-- Sectores y estado -->
          <div class="mt-2 flex flex-wrap items-center gap-1.5">
            <span
              v-for="sector in tarjeta.entry?.sectors ?? []"
              :key="sector.index"
              class="num rounded px-1.5 py-0.5 text-[10px] font-semibold"
              :class="
                sector.overall_fastest
                  ? 'bg-sector-overall/20 text-sector-overall'
                  : sector.personal_fastest
                    ? 'bg-sector-best/20 text-sector-best'
                    : 'bg-race-800/80 text-slate-400'
              "
              :title="`Sector ${sector.index + 1}`"
            >
              S{{ sector.index + 1 }} {{ sector.time_display ?? '—' }}
            </span>

            <span v-if="tarjeta.entry?.retired" class="chip border-bad/40 text-bad">DNF</span>
            <span
              v-if="tarjeta.entry?.in_pit && store.sessionIsActive"
              class="chip border-warn/40 text-warn"
            >
              En boxes
            </span>
            <span
              v-if="tarjeta.entry?.pit_out && store.sessionIsActive"
              class="chip border-warn/40 text-warn"
            >
              Salida
            </span>
            <span
              v-if="tarjeta.entry?.stopped && store.sessionIsActive"
              class="chip border-bad/40 text-bad"
            >
              Parado
            </span>

            <button
              type="button"
              class="ml-auto flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] uppercase tracking-[0.1em] text-slate-500 hover:bg-race-800 hover:text-slate-200"
              title="Ver el detalle del piloto"
              @click="abierto = tarjeta.numero"
            >
              <Maximize2 class="h-3 w-3" />
              Detalle
            </button>
          </div>
        </article>

        <!-- Hueco para agregar otro piloto -->
        <div
          v-if="tarjetas.length < MAX_FOLLOWED_DRIVERS"
          class="flex min-w-[200px] flex-1 items-center justify-center rounded-lg border border-dashed border-race-700/70 px-4 py-4 text-center text-[11px] text-slate-500"
        >
          Elegí otro piloto para seguirlo
        </div>
      </div>
    </div>

    <!--
        El modal va con Teleport: el dock tiene `backdrop-blur` y eso lo
        convierte en bloque contenedor de los descendientes `fixed`, asi que
        sin Teleport el modal se dibuja adentro del dock en vez de sobre la
        pagina.
    -->
    <Teleport to="body">
      <FollowDriverModal :driver-number="abierto" @close="abierto = null" />
    </Teleport>
  </aside>
</template>
