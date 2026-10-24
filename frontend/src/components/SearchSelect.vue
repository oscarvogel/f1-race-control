<script setup lang="ts">
/**
 * Combo con busqueda.
 *
 * Se escribe, se filtra y se elige una opcion real: si el texto no coincide
 * con ninguna opcion, **no** se guarda nada (queda sin seleccion). Es lo que
 * hace falta cuando la lista es larga (22 pilotos) y el desplegable obliga a
 * deslizar.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ChevronDown } from '@lucide/vue'

export interface SearchOption {
  value: string
  label: string
  hint?: string
}

const props = withDefaults(
  defineProps<{
    options: SearchOption[]
    modelValue: string | null
    placeholder?: string
    /** Permite dejar la seleccion vacia (p. ej. "sin comparacion"). */
    allowEmpty?: boolean
    emptyLabel?: string
    disabled?: boolean
  }>(),
  {
    placeholder: 'Buscar...',
    allowEmpty: false,
    emptyLabel: 'Ninguno',
    disabled: false,
  },
)

const emit = defineEmits<{ (e: 'update:modelValue', value: string | null): void }>()

const texto = ref('')
const abierto = ref(false)
const resaltado = ref(0)
const contenedor = ref<HTMLElement | null>(null)

/** Sin tildes y en minusculas: "norris" encuentra a "Norris". */
function normalizar(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
}
const seleccionada = computed(
  () => props.options.find((option) => option.value === props.modelValue) ?? null,
)

const filtradas = computed(() => {
  const filtro = normalizar(texto.value)
  if (!filtro) return props.options
  return props.options.filter((option) => normalizar(option.label).includes(filtro))
})

function etiquetaDe(value: string | null): string {
  if (!value) return ''
  return props.options.find((option) => option.value === value)?.label ?? ''
}

function abrir() {
  if (props.disabled) return
  texto.value = etiquetaDe(props.modelValue)
  abierto.value = true
  resaltado.value = Math.max(
    0,
    props.options.findIndex((option) => option.value === props.modelValue),
  )
}

function cerrar() {
  abierto.value = false
  // Al cerrar, el campo vuelve a mostrar exactamente la opcion elegida.
  texto.value = etiquetaDe(props.modelValue)
}

function elegir(option: SearchOption) {
  emit('update:modelValue', option.value)
  texto.value = option.label
  abierto.value = false
}

function limpiar() {
  emit('update:modelValue', null)
  texto.value = ''
  abierto.value = true
}

function onInput() {
  abierto.value = true
  resaltado.value = 0
  const exacto = props.options.find(
    (option) => normalizar(option.label) === normalizar(texto.value),
  )
  // Sin coincidencia exacta no se guarda nada: solo se filtra la lista.
  emit('update:modelValue', exacto ? exacto.value : null)
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    abierto.value = true
    resaltado.value = Math.min(resaltado.value + 1, filtradas.value.length - 1)
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    resaltado.value = Math.max(resaltado.value - 1, 0)
  } else if (event.key === 'Enter') {
    event.preventDefault()
    const opcion = filtradas.value[resaltado.value]
    if (opcion) elegir(opcion)
  } else if (event.key === 'Escape') {
    cerrar()
  }
}

function onClickFuera(event: MouseEvent) {
  if (!contenedor.value) return
  if (!contenedor.value.contains(event.target as Node)) cerrar()
}

watch(
  () => props.modelValue,
  (valor) => {
    if (!abierto.value) texto.value = etiquetaDe(valor)
  },
)

onMounted(() => document.addEventListener('click', onClickFuera))
onBeforeUnmount(() => document.removeEventListener('click', onClickFuera))
</script>

<template>
  <div ref="contenedor" class="relative">
    <div class="relative">
      <input
        :value="texto"
        type="text"
        :placeholder="placeholder"
        :disabled="disabled"
        autocomplete="off"
        class="num w-full rounded-md border border-race-700 bg-race-850/80 px-2.5 py-1.5 pr-7 text-[12px] text-slate-200 outline-none transition focus:border-accent/70 focus:ring-1 focus:ring-accent/40 disabled:opacity-50"
        @focus="abrir"
        @input="onInput"
        @keydown="onKeydown"
      />
      <ChevronDown class="pointer-events-none absolute right-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
    </div>

    <button
      v-if="allowEmpty && (modelValue || texto)"
      type="button"
      class="mt-1 text-[10px] uppercase tracking-[0.1em] text-slate-500 hover:text-accent"
      @click="limpiar"
    >
      {{ emptyLabel }}
    </button>

    <ul
      v-if="abierto && filtradas.length"
      class="absolute z-40 mt-1 max-h-64 w-full overflow-auto rounded-md border border-race-700 bg-race-900/95 py-1 shadow-xl backdrop-blur"
    >
      <li
        v-for="(option, index) in filtradas"
        :key="option.value"
        class="flex cursor-pointer items-center justify-between gap-2 px-2.5 py-1.5 text-[12px]"
        :class="index === resaltado ? 'bg-race-750/80 text-white' : 'text-slate-300'"
        @mouseenter="resaltado = index"
        @mousedown.prevent="elegir(option)"
      >
        <span class="truncate">{{ option.label }}</span>
        <span v-if="option.hint" class="num shrink-0 text-[10px] text-slate-500">{{ option.hint }}</span>
      </li>
    </ul>

    <p v-else-if="abierto && !filtradas.length" class="mt-1 text-[11px] text-slate-500">
      Sin coincidencias.
    </p>
  </div>
</template>
