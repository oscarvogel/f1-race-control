/**
 * Estilo de los neumaticos.
 *
 * Vive aparte para que la clasificacion, el dock de pilotos seguidos y el
 * modal usen los mismos colores: si cada componente define su propio mapa,
 * un compuesto nuevo aparece con un color distinto en cada pantalla.
 */

export interface TyreStyle {
  /** Letra corta (S, M, H, I, W). */
  label: string
  /** Nombre completo del compuesto. */
  name: string
  /** Color del texto. */
  color: string
  /** Fondo translucido. */
  bg: string
}

const TYRES: Record<string, TyreStyle> = {
  SOFT: { label: 'S', name: 'SOFT', color: '#ff5a6e', bg: 'rgba(232,17,45,0.18)' },
  MEDIUM: { label: 'M', name: 'MEDIUM', color: '#f5a623', bg: 'rgba(245,166,35,0.18)' },
  HARD: { label: 'H', name: 'HARD', color: '#e2e8f0', bg: 'rgba(226,232,240,0.14)' },
  INTERMEDIATE: { label: 'I', name: 'INTER', color: '#2ecc71', bg: 'rgba(46,204,113,0.18)' },
  WET: { label: 'W', name: 'WET', color: '#60a5fa', bg: 'rgba(59,130,246,0.18)' },
}

/** Sin dato se dibuja como guion: nunca como un compuesto inventado. */
export const SIN_COMPUESTO: TyreStyle = {
  label: '—',
  name: 'Sin pneumatico',
  color: '#64748b',
  bg: 'transparent',
}

/**
 * Estilo de un compuesto.
 *
 * Acepta cualquier casing: el feed escribe "Soft", "SOFT" y "Medium" segun
 * el origen. Un compuesto desconocido no se descarta: se muestra con su
 * inicial y su color neutro.
 */
export function tyreStyle(compound: string | null | undefined): TyreStyle {
  if (!compound) return SIN_COMPUESTO
  const found = TYRES[compound.trim().toUpperCase()]
  if (found) return found
  const inicial = compound.trim().slice(0, 1).toUpperCase()
  return {
    label: inicial || '—',
    name: compound.trim().toUpperCase(),
    color: '#94a3b8',
    bg: 'transparent',
  }
}
