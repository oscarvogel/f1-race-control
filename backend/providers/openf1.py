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

# El endpoint `location` devuelve varios MB por piloto (en la FP3 de Austin
# fueron 2,3 MB y 18.418 filas por piloto), asi que necesita un timeout
# propio, bastante mas generoso que el del resto de endpoints.
LOCATION_TIMEOUT_SECONDS = 120.0

# Espera antes de la segunda pasada de las posiciones: el cooldown por
# limite de tasa ya paso y los drivers que fallaron vuelven a responder.
RETRY_PASS_DELAY_SECONDS = 5.0

_last_request_at = 0.0
_cooldown_until = 0.0

# --- Tiempos oficiales de clasificacion --------------------------------------- #
#
# En una sesion de eliminatorias (clasificacion o sprint), OpenF1 publica
# ``duration`` como **lista**: el mejor tiempo de cada segmento (Q1/Q2/Q3). En
# practicas y carreras es un escalar: el tiempo de la sesion.
#
# El tiempo que cuenta para la clasificacion es el del **ultimo segmento
# alcanzado**, no el mas rapido de todos:
#
#   * Un piloto que llego a Q3 se clasifica con su tiempo de Q3, aunque en Q2
#     haya hecho un tiempo mas rapido: ese ya no cuenta.
#   * Los eliminados en Q2 se clasifican con su tiempo de Q2, y los de Q1 con
#     su tiempo de Q1.
#
# Los eliminados van **detras** de los que llegaron mas lejos, aunque su
# tiempo sea mejor. En la clasificacion de Austin 2026, Lindblad (Q3, 1:36.049)
# quedo P9 por delante de Lawson (Q2, 1:35.058, P10): no se ordenan todos
# juntos por tiempo, se ordenan por grupo de segmento.
#
# Ademas, ``/laps`` trae tambien las vueltas que la federacion annulo (por
# ejemplo por track limits) y OpenF1 no las marca: en los datos de 2026 el
# endpoint ya no trae el campo ``deleted``. Por eso tomar la vuelta mas rapida
# de ``/laps`` daba tiempos que no existen en la clasificacion oficial (la
# mejor vuelta de Norris, 1:34.379, fue anulada y su tiempo valido de Q3 es
# 1:35.049).
#
# La fuente del tiempo de clasificacion es, entonces, ``/session_result``.
LAP_MATCH_TOLERANCE = 0.002


def _official_times(row: dict[str, Any]) -> list[float | None]:
    """Los tiempos de un piloto tal como los publica ``/session_result``.

    En una eliminatoria es una lista (Q1/Q2/Q3); en el resto de sesiones, un
    escalar. Si no hay dato, devuelve una lista vacia.
    """
    duracion = row.get("duration")
    if isinstance(duracion, list):
        return [to_float(valor) for valor in duracion]
    valor = to_float(duracion)
    return [] if valor is None else [valor]


def _classification_time(tiempos: list[float | None]) -> float | None:
    """El tiempo que cuenta para la clasificacion: el del ultimo segmento."""
    for valor in reversed(tiempos):
        if valor is not None:
            return valor
    return None


def _classification_gap(gap: Any) -> float | None:
    """La diferencia con el lider en el segmento que cuenta.

    En una eliminatoria ``gap_to_leader`` tambien viene como lista (una por
    segmento). Cuenta la del ultimo segmento alcanzado, como los tiempos.
    """
    if isinstance(gap, list):
        for valor in reversed(gap):
            resultado = to_float(valor)
            if resultado is not None:
                return resultado
        return None
    return to_float(gap)


