<script setup lang="ts">
/**
 * Selector de sesion: la que esta en vivo o cualquiera de las sesiones del
 * Gran Premio (FP1, FP2, FP3, Sprint, Clasificacion, Carrera).
 *
 * Cambiar de sesion no cambia el formato de los datos: la interfaz siempre
 * consume el modelo normalizado, asi que la clasificacion, los sectores, los
 * neumaticos y el control de carrera se muestran igual en todos los casos.
 */
import { computed } from 'vue'
import { History, Loader2, Radio } from '@lucide/vue'
import { useRaceStore } from '@/stores/race'

const store = useRaceStore()

const TYPE_LABEL: Record<string, string> = {
  practice: 'Entrenamiento',
  sprint: 'Sprint',
  sprintshootout: 'Sprint (disputa)',
  qualifying: 'Clasificación',
  race: 'Carrera',
}

/** Nombre corto y en español de cada sesion. */
function labelFor(option: { session_type: string | null; session_name: string | null; session_key: string }): string {
  const type = (option.session_type ?? '').toLowerCase()
  const base = TYPE_LABEL[type] ?? option.session_type ?? 'Sesion'

  if (type === 'practice') {
    const number = (option.session_name ?? '').match(/(\d+)/)?.[1]
    return number ? `${base} ${number}` : base
  }
  if (type === 'qualifying') return base
  return base
}

const options = computed(() => store.sessionCatalog)

const currentValue = computed(() =>
  store.viewMode === 'historical' ? (store.activeSessionKey ?? 'live') : 'live',
)

async function onChange(event: Event) {
  const value = (event.target as HTMLSelectElement).value
  if (value === 'live') {
    await store.selectHistoricalSession(null)
    return
  }
  await store.selectHistoricalSession(value)
}
</script>

<template>
  <div class="flex items-center gap-2 rounded-lg border border-race-750/70 bg-race-900/70 px-2.5 py-1.5">
    <Radio
      v-if="store.viewMode === 'live'"
      class="h-3.5 w-3.5 text-accent"
      :stroke-width="2"
    />
    <History v-else class="h-3.5 w-3.5 text-slate-400" :stroke-width="2" />
    <Loader2
      v-if="store.loadingHistorical"
      class="h-3.5 w-3.5 animate-spin text-slate-400"
      :stroke-width="2"
    />
    <select
      class="max-w-[190px] cursor-pointer bg-transparent text-[12px] font-semibold text-slate-100 outline-none"
      :value="currentValue"
      title="Elegir sesion"
      @change="onChange"
    >
      <option value="live">En vivo</option>
      <option
        v-for="option in options"
        :key="option.session_key"
        :value="option.session_key"
      >
        {{ labelFor(option) }} · {{ option.session_key }}
      </option>
    </select>
  </div>
</template>
