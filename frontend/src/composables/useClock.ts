/**
 * Reloj compartido de la interfaz (1 Hz).
 *
 * La cabecera muestra la hora local y del circuito, y la clasificacion
 * muestra la cuenta regresiva del final de sesion. Si cada componente
 * montara su propio `setInterval`, los dos relojes se desfasarian y la
 * cuenta regresiva "saltaba" respecto de la hora que se ve arriba.
 *
 * El intervalo se crea con el primer consumidor y se destruye con el
 * ultimo, asi que no queda ningun temporizador vivo al desmontar todo.
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'

const now = ref<Date>(new Date())

let timer: number | null = null
let consumers = 0

export function useClock() {
  onMounted(() => {
    consumers += 1
    if (timer === null) {
      timer = window.setInterval(() => (now.value = new Date()), 1000)
    }
  })

  onBeforeUnmount(() => {
    consumers -= 1
    if (consumers <= 0 && timer !== null) {
      window.clearInterval(timer)
      timer = null
    }
  })

  return now
}