def _same_time(a: float | None, b: float | None) -> bool:
    """Si dos tiempos son el mismo, tolerando el redondeo."""
    if a is None or b is None:
        return False
    return abs(a - b) <= LAP_MATCH_TOLERANCE


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
            # OJO: el turno se reserva **antes** de esperar.
            #
            # Con las peticiones en paralelo (las posiciones se piden piloto
            # por piloto, 22 a la vez), todas calculaban el mismo hueco: leian
            # el mismo `_last_request_at`, dormian lo mismo y salian todas a la
            # vez. OpenF1 respondia 429 y solo 4 de 22 pilotos tenían
            # posición.
            #
            # Entre la lectura y esta escritura no hay ningun `await`, asi que
            # en asyncio la reserva es atomica: cada petición se lleva su
            # turno y sale espaciada 1 s de la anterior.
            _last_request_at = now + wait
            await asyncio.sleep(wait)
        else:
            _last_request_at = now

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

    async def _get_json(
        self,
        path: str,
        params: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> list[dict[str, Any]]:
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
                # Endpoint `location`: son varios MB por piloto, asi que
                # necesita un timeout mayor que el resto.
                if timeout is None:
                    response = await self._client.get(path + query)
                else:
                    response = await self._client.get(path + query, timeout=timeout)
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

        laps_por_piloto: dict[str, list[dict[str, Any]]] = {}
        for lap in laps:
            laps_por_piloto.setdefault(str(lap.get("driver_number")), []).append(lap)

        # Tiempos oficiales: los publica /session_result y son los que cuentan
        # para la clasificacion (ver la nota de `_official_times`).
        oficiales: dict[str, dict[str, Any]] = {}
        for row in results:
            numero = str(row.get("driver_number"))
            tiempos = _official_times(row)
            oficiales[numero] = {
                "time": _classification_time(tiempos),
                "times": tiempos,
                "gap": _classification_gap(row.get("gap_to_leader")),
                # Solo una eliminatoria tiene segmentos (Q1/Q2/Q3). En practicas
                # y carreras `duration` es un escalar y no hay nada que
                # etiquetar: llamarle "Q1" a la mejor vuelta seria inventar.
                "knockout": isinstance(row.get("duration"), list),
            }

        def elegir_vuelta(numero: str) -> tuple[float | None, int | None, list[float | None]]:
            """La vuelta que cuenta para la clasificacion de un piloto.

            Primero el tiempo oficial de ``/session_result``; los sectores se
            toman de la vuelta de ``/laps`` que tiene ese tiempo exacto. Si no
            hay tiempo oficial, se usa la vuelta mas rapida registrada.
            """
            filas = laps_por_piloto.get(numero) or []
            oficial = (oficiales.get(numero) or {}).get("time")
            if oficial is not None:
                iguales = [
                    fila for fila in filas
                    if _same_time(to_float(fila.get("lap_duration")), oficial)
                ]
                if not iguales:
                    # El tiempo oficial se conoce, pero su vuelta no esta en
                    # /laps: se muestra el tiempo y los sectores quedan vacios.
                    # Nunca se inventa un desglose.
                    return oficial, None, []
                fila = min(iguales, key=lambda f: to_int(f.get("lap_number")) or 0)
                return (
                    oficial,
                    to_int(fila.get("lap_number")),
                    [
                        to_float(fila.get("duration_sector_1")),
                        to_float(fila.get("duration_sector_2")),
                        to_float(fila.get("duration_sector_3")),
                    ],
                )

            candidatas = [f for f in filas if to_float(f.get("lap_duration")) is not None]
            if not candidatas:
                return None, None, []
            fila = min(candidatas, key=lambda f: to_float(f.get("lap_duration")))
            return (
                to_float(fila.get("lap_duration")),
                to_int(fila.get("lap_number")),
                [
                    to_float(fila.get("duration_sector_1")),
                    to_float(fila.get("duration_sector_2")),
                    to_float(fila.get("duration_sector_3")),
                ],
            )

        entries: list[TimingEntry] = []
        for row in results:
            number = str(row.get("driver_number"))
            oficial = oficiales.get(number) or {}
            best_time, best_lap_number, tiempos_sector = elegir_vuelta(number)
            sectors: list[Sector] = []
            for index, value in enumerate(tiempos_sector):
                sectors.append(Sector(index=index, time=value, personal_fastest=True))

            gap_value = oficial.get("gap")
            gap_text = None
            # Ojo: en la clasificacion de Austin 2026, OpenF1 devolvio
            # "gap_to_leader" vacio o nulo para varios pilotos. Sin este
            # chequeo, `"+%.3f" % None` revienta con "must be real number,
            # not NoneType" y el snapshot historico entero se cae.
            # Sin dato, no hay gap: queda None (se dibuja "—"), nunca 0.
            if gap_value is not None:
                gap_text = "LEADER" if gap_value == 0 else "+%.3f" % gap_value

            # Mejores vueltas por segmento (Q1/Q2/Q3), igual que las publica
            # el feed en vivo: asi la columna se puede etiquetar con el
            # segmento del que viene.
            tiempos_oficiales = oficial.get("times") or []
            best_lap_times: dict[str, float | None] = {}
            if oficial.get("knockout"):
                for indice, nombre in enumerate(("Q1", "Q2", "Q3")):
                    if indice < len(tiempos_oficiales):
                        best_lap_times[nombre] = tiempos_oficiales[indice]

            entries.append(
                TimingEntry(
                    provider_id=self.provider_id,
                    driver_number=number,
                    driver=driver_map.get(number),
                    position=to_int(row.get("position")),
                    best_lap_time=best_time,
                    best_lap_number=best_lap_number,
                    best_lap_times=best_lap_times,
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
        toda la sesion. Para la FP3 de Austin fueron 18.418 filas **por
        piloto** (unos 2,3 MB), y sin filtro son ~50 MB por sesion: una
        descarga de ese peso es lenta y fragile (el timeout normal de 30 s
        no alcanza).

        Por eso se consulta **piloto por piloto, en paralelo**: son 2,3 MB
        por pedido, el limitador de tasa ya espacia los inicios un segundo
        entre si, y un piloto que falle no tira abajo a los demas.

        Para dibujar el mapa alcanza con donde termino cada auto, asi que
        de cada piloto se conserva solo la ultima muestra: 22 puntos en
        lugar de 400.000.
        """
        key = str(session_key or self._session_key or "")
        if not key:
            return []

        try:
            conductores = await self._get_json("/drivers", {"session_key": key})
        except ProviderError:
            # Sin la lista de pilotos no se puede pedir uno por uno.
            conductores = []

        numeros: list[str] = []
        for fila in conductores or []:
            numero = str(fila.get("driver_number") or "")
            if numero and numero not in numeros:
                numeros.append(numero)

        if not numeros:
            # Fallback: una sola consulta de toda la sesion. Es mas pesada,
            # pero mejor que quedarse sin posiciones.
            filas = await self._get_json("/location", {"session_key": key}, timeout=LOCATION_TIMEOUT_SECONDS)
            numeros = []
        else:
            respuestas = await asyncio.gather(
                *(
                    self._get_json(
                        "/location",
                        {"session_key": key, "driver_number": numero},
                        timeout=LOCATION_TIMEOUT_SECONDS,
                    )
                    for numero in numeros
                ),
                return_exceptions=True,
            )
            filas = []
            fallidos: list[str] = []
            for numero, respuesta in zip(numeros, respuestas):
                if isinstance(respuesta, Exception):
                    # Un piloto que falla no debe tirar abajo a los demas.
                    logger.warning("OpenF1: sin posiciones para el piloto %s: %s", numero, respuesta)
                    fallidos.append(numero)
                    continue
                for fila in respuesta or []:
                    fila = dict(fila)
                    fila.setdefault("driver_number", numero)
                    filas.append(fila)

            # Segunda pasada para los que se quedaron fuera: la primera suele
            # chocar con el limite de tasa (429) y, con el cooldown ya
            # expirado, estos drivers vuelven a responder.
            if fallidos:
                logger.info("OpenF1: reintentando las posiciones de %d pilotos", len(fallidos))
                await asyncio.sleep(RETRY_PASS_DELAY_SECONDS)
                for numero in fallidos:
                    try:
                        respuesta = await self._get_json(
                            "/location",
                            {"session_key": key, "driver_number": numero},
                            timeout=LOCATION_TIMEOUT_SECONDS,
                        )
                    except Exception as exc:
                        logger.warning(
                            "OpenF1: sin posiciones para el piloto %s (2a pasada): %s",
                            numero,
                            exc,
                        )
                        continue
                    for fila in respuesta or []:
                        fila = dict(fila)
                        fila.setdefault("driver_number", numero)
                        filas.append(fila)

        ultima: dict[str, dict[str, Any]] = {}
        for fila in filas:
            numero = str(fila.get("driver_number") or "")
            if not numero:
                continue
            anterior = ultima.get(numero)
            if anterior is None or self._row_time(fila) >= self._row_time(anterior):
                ultima[numero] = fila

        posiciones: list[dict[str, Any]] = []
        for numero, fila in sorted(ultima.items(), key=lambda item: item[0]):
            momento = parse_timestamp(fila.get("date"))
            posiciones.append(
                {
                    "provider_id": self.provider_id,
                    "driver_number": numero,
                    "timestamp": momento.isoformat() if momento else None,
                    "source_timestamp": momento.isoformat() if momento else None,
                    "x": to_float(fila.get("x")),
                    "y": to_float(fila.get("y")),
                    "z": to_float(fila.get("z")),
                    "lap": to_int(fila.get("lap")),
                    "number_of_laps": to_int(fila.get("number_of_laps")),
                    "speed": None,
                    "gear": None,
                    "status": None,
                }
            )
        return posiciones

    async def get_best_laps(self, session_key: str | int | None = None) -> list[dict[str, Any]]:
        """Mejor vuelta de cada piloto, con los tiempos por sector.

        Es lo que hace posible el **analisis por sectores**: el feed en vivo
        solo publica los sectores de la *ultima* vuelta de cada piloto (y no
        suman su mejor vuelta), asi que no sirven para comparar. En cambio
        ``/laps`` trae el desglose de cada vuelta, y los sectores de la mejor
        vuelta **suman exactamente** el tiempo de esa vuelta.

        Se agrega el compuesto del stint en el que se hizo esa vuelta (de
        ``/stints``), para poder decir con que neumatico se hizo el mejor
        tiempo.

        La vuelta que se muestra es la que **cuenta para la clasificacion**:
        el tiempo oficial de ``/session_result`` y la vuelta de ``/laps`` que
        lo tiene. No se usa la vuelta mas rapida de ``/laps`` porque ahi estan
        tambien las vueltas anuladas por la federacion (OpenF1 ya no las
        marca con ``deleted``), que no existen en la clasificacion oficial.
        """
        key = str(session_key or self._session_key or "")
        if not key:
            return []

        filas = await self._get_json("/laps", {"session_key": key})
        laps_por_piloto: dict[str, list[dict[str, Any]]] = {}
        for fila in filas or []:
            duracion = fila.get("lap_duration")
            if not duracion:
                continue
            numero = str(fila.get("driver_number") or "")
            if not numero:
                continue
            laps_por_piloto.setdefault(numero, []).append(fila)

        # Tiempo oficial de clasificacion de cada piloto: el del ultimo
        # segmento alcanzado (ver `_official_times`).
        oficiales: dict[str, float] = {}
        try:
            resultados = await self._get_json("/session_result", {"session_key": key})
        except ProviderError:
            resultados = []
        for fila in resultados or []:
            numero = str(fila.get("driver_number") or "")
            if not numero:
                continue
            tiempo = _classification_time(_official_times(fila))
            if tiempo is not None:
                oficiales[numero] = tiempo

        mejores: dict[str, dict[str, Any]] = {}
        for numero, laps in laps_por_piloto.items():
            oficial = oficiales.get(numero)
            if oficial is not None:
                iguales = [
                    f for f in laps
                    if _same_time(to_float(f.get("lap_duration")), oficial)
                ]
                if not iguales:
                    # El tiempo oficial se conoce pero su vuelta no esta en
                    # /laps: se muestra el tiempo y los sectores quedan vacios.
                    mejores[numero] = {"lap_duration": oficial, "lap_number": None}
                    continue
                mejores[numero] = min(iguales, key=lambda f: to_int(f.get("lap_number")) or 0)
                continue
            validas = [f for f in laps if to_float(f.get("lap_duration")) is not None]
            if validas:
                mejores[numero] = min(validas, key=lambda f: to_float(f.get("lap_duration")))

        if not mejores:
            return []

        # Compuesto de cada stint, para ubicar la vuelta en el stint.
        stints: list[dict[str, Any]] = []
        try:
            stints = await self._get_json("/stints", {"session_key": key})
        except ProviderError:
            stints = []

        salida: list[dict[str, Any]] = []
        for numero, fila in mejores.items():
            vuelta = int(fila.get("lap_number") or 0)
            compuesto = None
            edad = None
            edad_inicio = None
            inicio_stint = None
            for stint in stints or []:
                if str(stint.get("driver_number") or "") != numero:
                    continue
                inicio = int(stint.get("lap_start") or 0)
                fin = int(stint.get("lap_end") or 0)
                if inicio <= vuelta <= (fin or inicio):
                    compuesto = stint.get("compound")
                    edad_inicio = to_int(stint.get("tyre_age_at_start"))
                    inicio_stint = inicio
                    # La edad del neumático en ESTA vuelta: la del comienzo del
                    # stint mas las vueltas que se le、趣味amente asi.
                    # ``tyre_age_at_start`` es la de cuando se pondio el
                    # neumatico: con eso sola, la mejor vuelta de la Q3
                    # pareceria recien estrenado.
                    edad = (
                        (edad_inicio or 0) + max(0, vuelta - inicio)
                        if edad_inicio is not None
                        else None
                    )
                    break

            salida.append(
                {
                    "driver_number": numero,
                    "lap_number": vuelta,
                    "lap_time": to_float(fila.get("lap_duration")),
                    "sector_1": to_float(fila.get("duration_sector_1")),
                    "sector_2": to_float(fila.get("duration_sector_2")),
                    "sector_3": to_float(fila.get("duration_sector_3")),
                    "compound": compuesto,
                    "tyre_age": edad,
                    "tyre_age_at_start": edad_inicio,
                    "stint_lap_start": inicio_stint,
                    "is_pit_out_lap": bool(fila.get("is_pit_out_lap")),
                    "i1_speed": to_float(fila.get("i1_speed")),
                    "i2_speed": to_float(fila.get("i2_speed")),
                }
            )
        salida.sort(key=lambda item: (item.get("lap_time") is None, item.get("lap_time") or 0))
        return salida

    @staticmethod
    def _row_time(row: dict[str, Any]) -> float:
        """Instante de una fila de `location`, para quedarse con la ultima."""
        momento = parse_timestamp(row.get("date"))
        return momento.timestamp() if momento else 0.0
