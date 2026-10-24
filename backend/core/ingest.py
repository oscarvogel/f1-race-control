"""Ingesta de datos: un unico proceso que habla con los proveedores.

Diseno (seccion 12 de la especificacion):

1. **Un solo proceso de obtencion de datos.** El comando
   ``manage.py ingest_live`` es el unico que llama a los proveedores. El
   frontend nunca genera trafico hacia las APIs externas.
2. **Cache compartida del snapshot.** El resultado se guarda en SQLite
   (``SessionSnapshot``), que es la unica cache visible para el proceso de la
   API. Por eso abrir dos navegadores no duplica la ingesta.
3. **Solo se persiste si algo cambio.** Se calcula una huella SHA-256 del
   payload normalizado; si coincide con el ultimo snapshot, no se escribe una
   fila nueva.
4. **Reintentos con backoff y reconexion.** Cada ciclo reintenta con espera
   creciente si el proveedor falla.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from asgiref.sync import sync_to_async
from django.conf import settings
from django.utils import timezone as django_timezone

from providers.base import (
    DELAYED,
    ERROR,
    HISTORICAL,
    LIVE,
    OFFLINE,
    REPLAY,
    WAITING,
)
from providers.free_live import FreeLiveTimingProvider
from providers.jolpica import JolpicaProvider
from providers.manager import (
    SCOPE_HISTORICAL,
    SCOPE_LIVE,
    SCOPE_METADATA,
    ProviderManager,
)
from providers.openf1 import OpenF1Provider

from .models import (
    IngestionRun,
    ProviderStatus as ProviderStatusModel,
    Session,
    SessionSnapshot,
    payload_fingerprint,
)

logger = logging.getLogger("racecenter.ingest")

# Cuantas filas se conservan de las tablas de bitacora (ProviderStatus,
# IngestionRun). Son historiales de auditoria, no un archivo infinito.
HISTORY_ROWS = 500

# Cuantos snapshots EN VIVO se conservan. Cada uno pesa del orden de 90 KB,
# asi que este numero es tambien el techo practico del tamano de la base
# (~18 MB). Los historicos no se recortan: hay uno por sesion.
SNAPSHOT_ROWS = 200


def build_manager() -> ProviderManager:
    """Construye el :class:`ProviderManager` con la configuracion del entorno."""
    manager = ProviderManager(
        live_provider=settings.LIVE_PROVIDER,
        historical_provider=settings.HISTORICAL_PROVIDER,
        metadata_provider=settings.METADATA_PROVIDER,
        mode=settings.DATA_PROVIDER,
        live_max_age_seconds=settings.LIVE_MAX_AGE_SECONDS,
        delayed_max_age_seconds=settings.DELAYED_MAX_AGE_SECONDS,
    )

    manager.register(
        FreeLiveTimingProvider(
            base_url=settings.F1_LIVETIMING_URL,
            timeout=settings.INGEST_HTTP_TIMEOUT,
        )
    )
    manager.register(
        OpenF1Provider(
            base_url=settings.OPENF1_BASE_URL,
            api_key=settings.OPENF1_API_KEY,
            live_enabled=settings.OPENF1_LIVE_ENABLED,
        )
    )
    manager.register(JolpicaProvider(base_url=settings.JOLPICA_BASE_URL))
    return manager


class SnapshotBuilder:
    """Construye el payload normalizado que consume el frontend."""

    def __init__(self, manager: ProviderManager) -> None:
        self.manager = manager

    async def build(self, scope: str = SCOPE_LIVE) -> dict[str, Any]:
        session, session_provider = await self.manager.fetch("session", scope)
        timing, timing_provider = await self.manager.fetch("timing", scope)
        drivers, drivers_provider = await self.manager.fetch("drivers", scope)
        weather, weather_provider = await self.manager.fetch("weather", scope)
        race_control, race_control_provider = await self.manager.fetch("race_control", scope)
        tyres, tyres_provider = await self.manager.fetch("tyres", scope)
        positions, positions_provider = await self.manager.fetch("positions", scope)
        track_status, track_status_provider = await self.manager.fetch("track_status", scope)

        data_state = self.manager.classify_state(session)

        sources = {
            "session": session_provider,
            "timing": timing_provider,
            "drivers": drivers_provider,
            "weather": weather_provider,
            "race_control": race_control_provider,
            "tyres": tyres_provider,
            "positions": positions_provider,
            "track_status": track_status_provider,
        }

        now = datetime.now(timezone.utc)
        return {
            "generated_at": now.isoformat(),
            "data_state": data_state,
            "scope": scope,
            "session": session.as_dict() if session else None,
            "drivers": [driver.as_dict() for driver in (drivers or [])],
            "timing": [entry.as_dict() for entry in (timing or [])],
            "weather": weather.as_dict() if weather else None,
            "race_control": [event.as_dict() for event in (race_control or [])],
            "tyres": [stint.as_dict() for stint in (tyres or [])],
            "positions": list(positions or []),
            "track_status": track_status or None,
            "sources": sources,
            "provider_status": [status.as_dict() for status in self.manager.status_list()],
            "diagnostics": self.manager.diagnostics(),
        }


class Ingestor:
    """Ejecuta los ciclos de ingesta y persiste el snapshot."""

    def __init__(self, scope: str = SCOPE_LIVE) -> None:
        self.manager = build_manager()
        self.builder = SnapshotBuilder(self.manager)
        self.scope = scope
        self._backoff = 1.0
        self._failures = 0

    async def start(self) -> None:
        await self.manager.connect_all()

    async def stop(self) -> None:
        await self.manager.disconnect_all()

    async def run_once(self) -> dict[str, Any] | None:
        """Un ciclo de ingesta. Devuelve el snapshot persistido o ``None``."""
        started = datetime.now(timezone.utc)
        errors: list[str] = []

        try:
            await self.manager.refresh_status()
            payload = await self.builder.build(self.scope)

            # El ORM de Django es sincrono: desde un contexto async hay que
            # delegar las escrituras en un hilo.
            changed, session_id = await sync_to_async(self._persist_snapshot, thread_sensitive=True)(
                payload
            )

            self._backoff = 1.0
            self._failures = 0

            await sync_to_async(self._record_run, thread_sensitive=True)(
                ok=True,
                started=started,
                payload=payload,
                changed=changed,
                session_id=session_id,
                error="",
            )
            return payload

        except Exception as exc:  # pragma: no cover - defensivo
            errors.append("%s: %s" % (type(exc).__name__, exc))
            logger.exception("Fallo el ciclo de ingesta")
            self._failures += 1
            await sync_to_async(self._record_run, thread_sensitive=True)(
                ok=False,
                started=started,
                payload={},
                changed=False,
                session_id="",
                error="; ".join(errors),
            )
            return None

    def _persist_snapshot(self, payload: dict[str, Any]) -> tuple[bool, str]:
        """Escribe el snapshot solo si el contenido cambio. (sincrono)"""
        session = self._upsert_session(payload.get("session"))
        changed = False
        fingerprint = payload_fingerprint(payload)

        if session is not None:
            existing = (
                SessionSnapshot.objects.filter(session=session)
                .order_by("-created_at")
                .first()
            )
            if existing is None or existing.fingerprint != fingerprint:
                session_data = payload.get("session") or {}
                SessionSnapshot.objects.create(
                    session=session,
                    provider_id=payload["sources"].get("timing")
                    or payload["sources"].get("session")
                    or settings.LIVE_PROVIDER,
                    scope=payload.get("scope") or "live",
                    data_state=payload["data_state"],
                    fingerprint=fingerprint,
                    source_timestamp=_parse_iso(session_data.get("source_timestamp")),
                    payload=payload,
                )
                changed = True

        self._persist_provider_status()
        session_id = str((payload.get("session") or {}).get("provider_session_id") or "")
        return changed, session_id

    def _record_run(
        self,
        *,
        ok: bool,
        started: datetime,
        payload: dict[str, Any],
        changed: bool,
        session_id: str,
        error: str,
    ) -> None:
        """Guarda la bitacora del ciclo. (sincrono)"""
        finished = datetime.now(timezone.utc)
        run = IngestionRun(
            provider_id=settings.LIVE_PROVIDER,
            started_at=started,
            finished_at=finished,
            ok=ok,
            duration_ms=(finished - started).total_seconds() * 1000.0,
            entries_count=len(payload.get("timing") or []),
            changed=changed,
            data_state=payload.get("data_state") or "",
            session_id=session_id,
            error=error,
        )
        run.save()

    def _upsert_session(self, session_data: dict[str, Any] | None) -> Session | None:
        if not session_data:
            return None
        provider_id = session_data.get("provider_id") or settings.LIVE_PROVIDER
        provider_session_id = str(session_data.get("provider_session_id") or "")
        if not provider_session_id:
            return None

        session, _ = Session.objects.get_or_create(
            provider_id=provider_id,
            provider_session_id=provider_session_id,
            defaults={
                "name": session_data.get("session_name") or session_data.get("meeting_name") or "",
                "session_type": session_data.get("session_type") or "",
                "session_number": session_data.get("session_number"),
                "start_time_utc": _parse_iso(session_data.get("start_time_utc")),
                "end_time_utc": _parse_iso(session_data.get("end_time_utc")),
                "state": session_data.get("state") or "",
                "qualifying_segment": session_data.get("qualifying_segment") or "",
                "source_timestamp": _parse_iso(session_data.get("source_timestamp")),
            },
        )
        # Se refrescan los campos que pueden cambiar durante la sesion.
        session.name = session_data.get("session_name") or session.name
        session.session_type = session_data.get("session_type") or session.session_type
        session.state = session_data.get("state") or session.state
        session.start_time_utc = _parse_iso(session_data.get("start_time_utc")) or session.start_time_utc
        session.end_time_utc = _parse_iso(session_data.get("end_time_utc")) or session.end_time_utc
        session.source_timestamp = (
            _parse_iso(session_data.get("source_timestamp")) or session.source_timestamp
        )
        session.save()
        return session

    def _persist_provider_status(self) -> None:
        for status in self.manager.status_list():
            ProviderStatusModel.objects.create(
                provider_id=status.provider_id,
                name=status.name,
                endpoint=status.endpoint,
                state=status.state,
                is_connected=status.is_connected,
                last_message_at=status.last_message_at,
                data_age_seconds=status.data_age_seconds,
                latency_ms=status.latency_ms,
                last_error=status.last_error or "",
                error_count=status.error_count,
                reconnect_count=status.reconnect_count,
                capabilities=status.capabilities.as_dict() if status.capabilities else {},
            )
        # Estas tablas son bitacora, no archivo: se recorta lo viejo.
        # (No se puede hacer delete() sobre un queryset recortado: se borra
        # por PK, que es lo que Django permite.)
        trim_history()

    # -- recorte de historiales --------------------------------------------- #


def trim_history() -> None:
    """Recorta las tablas que crecen sin limite.

    ProviderStatus e IngestionRun son historiales de auditoria. Los snapshots
    **en vivo** pesan del orden de 90 KB cada uno y se escribe uno nuevo cada
    vez que cambian los datos: durante una sesion en vivo, uno cada pocos
    segundos. Sin recorte la base crece sin limite.

    Los snapshots **historicos** no se tocan: hay uno por sesion y se
    consultan a pedido, asi que son pocos y valen la pena.

    (No se puede hacer ``delete()`` sobre un queryset recortado: se borra por
    PK, que es lo que Django permite.)
    """
    stale_status = list(
        ProviderStatusModel.objects.order_by("-recorded_at")[HISTORY_ROWS:].values_list(
            "pk", flat=True
        )
    )
    if stale_status:
        ProviderStatusModel.objects.filter(pk__in=stale_status).delete()

    stale_runs = list(
        IngestionRun.objects.order_by("-started_at")[HISTORY_ROWS:].values_list("pk", flat=True)
    )
    if stale_runs:
        IngestionRun.objects.filter(pk__in=stale_runs).delete()

    stale_snapshots = list(
        SessionSnapshot.objects.filter(scope="live")
        .order_by("-created_at")[SNAPSHOT_ROWS:]
        .values_list("pk", flat=True)
    )
    if stale_snapshots:
        SessionSnapshot.objects.filter(pk__in=stale_snapshots).delete()


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def latest_snapshot() -> dict[str, Any] | None:
    """Ultimo snapshot **en vivo**, para responder rapido a la API.

    Se filtra por ``scope``: el historico se guarda en la misma tabla y, sin
    ese filtro, cargar un FP1 desde el selector dejaba su fila como la mas
    reciente y el dashboard en vivo pasaba a servir datos historicos.
    """
    snapshot = SessionSnapshot.objects.filter(scope="live").order_by("-created_at").first()
    if snapshot is None:
        return None
    payload = dict(snapshot.payload)
    payload["_snapshot_id"] = snapshot.id
    payload["_snapshot_created_at"] = snapshot.created_at.isoformat()
    payload["_session_pk"] = snapshot.session_id
    return payload


def snapshot_for_session(session_pk: int) -> dict[str, Any] | None:
    snapshot = (
        SessionSnapshot.objects.filter(session_id=session_pk)
        .order_by("-created_at")
        .first()
    )
    if snapshot is None:
        return None
    payload = dict(snapshot.payload)
    payload["_snapshot_id"] = snapshot.id
    payload["_snapshot_created_at"] = snapshot.created_at.isoformat()
    payload["_session_pk"] = snapshot.session_id
    return payload
