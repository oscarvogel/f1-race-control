<script setup lang="ts">
import { computed } from 'vue'
import { CircleDot, Clock, Database, Plug, Server, X } from '@lucide/vue'
import StatusBadge from './StatusBadge.vue'
import { useRaceStore } from '@/stores/race'

const store = useRaceStore()

const providers = computed(() => store.providerStatus)
const diagnostics = computed(() => store.diagnostics)
const session = computed(() => store.session)

function ageLabel(seconds: number | null): string {
  if (seconds === null || seconds === undefined) return 'sin dato'
  if (seconds < 1) return 'ahora'
  if (seconds < 60) return `${seconds.toFixed(1)} s`
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`
  return `${(seconds / 3600).toFixed(1)} h`
}

function timeOf(value: string | null): string {
  if (!value) return '—'
  try {
    return new Date(value).toLocaleString('es-AR', {
      timeZone: 'America/Argentina/Cordoba',
      hour12: false,
    })
  } catch {
    return value
  }
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="store.diagnosticsOpen"
      class="fixed inset-0 z-50 flex items-center justify-center bg-race-950/85 p-4 backdrop-blur-sm"
      @click.self="store.diagnosticsOpen = false"
    >
      <div
        class="fade-up panel max-h-[88vh] w-full max-w-4xl overflow-hidden shadow-2xl shadow-black/60"
      >
        <header class="panel-title justify-between">
          <span>Diagnostico del sistema</span>
          <button
            type="button"
            class="rounded-md p-1 text-slate-500 transition hover:bg-race-800 hover:text-white"
            title="Cerrar"
            @click="store.diagnosticsOpen = false"
          >
            <X class="h-4 w-4" />
          </button>
        </header>

        <div class="max-h-[78vh] overflow-auto px-4 py-4">
          <!-- Sesion detectada -->
          <section class="mb-5">
            <h3 class="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
              <Server class="h-3.5 w-3.5" /> Sesion detectada
            </h3>
            <div class="grid grid-cols-2 gap-x-4 gap-y-2 rounded-lg border border-race-750/70 bg-race-850/50 px-4 py-3 sm:grid-cols-4">
              <div>
                <div class="text-[9px] uppercase tracking-[0.14em] text-slate-500">Gran Premio</div>
                <div class="truncate text-[13px] font-semibold text-slate-100">
                  {{ session?.meeting_name ?? '—' }}
                </div>
              </div>
              <div>
                <div class="text-[9px] uppercase tracking-[0.14em] text-slate-500">Sesion</div>
                <div class="truncate text-[13px] font-semibold text-slate-100">
                  {{ session?.session_name ?? session?.session_type ?? '—' }}
                </div>
              </div>
              <div>
                <div class="text-[9px] uppercase tracking-[0.14em] text-slate-500">ID del proveedor</div>
                <div class="num truncate text-[13px] font-semibold text-slate-100">
                  {{ session?.provider_session_id ?? '—' }}
                </div>
              </div>
              <div>
                <div class="text-[9px] uppercase tracking-[0.14em] text-slate-500">Estado</div>
                <div class="text-[13px] font-semibold text-slate-100">{{ session?.state ?? '—' }}</div>
              </div>
            </div>
          </section>

          <!-- Proveedores -->
          <section class="mb-5">
            <h3 class="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
              <Plug class="h-3.5 w-3.5" /> Proveedores
            </h3>
            <div class="space-y-2">
              <article
                v-for="provider in providers"
                :key="provider.provider_id"
                class="rounded-lg border border-race-750/70 bg-race-850/50 px-4 py-3"
              >
                <div class="flex flex-wrap items-center justify-between gap-2">
                  <div class="flex items-center gap-2">
                    <CircleDot
                      class="h-3.5 w-3.5"
                      :class="provider.is_connected ? 'text-ok' : 'text-bad'"
                    />
                    <span class="text-[13px] font-semibold text-slate-100">{{ provider.name }}</span>
                    <span class="chip">{{ provider.provider_id }}</span>
                  </div>
                  <StatusBadge :state="provider.state" size="sm" />
                </div>

                <dl class="mt-2.5 grid grid-cols-2 gap-x-4 gap-y-2 text-[11px] sm:grid-cols-4">
                  <div class="min-w-0">
                    <dt class="uppercase tracking-[0.1em] text-slate-500">Endpoint</dt>
                    <dd class="num truncate text-slate-300">{{ provider.endpoint || '—' }}</dd>
                  </div>
                  <div>
                    <dt class="uppercase tracking-[0.1em] text-slate-500">Ultimo mensaje</dt>
                    <dd class="num text-slate-300">{{ timeOf(provider.last_message_at) }}</dd>
                  </div>
                  <div>
                    <dt class="uppercase tracking-[0.1em] text-slate-500">Edad del dato</dt>
                    <dd class="num text-slate-300">{{ ageLabel(provider.data_age_seconds) }}</dd>
                  </div>
                  <div>
                    <dt class="uppercase tracking-[0.1em] text-slate-500">Latencia</dt>
                    <dd class="num text-slate-300">
                      {{ provider.latency_ms != null ? `${provider.latency_ms.toFixed(0)} ms` : '—' }}
                    </dd>
                  </div>
                  <div>
                    <dt class="uppercase tracking-[0.1em] text-slate-500">Errores</dt>
                    <dd class="num text-slate-300">{{ provider.error_count }}</dd>
                  </div>
                  <div>
                    <dt class="uppercase tracking-[0.1em] text-slate-500">Reconexiones</dt>
                    <dd class="num text-slate-300">{{ provider.reconnect_count }}</dd>
                  </div>
                  <div class="col-span-2 min-w-0">
                    <dt class="uppercase tracking-[0.1em] text-slate-500">Ultimo error</dt>
                    <dd class="num truncate text-bad" :title="provider.last_error ?? ''">
                      {{ provider.last_error || 'ninguno' }}
                    </dd>
                  </div>
                </dl>

                <p v-if="provider.capabilities?.notes" class="mt-2 text-[11px] italic text-slate-500">
                  {{ provider.capabilities.notes }}
                </p>
              </article>
            </div>
          </section>

          <!-- Seleccion activa -->
          <section v-if="diagnostics">
            <h3 class="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
              <Database class="h-3.5 w-3.5" /> Seleccion y umbrales
            </h3>
            <div class="grid grid-cols-2 gap-x-4 gap-y-2 rounded-lg border border-race-750/70 bg-race-850/50 px-4 py-3 sm:grid-cols-4">
              <div>
                <div class="text-[9px] uppercase tracking-[0.14em] text-slate-500">Modo</div>
                <div class="num text-[13px] text-slate-100">{{ diagnostics.mode }}</div>
              </div>
              <div>
                <div class="text-[9px] uppercase tracking-[0.14em] text-slate-500">Proveedor live</div>
                <div class="num text-[13px] text-slate-100">{{ diagnostics.live_provider ?? '—' }}</div>
              </div>
              <div>
                <div class="text-[9px] uppercase tracking-[0.14em] text-slate-500">Historico</div>
                <div class="num text-[13px] text-slate-100">{{ diagnostics.historical_provider ?? '—' }}</div>
              </div>
              <div>
                <div class="text-[9px] uppercase tracking-[0.14em] text-slate-500">Metadatos</div>
                <div class="num text-[13px] text-slate-100">{{ diagnostics.metadata_provider ?? '—' }}</div>
              </div>
              <div>
                <div class="text-[9px] uppercase tracking-[0.14em] text-slate-500">Umbral LIVE</div>
                <div class="num text-[13px] text-slate-100">{{ diagnostics.thresholds.live_max_age_seconds }} s</div>
              </div>
              <div>
                <div class="text-[9px] uppercase tracking-[0.14em] text-slate-500">Umbral DELAYED</div>
                <div class="num text-[13px] text-slate-100">{{ diagnostics.thresholds.delayed_max_age_seconds }} s</div>
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  </Teleport>
</template>
