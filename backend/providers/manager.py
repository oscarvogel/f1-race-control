"""Gestor multiproveedor.

El :class:`ProviderManager` es el unico punto por el que el backend pide
datos. Aplica tres reglas que el resto del sistema da por ciertas:

1. **Separacion de semantica.** Un pedido de datos *live* NUNCA se resuelve
   con un proveedor *historico*. Si la fuente en vivo no esta disponible, el
   resultado lo dice explicitamente (con su estado y su error) en lugar de
   servir un historico disfrazado de directo.
2. **Sin datos inventados.** Si ningun proveedor de la semantica pedida puede
   satisfacer la capacidad, se devuelve ``None`` / lista vacia **con el motivo
   registrado**, nunca un valor inventado.
3. **Trazabilidad.** Cada resultado normalizado lleva ``provider_id`` y
   ``source_timestamp``: el frontend siempre sabe de donde salio el dato y de
   que antiguedad tiene.

Ademas mide, por proveedor: estado de conexion, latencia observada, edad del
ultimo dato, ultimo error y numero de reconexiones.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Iterable

from .base import (
    DELAYED,
    ERROR,
    HISTORICAL,
    LIVE,
    OFFLINE,
    REPLAY,
    WAITING,
    Driver,
    ProviderCapabilities,
    ProviderError,
    ProviderStatus,
    RaceControlEvent,
    SessionInfo,
    Stint,
    TelemetrySample,
    TimingEntry,
    TimingProvider,
    UnsupportedCapability,
    WeatherReport,
    sort_timing_entries,
)

# Ambito semantico de un pedido.
SCOPE_LIVE = "live"
SCOPE_HISTORICAL = "historical"
SCOPE_METADATA = "metadata"

# Capacidad -> metodo del proveedor.
_CAPABILITY_METHODS = {
    "session": "get_session",
    "drivers": "get_drivers",
    "timing": "get_timing",
    "laps": "get_laps",
    "stints": "get_stints",
    "tyres": "get_tyres",
    "weather": "get_weather",
    "race_control": "get_race_control",
    "telemetry": "get_telemetry",
    "positions": "get_positions",
    "track_status": "get_track_status",
}


class ProviderManager:
    """Registro de proveedores, seleccion por capacidad y estado."""

    def __init__(
        self,
        providers: Iterable[TimingProvider] | None = None,
        live_provider: str | None = None,
        historical_provider: str | None = None,
        metadata_provider: str | None = None,
        mode: str = "auto",
        live_max_age_seconds: float = 90.0,
        delayed_max_age_seconds: float = 300.0,
    ) -> None:
        self._providers: dict[str, TimingProvider] = {}
        for provider in providers or []:
            self.register(provider)

        self.live_provider = live_provider
        self.historical_provider = historical_provider
        self.metadata_provider = metadata_provider
        self.mode = mode  # "auto" | "live" | "historical" | "metadata"

        # Umbrales de frescura. Documentados y configurables: dependen de la
        # frecuencia real de cada proveedor (el feed live entrega por debajo
        # del Hz durante una sesion activa).
        self.live_max_age_seconds = live_max_age_seconds
        self.delayed_max_age_seconds = delayed_max_age_seconds

        self.last_error: dict[str, str] = {}
        self._capability_cache: dict[str, ProviderCapabilities] = {}
        # Ultimo instante (monotono) en que se comprobo el estado de cada
        # proveedor, para respetar su cadencia declarada.
        self._last_health_check: dict[str, float] = {}

    # -- registro ---------------------------------------------------------- #

    def register(self, provider: TimingProvider) -> None:
        self._providers[provider.provider_id] = provider

    @property
    def providers(self) -> list[TimingProvider]:
        return list(self._providers.values())

    def get(self, provider_id: str) -> TimingProvider | None:
        return self._providers.get(provider_id)

    # -- ciclo de vida ----------------------------------------------------- #

    async def connect_all(self) -> dict[str, bool]:
        results: dict[str, bool] = {}
        for provider_id, provider in self._providers.items():
            try:
                results[provider_id] = await provider.connect()
            except Exception as exc:  # pragma: no cover - defensivo
                results[provider_id] = False
                self.last_error[provider_id] = "%s: %s" % (type(exc).__name__, exc)
        return results

    async def disconnect_all(self) -> None:
        for provider in self._providers.values():
            try:
                await provider.disconnect()
            except Exception:  # pragma: no cover - defensivo
                pass

    async def refresh_status(self, force: bool = False) -> list[ProviderStatus]:
        """Consulta el estado real de cada proveedor.

        Respeta la cadencia declarada por cada proveedor
        (``health_check_interval``): un proveedor externo con limite de tasa
        no se sondea en cada ciclo. El estado cacheado se devuelve tal cual,
        con su ``updated_at`` original, para que el diagnostico siga siendo
        honesto sobre cuando se comprobo.
        """
        statuses: list[ProviderStatus] = []
        now = time.monotonic()
        for provider in self._providers.values():
            interval = float(getattr(provider, "health_check_interval", 0.0) or 0.0)
            last = self._last_health_check.get(provider.provider_id)
            if (
                not force
                and interval > 0
                and last is not None
                and (now - last) < interval
            ):
                statuses.append(provider.status)
                continue
            try:
                status = await provider.health_check()
                self._last_health_check[provider.provider_id] = time.monotonic()
                statuses.append(status)
            except Exception as exc:
                provider.status.state = ERROR
                provider.status.is_connected = False
                provider.status.last_error = "%s: %s" % (type(exc).__name__, exc)
                provider.status.updated_at = datetime.now(timezone.utc)
                self._last_health_check[provider.provider_id] = time.monotonic()
                statuses.append(provider.status)
        return statuses

    def status_list(self) -> list[ProviderStatus]:
        return [provider.status for provider in self._providers.values()]

    async def capabilities(self) -> list[ProviderCapabilities]:
        caps: list[ProviderCapabilities] = []
        for provider in self._providers.values():
            try:
                caps.append(await provider.get_capabilities())
            except Exception:
                caps.append(
                    ProviderCapabilities(
                        provider_id=provider.provider_id,
                        notes="No se pudieron obtener las capacidades.",
                    )
                )
        return caps

    # -- seleccion --------------------------------------------------------- #

    def _scope_of(self, capability: str) -> str:
        """Determina el ambito semantico segun la configuracion."""
        if self.mode == "live":
            return SCOPE_LIVE
        if self.mode == "historical":
            return SCOPE_HISTORICAL
        if self.mode == "metadata":
            return SCOPE_METADATA

        # auto: el ambito por defecto de cada capacidad.
        if capability in ("session", "drivers", "timing", "weather", "race_control", "tyres"):
            return SCOPE_LIVE
        if capability in ("laps", "positions", "telemetry"):
            return SCOPE_HISTORICAL
        return SCOPE_METADATA

    def _preferred_id(self, scope: str) -> str | None:
        if scope == SCOPE_LIVE:
            return self.live_provider
        if scope == SCOPE_HISTORICAL:
            return self.historical_provider
        if scope == SCOPE_METADATA:
            return self.metadata_provider
        return None

    def _in_scope(self, provider: TimingProvider, scope: str) -> bool:
        caps = self._capability_cache.get(provider.provider_id)
        if caps is None:
            caps = provider.status.capabilities
        if caps is None:
            # Sin informacion de capacidades: no se puede afirmar que el
            # proveedor serve la semantica pedida.
            return False
        if scope == SCOPE_LIVE:
            return caps.live
        if scope == SCOPE_HISTORICAL:
            return caps.historical
        return caps.metadata

    def select_provider(self, capability: str, scope: str | None = None) -> TimingProvider | None:
        """Elige el proveedor para una capacidad.

        Prioridad: proveedor configurado explicitamente para el ambito, luego
        el resto de proveedores del mismo ambito ordenados por:

        1. estado de conexion,
        2. frescura del ultimo dato,
        3. menor latencia observada.
        """
        scope = scope or self._scope_of(capability)
        candidates = [
            provider
            for provider in self._providers.values()
            if self._in_scope(provider, scope)
        ]
        if not candidates:
            return None

        preferred = self._preferred_id(scope)
        if preferred:
            for provider in candidates:
                if provider.provider_id == preferred:
                    return provider

        def rank(provider: TimingProvider):
            status = provider.status
            age = status.data_age_seconds
            if status.state == ERROR:
                age_bucket = 3
            elif not status.is_connected:
                age_bucket = 2
            elif age is None:
                age_bucket = 1
            else:
                age_bucket = 0
            return (
                age_bucket,
                age if age is not None else 1e9,
                status.latency_ms if status.latency_ms is not None else 1e9,
                provider.provider_id,
            )

        return sorted(candidates, key=rank)[0]

    # -- acceso a datos ---------------------------------------------------- #

    async def fetch(
        self,
        capability: str,
        scope: str | None = None,
        **kwargs: Any,
    ) -> tuple[Any, str | None]:
        """Obtiene un conjunto de datos normalizado.

        Devuelve ``(datos, provider_id)``. Si nada puede satisfacer la
        capacidad, devuelve ``(None, None)`` y deja el motivo en
        ``self.last_error``.
        """
        method_name = _CAPABILITY_METHODS.get(capability)
        if method_name is None:
            raise ValueError("Capacidad desconocida: %s" % capability)

        scope = scope or self._scope_of(capability)
        provider = self.select_provider(capability, scope)
        if provider is None:
            self.last_error["*"] = (
                "Ningun proveedor registrado soporta '%s' en ambito '%s'." % (capability, scope)
            )
            return None, None

        started = time.perf_counter()
        try:
            method: Callable[..., Awaitable[Any]] = getattr(provider, method_name)
            data = await method(**kwargs)
        except UnsupportedCapability:
            self.last_error[provider.provider_id] = (
                "El proveedor %s no soporta la capacidad '%s'." % (provider.provider_id, capability)
            )
            return None, None
        except ProviderError as exc:
            self.last_error[provider.provider_id] = str(exc)
            provider.status.last_error = str(exc)
            provider.status.error_count += 1
            provider.status.updated_at = datetime.now(timezone.utc)
            return None, None
        except Exception as exc:  # pragma: no cover - defensivo
            self.last_error[provider.provider_id] = "%s: %s" % (type(exc).__name__, exc)
            provider.status.last_error = self.last_error[provider.provider_id]
            provider.status.error_count += 1
            provider.status.updated_at = datetime.now(timezone.utc)
            return None, None

        latency_ms = (time.perf_counter() - started) * 1000.0
        provider.status.latency_ms = round(latency_ms, 2)
        provider.status.updated_at = datetime.now(timezone.utc)
        self.last_error.pop(provider.provider_id, None)
        return data, provider.provider_id

    async def get_timing(self, scope: str | None = None) -> list[TimingEntry]:
        entries, _ = await self.fetch("timing", scope)
        if not entries:
            return []
        return sort_timing_entries(entries)

    async def get_drivers(self, scope: str | None = None) -> list[Driver]:
        drivers, _ = await self.fetch("drivers", scope)
        return drivers or []

    async def get_session(self, scope: str | None = None) -> SessionInfo | None:
        session, _ = await self.fetch("session", scope)
        return session

    async def get_weather(self, scope: str | None = None) -> WeatherReport | None:
        weather, _ = await self.fetch("weather", scope)
        return weather

    async def get_race_control(self, scope: str | None = None) -> list[RaceControlEvent]:
        events, _ = await self.fetch("race_control", scope)
        return events or []

    async def get_tyres(self, scope: str | None = None) -> list[Stint]:
        stints, _ = await self.fetch("tyres", scope)
        return stints or []

    async def get_stints(self, scope: str | None = None) -> list[Stint]:
        stints, _ = await self.fetch("stints", scope)
        return stints or []

    async def get_laps(self, scope: str | None = None) -> list:
        laps, _ = await self.fetch("laps", scope)
        return laps or []

    async def get_telemetry(self, scope: str | None = None) -> list[TelemetrySample]:
        samples, _ = await self.fetch("telemetry", scope)
        return samples or []

    async def get_positions(self, scope: str | None = None) -> list[dict[str, Any]]:
        positions, _ = await self.fetch("positions", scope)
        return positions or []

    async def get_track_status(self, scope: str | None = None) -> dict[str, Any] | None:
        status, _ = await self.fetch("track_status", scope)
        return status

    # -- estado semantico del dataset ------------------------------------- #

    def classify_state(self, session: SessionInfo | None) -> str:
        """Traduce el estado tecnico a los estados que ve el usuario.

        LIVE      -> datos actuales de una sesion activa, de una fuente autorizada.
        DELAYED   -> hay datos, pero con retraso relevante.
        HISTORICAL-> sesion finalizada.
        REPLAY    -> reproduccion de una sesion historica.
        WAITING   -> sesion identificada pero sin registros actuales.
        OFFLINE   -> fuente desconectada o no disponible.
        ERROR     -> fallo conocido de la ingesta.
        """
        provider = self._providers.get(self.live_provider or "") or (
            self._providers.get("free_livetiming")
        )
        status = provider.status if provider else None

        if status is None:
            return OFFLINE
        if status.state == ERROR:
            return ERROR

        finalised = bool(session and session.state and session.state.lower() in (
            "finalised", "finished", "ended", "completed",
        ))

        if not status.is_connected:
            return OFFLINE

        if session is None:
            return WAITING

        if finalised:
            return HISTORICAL

        age = status.data_age_seconds
        if age is None:
            return WAITING
        if age <= self.live_max_age_seconds:
            return LIVE
        if age <= self.delayed_max_age_seconds:
            return DELAYED
        return OFFLINE

    def diagnostics(self) -> dict[str, Any]:
        """Resumen para el panel de diagnostico del frontend."""
        return {
            "mode": self.mode,
            "live_provider": self.live_provider,
            "historical_provider": self.historical_provider,
            "metadata_provider": self.metadata_provider,
            "thresholds": {
                "live_max_age_seconds": self.live_max_age_seconds,
                "delayed_max_age_seconds": self.delayed_max_age_seconds,
            },
            "providers": [status.as_dict() for status in self.status_list()],
            "last_error": dict(self.last_error),
        }
