/**
 * Polling periodico con pausa cuando la pestana no esta visible.
 *
 * El backend ya se encarga de la ingesta (un solo proceso); aqui solo se
 * consulta la API interna, que es barata.
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'

export function usePolling(fn: () => void | Promise<void>, intervalMs = 2000) {
  const running = ref(false)
  let timer: number | null = null
  let inFlight = false

  async function tick() {
    if (inFlight) return
    if (typeof document !== 'undefined' && document.hidden) return
    inFlight = true
    try {
      await fn()
    } finally {
      inFlight = false
    }
  }

  function start() {
    if (running.value) return
    running.value = true
    void tick()
    timer = window.setInterval(() => void tick(), intervalMs)
  }

  function stop() {
    running.value = false
    if (timer !== null) {
      window.clearInterval(timer)
      timer = null
    }
  }

  onMounted(start)
  onBeforeUnmount(stop)

  return { start, stop, running }
}
