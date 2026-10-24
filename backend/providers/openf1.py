"""Adaptador de OpenF1 (historico gratuito).

Documentacion: https://openf1.org/docs/

Segun la documentacion del propio proyecto:

* "Historical data (from 2023 onwards) is free and accessible without
  authentication."
* "Real-time data requires a paid subscription."

Por eso este proveedor se declara **historico** y, por defecto, no intenta
lecturas en vivo. La habilitacion de acceso live autorizado queda preparada
mediante ``OPENF1_LIVE_ENABLED`` + una clave de API, pero **no** se activa ni
se simula: si no hay credencial valida, el proveedor no finge tener datos live.

Notas de la API que condicionan el codigo:

* Los filtros se pasan en crudo en la query string (``date_start>=2026-10-20``).
  Codificarlos rompe la busqueda.
* Filtrar por un atributo inexistente (por ejemplo ``limit``) devuelve
  ``404 {"detail": "No results found."}``, no un error de sintaxis. Por eso se
  distinguen "sin resultados" de "endpoint caido".
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger("racecenter.providers.openf1")

from .base import (
    Driver,
    ProviderCapabilities,
    ProviderError,
    ProviderRateLimited,
    ProviderStatus,
    RaceControlEvent,
    Sector,
    SessionInfo,
    Stint,
    TelemetrySample,
    TimingEntry,
    TimingProvider,
    UnsupportedCapability,
    WeatherReport,
    parse_lap_time,
    parse_timestamp,
    to_float,
    to_int,
)

# --- Limite de tasa de OpenF1 (se aplica por IP) ---------------------------- #
#
# Medido contra la API real (24/10/2026): una rafaga corta de peticiones
# agota el limite y la respuesta es **429 con la cabecera "retry-after: 60"**.
# Tres medidas, en este orden:
#
#   1. Separar cada peticion un intervalo minimo.
#   2. Respetar el "retry-after" que dicta el servidor, no un backoff propio.
#   3. Recordar el cooldown: mientras dura, no se gastan mas peticiones
#      (de otro modo se siguen quemando cuota con un 429 garantizado).
MIN_REQUEST_INTERVAL_SECONDS = 1.0
MAX_RETRY_AFTER_SECONDS = 90.0
MAX_ATTEMPTS = 3

_last_request_at = 0.0
_cooldown_until = 0.0


class OpenF1Provider(TimingProvider):
    """Proveedor historico de datos de cronometraje, vueltas, clima y control."""

    provider_id = "openf1"
    display_name = "OpenF1 (historico gratuito)"

    # OpenF1 es un proveedor externo con limite de tasa por IP. Sondearlo en
    # cada ciclo de ingesta (cada 3 s) consume cuota sin aportar nada: el
    # dato historico no cambia. Se comprueba cada 5 minutos.
    health_check_interval = 300.0

    def __init__(
        self,
        base_url: str = "https://api.openf1.org/v1",
        api_key: str | None = None,
        live_enabled: bool = False,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.endpoint = self.base_url
        self.api_key = api_key
        self.live_enabled = bool(live_enabled and api_key)
        self.timeout = timeout
        super().__init__()
        self._client: httpx.AsyncClient | None = None
        self._session_key: str | None = None

    # -- ciclo de vida ----------------------------------------------------- #

    async def connect(self) -> bool:
        headers = {"Accept": "application/json", "User-Agent": "RaceCenter/1.0"}
        if self.live_enabled and self.api_key:
            headers["Authorization"] = "Bearer %s" % self.api_key
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(self.timeout),
            headers=headers,
            follow_redirects=True,
        )
        try:
            status = await self.health_check()
        except Exception:
            status = None
        return bool(status and status.is_connected)

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self.status.is_connected = False
        self.status.state = "OFFLINE"

    async def health_check(self) -> ProviderStatus:
        started = time.perf_counter()
        year = str(datetime.now(timezone.utc).year)
        try:
            sessions = await self._get_json("/sessions", {"year": year})
        except ProviderRateLimited as exc:
            # El proveedor sigue conectado: lo que se agoto es la cuota por IP.
            # No se marca ERROR; se deja el estado anterior y se anota el motivo.
            self.status.last_error = str(exc)
            self.status.updated_at = datetime.now(timezone.utc)
            return self.status
        except ProviderError as exc:
            self.status.is_connected = False
            self.status.state = "ERROR"
            self.status.last_error = str(exc)
            self.status.updated_at = datetime.now(timezone.utc)
            raise

        latency_ms = (time.perf_counter() - started) * 1000.0
        self.status.is_connected = True
        self.status.state = "CONNECTED"
        self.status.latency_ms = round(latency_ms, 2)
        self.status.last_error = None
        self.status.updated_at = datetime.now(timezone.utc)
        self.status.capabilities = await self.get_capabilities()
        return self.status

    async def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_id=self.provider_id,
            live=self.live_enabled,
            historical=True,
            metadata=True,
            timing=True,
            laps=True,
            sectors=True,
            tyres=True,
            weather=True,
            race_control=True,
            telemetry=True,
            positions=True,
            notes=(
                "Historico gratuito desde 2023. El acceso live requiere suscripcion "
                "pagada y no esta habilitado."
                if not self.live_enabled
                else "Acceso live habilitado con credencial propia."
            ),
        )

    # -- transporte -------------------------------------------------------- #

    async def _throttle(self) -> None:
        """Respeta el intervalo minimo entre peticiones y el cooldown activo.

        Mientras hay cooldown no se emite **ninguna** peticion: preguntar
        durante el periodo que el servidor indico solo gasta cuota y recibe
        un 429 garantizado.
        """
        global _last_request_at, _cooldown_until

        now = time.monotonic()
        if now < _cooldown_until:
            remaining = _cooldown_until - now
            raise ProviderRateLimited(
                "OpenF1 esta en cooldown por limite de tasa: quedan %.0fs. "
                "El servidor indico esperar antes de volver a preguntar."
                % remaining
            )

        wait = (_last_request_at + MIN_REQUEST_INTERVAL_SECONDS) - now
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_at = time.monotonic()

    @staticmethod
    def _retry_after_seconds(response: httpx.Response) -> float | None:
        """Segundos que pide el servidor esperar (cabecera ``retry-after``)."""
        raw = response.headers.get("retry-after")
        if not raw:
            return None
        try:
            return float(str(raw).strip())
        except (TypeError, ValueError):
            return None

    async def _get_json(self, path: str, params: dict[str, str] | None = None) -> list[dict[str, Any]]:
        if self._client is None:
            await self.connect()

        query = ""
        if params:
            # Los operadores (>=/<=/...) deben ir crudos: codificarlos rompe el filtro.
            query = "?" + "&".join("%s=%s" % (key, value) for key, value in params.items())

        # OpenF1 limita la tasa por IP. Ante un 429 se espera lo que indique el
        # servidor ("retry-after") en lugar de perder el dato.
        global _cooldown_until

        last_status = 0
        for attempt in range(MAX_ATTEMPTS):
            await self._throttle()
            try:
                response = await self._client.get(path + query)
            except httpx.HTTPError as exc:
                self._record_error(exc)
                raise ProviderError("Fallo de red hacia OpenF1 %s: %s" % (path, exc)) from exc

            last_status = response.status_code
            if response.status_code != 429:
                break

            retry_after = self._retry_after_seconds(response)
            wait = retry_after if retry_after is not None else 2.0 * (attempt + 1)
            wait = min(wait, MAX_RETRY_AFTER_SECONDS)
            # Durante la espera no se vuelve a preguntar.
            _cooldown_until = time.monotonic() + wait
            logger.warning(
                "OpenF1 respondio 429 en %s: se espera %.0fs (intento %d/%d, retry-after=%s)",
                path, wait, attempt + 1, MAX_ATTEMPTS,
                "%.0fs" % retry_after if retry_after is not None else "n/d",
            )
            await asyncio.sleep(wait)

        if last_status == 404:
            # "No results found" es una respuesta valida de la API de filtrado.
            return []
        if last_status == 429:
            message = "OpenF1 respondio 429 (limite de tasa) en %s, incluso tras reintentos." % path
            self.status.last_error = message
            raise ProviderRateLimited(message)
        if last_status == 401:
            self._record_error(ProviderError("OpenF1 respondio 401 (credencial requerida o invalida)."))
            raise ProviderError(
                "OpenF1 respondio 401. Revisar la credencial de acceso live."
            )
        if last_status >= 400:
            message = "OpenF1 respondio HTTP %s en %s." % (last_status, path)
            self._record_error(ProviderError(message))
            raise ProviderError(message)

        try:
            payload = response.json()
        except ValueError as exc:
            self._record_error(exc)
            raise ProviderError("Respuesta no-JSON de OpenF1 en %s." % path) from exc

        if isinstance(payload, dict):
            return [payload]
        return payload

    # -- resolucion de sesion ---------------------------------------------- #

    async def find_session_key(
        self,
        *,
        year: int | None = None,
        meeting_key: int | None = None,
        session_type: str | None = None,
        session_key: str | int | None = None,
        latest: bool = True,
    ) -> str | None:
        """Resuelve una clave de sesion real de OpenF1."""
        if session_key is not None:
            return str(session_key)

        params: dict[str, str] = {}
        if year is not None:
            params["year"] = str(year)
        if meeting_key is not None:
            params["meeting_key"] = str(meeting_key)
        if session_type is not None:
            params["session_type"] = session_type

        sessions = await self._get_json("/sessions", params or None)
        if not sessions:
            return None

        def sort_key(item: dict[str, Any]):
            return item.get("date_start") or ""

        sessions.sort(key=sort_key)
        if latest:
            return str(sessions[-1].get("session_key"))
        return str(sessions[0].get("session_key"))

    async def get_sessions(self, **filters: Any) -> list[SessionInfo]:
        """Lista sesiones historicas (para el selector de replay)."""
        params: dict[str, str] = {}
        for key, value in filters.items():
            if value is None:
                continue
            params[key] = str(value)
        raw = await self._get_json("/sessions", params or None)
        return [self._normalise_session(item) for item in raw]

    def _normalise_session(self, raw: dict[str, Any]) -> SessionInfo:
        start = parse_timestamp(raw.get("date_start"))
        end = parse_timestamp(raw.get("date_end"))
        return SessionInfo(
            provider_id=self.provider_id,
            provider_session_id=str(raw.get("session_key")),
            meeting_name=raw.get("meeting_name"),
            official_name=raw.get("meeting_official_name"),
            circuit_name=raw.get("circuit_short_name"),
            location=raw.get("location"),
            country_name=raw.get("country_name"),
            country_code=raw.get("country_code"),
            season=str(raw.get("year")) if raw.get("year") is not None else None,
            round_number=to_int(raw.get("meeting_key")),
            meeting_key=to_int(raw.get("meeting_key")),
            circuit_key=to_int(raw.get("circuit_key")),
            session_type=raw.get("session_type"),
            session_name=raw.get("session_name"),
            session_number=to_int(raw.get("session_number")),
            start_time_utc=start,
            end_time_utc=end,
            state="Finalised",
            archive_status="Complete",
            gmt_offset=raw.get("gmt_offset"),
            source_timestamp=datetime.now(timezone.utc),
        )

    # -- datos ------------------------------------------------------------- #

    async def get_session(self, session_key: str | int | None = None) -> SessionInfo | None:
        key = str(session_key or self._session_key or "")
        if not key:
            key = await self.find_session_key() or ""
        if not key:
            return None
        self._session_key = key
        rows = await self._get_json("/sessions", {"session_key": key})
        if not rows:
            return None
        session = self._normalise_session(rows[0])
        # Enriquecer con datos del meeting (nombre del GP, pais, circuito).
        if session.meeting_key:
            meetings = await self._get_json("/meetings", {"meeting_key": str(session.meeting_key)})
            if meetings:
                meeting = meetings[0]
                session.meeting_name = meeting.get("meeting_name") or session.meeting_name
                session.official_name = meeting.get("meeting_official_name") or session.official_name
                session.location = meeting.get("location") or session.location
                session.country_name = meeting.get("country_name") or session.country_name
                session.country_code = meeting.get("country_code") or session.country_code
                session.circuit_name = meeting.get("circuit_short_name") or session.circuit_name
        return session

    async def get_drivers(self, session_key: str | int | None = None) -> list[Driver]:
        key = str(session_key or self._session_key or "")
        if not key:
            return []
        rows = await self._get_json("/drivers", {"session_key": key})
        return [self._normalise_driver(row) for row in rows]

    def _normalise_driver(self, row: dict[str, Any]) -> Driver:
        return Driver(
            provider_id=self.provider_id,
            number=str(row.get("driver_number")),
            code=row.get("name_acronym"),
            full_name=row.get("full_name"),
            broadcast_name=row.get("broadcast_name"),
            first_name=row.get("first_name"),
            last_name=row.get("last_name"),
            team_name=row.get("team_name"),
            team_colour=row.get("team_colour"),
            country_code=row.get("country_code"),
            line=to_int(row.get("grid_position")),
            headshot_url=row.get("headshot_url"),
            source_timestamp=parse_timestamp(row.get("date")),
        )

    async def get_timing(self, session_key: str | int | None = None) -> list[TimingEntry]:
        """Reconstruye la clasificacion final de una sesion historica.

        OpenF1 no expone una "clasificacion en vivo" para sesiones terminadas:
        la reconstruye desde ``session_result`` (posicion, vueltas, duracion,
        diferencia) mas la mejor vuelta de ``laps`` y la ficha de ``drivers``.
        """
        key = str(session_key or self._session_key or "")
        if not key:
            return []

        results, laps, drivers = await self._gather(
            self._get_json("/session_result", {"session_key": key}),
            self._get_json("/laps", {"session_key": key}),
            self._get_json("/drivers", {"session_key": key}),
        )

        driver_map = {
            str(row.get("driver_number")): self._normalise_driver(row)
            for row in drivers
            if row.get("driver_number") is not None
        }

        best_lap: dict[str, dict[str, Any]] = {}
        for lap in laps:
            number = str(lap.get("driver_number"))
            duration = to_float(lap.get("lap_duration"))
            if duration is None:
                continue
            current = best_lap.get(number)
            if current is None or duration < current["duration"]:
                best_lap[number] = {
                    "duration": duration,
                    "lap_number": to_int(lap.get("lap_number")),
                    "s1": to_float(lap.get("duration_sector_1")),
                    "s2": to_float(lap.get("duration_sector_2")),
                    "s3": to_float(lap.get("duration_sector_3")),
                }

        entries: list[TimingEntry] = []
        for row in results:
            number = str(row.get("driver_number"))
            best = best_lap.get(number)
            sectors: list[Sector] = []
            if best:
                for index, value in enumerate((best.get("s1"), best.get("s2"), best.get("s3"))):
                    sectors.append(Sector(index=index, time=value, personal_fastest=best is not None))

            duration = to_float(row.get("duration"))
            gap = row.get("gap_to_leader")
            gap_text = None
            if gap is not None:
                gap_value = to_float(gap)
                gap_text = "LEADER" if gap_value == 0 else "+%.3f" % gap_value

            entries.append(
                TimingEntry(
                    provider_id=self.provider_id,
                    driver_number=number,
                    driver=driver_map.get(number),
                    position=to_int(row.get("position")),
                    best_lap_time=best.get("duration") if best else None,
                    best_lap_number=best.get("lap_number") if best else None,
                    sectors=sectors,
                    gap_to_leader=gap_text,
                    number_of_laps=to_int(row.get("number_of_laps")),
                    retired=bool(row.get("dnf")) or bool(row.get("dsq")),
                    last_lap_time=None,
                    source_timestamp=datetime.now(timezone.utc),
                )
            )
        return entries

    async def _gather(self, *coroutines: Any) -> list[Any]:
        """Ejecuta varias consultas en paralelo.

        Si una falla, el error se propaga: no se devuelve una excepcion dentro
        de la lista, porque eso terminaria en un ``AttributeError`` mucho mas
        dificil de entender.
        """
        import asyncio

        return list(await asyncio.gather(*coroutines))

    async def get_laps(self, session_key: str | int | None = None) -> list:
        from .base import Lap

        key = str(session_key or self._session_key or "")
        if not key:
            return []
        rows = await self._get_json("/laps", {"session_key": key})
        return [
            Lap(
                provider_id=self.provider_id,
                driver_number=str(row.get("driver_number")),
                lap_number=to_int(row.get("lap_number")),
                lap_duration=to_float(row.get("lap_duration")),
                sector_1=to_float(row.get("duration_sector_1")),
                sector_2=to_float(row.get("duration_sector_2")),
                sector_3=to_float(row.get("duration_sector_3")),
                compound=row.get("compound"),
                tyre_age_at_start=to_int(row.get("tyre_age_at_start")),
                is_pit_out_lap=row.get("is_pit_out_lap"),
                stint_number=to_int(row.get("stint_number")),
                position=to_int(row.get("position")),
                deleted=row.get("deleted"),
                date=parse_timestamp(row.get("date_start")),
                source_timestamp=datetime.now(timezone.utc),
            )
            for row in rows
        ]

    async def get_stints(self, session_key: str | int | None = None) -> list[Stint]:
        key = str(session_key or self._session_key or "")
        if not key:
            return []
        rows = await self._get_json("/stints", {"session_key": key})
        return [
            Stint(
                provider_id=self.provider_id,
                driver_number=str(row.get("driver_number")),
                stint_number=to_int(row.get("stint_number")),
                compound=row.get("compound"),
                lap_start=to_int(row.get("lap_start")),
                lap_end=to_int(row.get("lap_end")),
                tyre_age_at_start=to_int(row.get("tyre_age_at_start")),
                source_timestamp=datetime.now(timezone.utc),
            )
            for row in rows
        ]

    async def get_tyres(self, session_key: str | int | None = None) -> list[Stint]:
        return await self.get_stints(session_key)

    async def get_weather(self, session_key: str | int | None = None) -> WeatherReport | None:
        key = str(session_key or self._session_key or "")
        if not key:
            return None
        rows = await self._get_json("/weather", {"session_key": key})
        if not rows:
            return None
        last = rows[-1]
        return WeatherReport(
            provider_id=self.provider_id,
            air_temperature=to_float(last.get("air_temperature")),
            track_temperature=to_float(last.get("track_temperature")),
            humidity=to_float(last.get("humidity")),
            pressure=to_float(last.get("pressure")),
            rainfall=to_float(last.get("rainfall")),
            wind_speed=to_float(last.get("wind_speed")),
            wind_direction=to_float(last.get("wind_direction")),
            source_timestamp=parse_timestamp(last.get("date")),
        )

    async def get_race_control(self, session_key: str | int | None = None) -> list[RaceControlEvent]:
        key = str(session_key or self._session_key or "")
        if not key:
            return []
        rows = await self._get_json("/race_control", {"session_key": key})
        events = [
            RaceControlEvent(
                provider_id=self.provider_id,
                message=str(row.get("message")),
                category=row.get("category"),
                flag=row.get("flag"),
                scope=row.get("scope"),
                utc=parse_timestamp(row.get("date")),
                source_timestamp=datetime.now(timezone.utc),
            )
            for row in rows
            if row.get("message")
        ]
        events.sort(key=lambda event: (event.utc is None, event.utc))
        return events

    async def get_telemetry(self, session_key: str | int | None = None) -> list[TelemetrySample]:
        key = str(session_key or self._session_key or "")
        if not key:
            return []
        rows = await self._get_json("/car_data", {"session_key": key})
        return [
            TelemetrySample(
                provider_id=self.provider_id,
                driver_number=str(row.get("driver_number")),
                timestamp=parse_timestamp(row.get("date")),
                speed=to_float(row.get("speed")),
                rpm=to_float(row.get("rpm")),
                gear=to_int(row.get("n_gear")),
                throttle=to_float(row.get("throttle")),
                brake=to_float(row.get("brake")),
                drs=to_int(row.get("drs")),
                x=to_float(row.get("x")),
                y=to_float(row.get("y")),
                source_timestamp=datetime.now(timezone.utc),
            )
            for row in rows
        ]

    async def get_positions(self, session_key: str | int | None = None) -> list[dict[str, Any]]:
        """Posiciones GPS: la **ultima muestra de cada piloto**.

        El endpoint ``location`` devuelve una fila por piloto e instante de
        toda la sesion (unas 80.000 filas para una hora con 22 pilotos). Para
        dibujar el mapa de un replay alcanza con donde termino cada uno, asi
        que se reduce a una fila por piloto: 22 puntos en lugar de 80.000,
        sin que el snapshot guarde basura.

        La API puede devolver valores nulos si el feed no los trae: en ese
        caso la coordenada queda en ``None`` y el mapa no dibuja el auto, en
        vez de dibujarlo en el origen (0,0).
        """
        key = str(session_key or self._session_key or "")
        if not key:
            return []
        rows = await self._get_json("/location", {"session_key": key})

        ultima: dict[str, dict[str, Any]] = {}
        for row in rows:
            numero = str(row.get("driver_number") or "")
            if not numero:
                continue
            anterior = ultima.get(numero)
            if anterior is None or self._row_time(row) >= self._row_time(anterior):
                ultima[numero] = row

        posiciones: list[dict[str, Any]] = []
        for numero, row in sorted(ultima.items(), key=lambda item: item[0]):
            momento = parse_timestamp(row.get("date"))
            posiciones.append(
                {
                    "provider_id": self.provider_id,
                    "driver_number": numero,
                    "timestamp": momento.isoformat() if momento else None,
                    "source_timestamp": momento.isoformat() if momento else None,
                    "x": to_float(row.get("x")),
                    "y": to_float(row.get("y")),
                    "z": to_float(row.get("z")),
                    "lap": to_int(row.get("lap")),
                    "number_of_laps": to_int(row.get("number_of_laps")),
                    "speed": None,
                    "gear": None,
                    "status": None,
                }
            )
        return posiciones

    @staticmethod
    def _row_time(row: dict[str, Any]) -> float:
        """Instante de una fila de `location`, para quedarse con la ultima."""
        momento = parse_timestamp(row.get("date"))
        return momento.timestamp() if momento else 0.0
