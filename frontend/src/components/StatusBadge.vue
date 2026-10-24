<script setup lang="ts">
import { computed } from 'vue'
import type { DataState } from '@/types'

const props = defineProps<{
  state: DataState | string
  size?: 'sm' | 'md'
}>()

const config = computed(() => {
  switch (props.state) {
    case 'LIVE':
      return { label: 'LIVE', color: '#2ecc71', bg: 'rgba(46,204,113,0.14)', pulse: true }
    case 'DELAYED':
      return { label: 'DELAYED', color: '#f5a623', bg: 'rgba(245,166,35,0.14)', pulse: false }
    case 'HISTORICAL':
      return { label: 'HISTORICAL', color: '#60a5fa', bg: 'rgba(96,165,250,0.14)', pulse: false }
    case 'REPLAY':
      return { label: 'REPLAY', color: '#a78bfa', bg: 'rgba(167,139,250,0.14)', pulse: false }
    case 'WAITING':
      return { label: 'WAITING', color: '#94a3b8', bg: 'rgba(148,163,184,0.12)', pulse: true }
    case 'ERROR':
      return { label: 'ERROR', color: '#ff4d4d', bg: 'rgba(255,77,77,0.14)', pulse: false }
    default:
      return { label: 'OFFLINE', color: '#94a3b8', bg: 'rgba(148,163,184,0.12)', pulse: false }
  }
})
</script>

<template>
  <span
    class="inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 font-semibold uppercase tracking-[0.14em]"
    :style="{
      color: config.color,
      backgroundColor: config.bg,
      borderColor: config.color + '55',
      fontSize: size === 'sm' ? '9px' : '10px',
    }"
  >
    <span
      class="inline-block h-1.5 w-1.5 rounded-full"
      :class="config.pulse ? 'live-dot' : ''"
      :style="{ backgroundColor: config.color }"
    />
    {{ config.label }}
  </span>
</template>
