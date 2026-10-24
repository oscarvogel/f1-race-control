<script setup lang="ts">
import { computed } from 'vue'
import { Flag, MessageSquareWarning } from '@lucide/vue'
import { useRaceStore } from '@/stores/race'

const store = useRaceStore()

/** Ultimos eventos, del mas reciente al mas antiguo. */
const events = computed(() => [...store.raceControl].reverse().slice(0, 60))

function timeOf(utc: string | null): string {
  if (!utc) return '--:--:--'
  try {
    return new Date(utc).toLocaleTimeString('es-AR', {
      timeZone: 'America/Argentina/Cordoba',
      hour12: false,
    })
  } catch {
    return '--:--:--'
  }
}

/** Color por tipo de evento: banderas, penalizaciones y mensajes. */
function toneOf(category: string | null, flag: string | null): string {
  const flagValue = (flag ?? '').toUpperCase()
  if (flagValue.includes('RED')) return 'text-bad'
  if (flagValue.includes('YELLOW')) return 'text-warn'
  if (flagValue.includes('CHEQUERED')) return 'text-slate-300'
  if (flagValue.includes('SC') || flagValue.includes('VSC')) return 'text-warn'
  const text = (category ?? '').toLowerCase()
  if (text.includes('penal') || text.includes('steward')) return 'text-accent-soft'
  if (text.includes('flag')) return 'text-warn'
  return 'text-slate-400'
}
</script>

<template>
  <section class="panel flex min-h-0 flex-col overflow-hidden">
    <header class="panel-title justify-between">
      <span>Control de carrera</span>
      <span class="chip">{{ events.length }} eventos</span>
    </header>
    <div class="min-h-0 flex-1 overflow-auto">
      <ul v-if="events.length" class="divide-y divide-race-800/60">
        <li v-for="(event, index) in events" :key="`${event.utc}-${index}`" class="flex gap-2.5 px-4 py-2">
          <span class="num w-[52px] shrink-0 pt-0.5 text-[11px] text-slate-500">
            {{ timeOf(event.utc) }}
          </span>
          <span class="shrink-0 pt-0.5" :class="toneOf(event.category, event.flag)">
            <Flag v-if="event.flag" class="h-3.5 w-3.5" />
            <MessageSquareWarning v-else class="h-3.5 w-3.5" />
          </span>
          <span class="text-[12px] leading-snug text-slate-300">{{ event.message }}</span>
        </li>
      </ul>
      <p v-else class="px-4 py-8 text-center text-xs text-slate-500">
        Sin eventos de control de carrera recibidos.
      </p>
    </div>
  </section>
</template>
