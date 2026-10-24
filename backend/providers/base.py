"""Contratos normalizados del dominio de cronometraje.

Este modulo define:

* Las estructuras de datos **independientes del proveedor** (Session, Driver,
  TimingEntry, ...) que consume el frontend. Nunca se expone el formato crudo
  de una API externa al frontend: todo pasa por aqui.
* La interfaz abstracta :class:`TimingProvider`, que todo adaptador debe
  implementar.

Reglas del dominio aplicadas aqui:

* Todo dato normalizado lleva ``provider_id`` (de quien viene) y
  ``source_timestamp`` (cuando lo produjo la fuente). El frontend siempre puede
  saber de donde salio cada conjunto de datos.
* La ausencia de informacion se representa con ``None``. **Nunca** se convierte
  un valor ausente en ``0``, porque un ``0`` es una lectura real valida
  (vueltas, penalizaciones, temperatura) y falsearia el dashboard.
* Las capacidades no soportadas se declaran explicitamente. Un proveedor que no
  tiene telemetria no simula telemetria: lanza :class:`UnsupportedCapability`.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

# --------------------------------------------------------------------------- #
# Estados del pipeline de datos
# --------------------------------------------------------------------------- #

LIVE = "LIVE"
DELAYED = "DELAYED"
HISTORICAL = "HISTORICAL"
REPLAY = "REPLAY"
WAITING = "WAITING"
OFFLINE = "OFFLINE"
ERROR = "ERROR"

DATA_STATES = (LIVE, DELAYED, HISTORICAL, REPLAY, WAITING, OFFLINE, ERROR)


class UnsupportedCapability(Exception):
    """El proveedor no puede satisfacer la capacidad solicitada.

    El :class:`~providers.manager.ProviderManager` captura esta excepcion y
    decide si existe otro proveedor valido para esa misma capacidad. Nunca se
    rellena con datos inventados.
    """


class ProviderError(Exception):
    """Fallo de transporte o de datos de un proveedor concreto."""


class ProviderRateLimited(ProviderError):
    """El proveedor rechazo la peticion por limite de tasa.

    No es un fallo del proveedor: sigue conectado, lo que se agoto es la
    cuota por IP. Se distingue de :class:`ProviderError` para que el estado
    operativo no se marque como ERROR y para que la parte opcional de una
    respuesta pueda caerse sin perder el resto.
    """


# --------------------------------------------------------------------------- #
# Utilidades de tiempo
# --------------------------------------------------------------------------- #

_LAP_TIME_RE = re.compile(r"^\s*(?:(\d+):)?(\d{1,3})(?:\.(\d{1,6}))?\s*$")


def parse_lap_time(value: Any) -> float | None:
    """Convierte un tiempo de vuelta F1 a segundos.

    Acepta los formatos que emite el feed de cronometraje:

    * ``"1:35.706"`` -> 95.706
    * ``"1:35"``     -> 95.0
    * ``"95.706"``   -> 95.706
    * ``"95"``       -> 95.0

    Devuelve ``None`` si el valor no es utilizable. Nunca devuelve ``0.0``
    para un valor invalido, porque ``0`` es un tiempo real (o casi) valido.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    if isinstance(value, dict):
        value = value.get("Value")
        if value is None:
            return None
    text = str(value).strip()
    if not text:
        return None
    match = _LAP_TIME_RE.match(text)
    if not match:
        return None
    minutes, seconds, fraction = match.groups()
    total = float(seconds)
    if fraction:
        total += float("0." + fraction)
    if minutes:
        total += int(minutes) * 60
    return total


def format_lap_time(seconds: float | None) -> str | None:
    """Invierte :func:`parse_lap_time` al formato ``m:ss.mmm`` de la F1."""
    if seconds is None:
        return None
    if seconds <= 0:
        return None
    minutes = int(seconds // 60)
    rest = seconds - (minutes * 60)
    return "%d:%06.3f" % (minutes, rest)


def parse_timestamp(value: Any) -> datetime | None:
    """Normaliza un timestamp de proveedor a ``datetime`` con timezone UTC.

    Acepta ISO-8601 (``2026-10-24T18:58:14.771Z``), el formato compacto del
    feed de cronometraje (``2026-10-24T17:47:11``) y epoch en segundos/millis.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        seconds = float(value)
        if seconds > 1e11:  # milisegundos
            seconds /= 1000.0
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(str(value).strip(), fmt)
                break
            except ValueError:
                continue
        else:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def to_float(value: Any) -> float | None:
    """Convierte a float preservando el "sin dato" como ``None``."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def to_int(value: Any) -> int | None:
    """Convierte a int preservando el "sin dato" como ``None``."""
    number = to_float(value)
    if number is None:
        return None
    try:
        return int(number)
    except (TypeError, ValueError, OverflowError):
        return None


# --------------------------------------------------------------------------- #
# Capacidades
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ProviderCapabilities:
    """Que sabe hacer realmente un proveedor.

    Se usa para (a) elegir proveedor y (b) avisar al usuario de que una
    funcionalidad no esta disponible, en vez de fingir.
    """

    provider_id: str
    live: bool = False
    historical: bool = False
    metadata: bool = False
    timing: bool = False
    laps: bool = False
    sectors: bool = False
    tyres: bool = False
    weather: bool = False
    race_control: bool = False
    telemetry: bool = False
    positions: bool = False
    notes: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "live": self.live,
            "historical": self.historical,
            "metadata": self.metadata,
            "timing": self.timing,
            "laps": self.laps,
            "sectors": self.sectors,
            "tyres": self.tyres,
            "weather": self.weather,
            "race_control": self.race_control,
            "telemetry": self.telemetry,
            "positions": self.positions,
            "notes": self.notes,
        }


# --------------------------------------------------------------------------- #
# Entidades normalizadas
# --------------------------------------------------------------------------- #


@dataclass
class SessionInfo:
    """Sesion de campeonato normalizada."""

    provider_id: str
    provider_session_id: str
    meeting_name: str | None = None
    official_name: str | None = None
    circuit_name: str | None = None
    location: str | None = None
    country_name: str | None = None
    country_code: str | None = None
    season: str | None = None
    round_number: int | None = None
    meeting_key: int | None = None
    circuit_key: int | None = None
    session_type: str | None = None
    session_name: str | None = None
    session_number: int | None = None
    start_time_utc: datetime | None = None
    end_time_utc: datetime | None = None
    state: str | None = None
    archive_status: str | None = None
    gmt_offset: str | None = None
    # Segmento de clasificacion (Q1/Q2/Q3) si el proveedor lo expone.
    qualifying_segment: str | None = None
    source_timestamp: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "provider_session_id": self.provider_session_id,
            "meeting_name": self.meeting_name,
            "official_name": self.official_name,
            "circuit_name": self.circuit_name,
            "location": self.location,
            "country_name": self.country_name,
            "country_code": self.country_code,
            "season": self.season,
            "round_number": self.round_number,
            "meeting_key": self.meeting_key,
            "circuit_key": self.circuit_key,
            "session_type": self.session_type,
            "session_name": self.session_name,
            "session_number": self.session_number,
            "start_time_utc": _iso(self.start_time_utc),
            "end_time_utc": _iso(self.end_time_utc),
            "state": self.state,
            "archive_status": self.archive_status,
            "gmt_offset": self.gmt_offset,
            "qualifying_segment": self.qualifying_segment,
            "source_timestamp": _iso(self.source_timestamp),
        }


@dataclass
class Driver:
    """Piloto normalizado."""

    provider_id: str
    number: str
    code: str | None = None
    full_name: str | None = None
    broadcast_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    team_name: str | None = None
    team_colour: str | None = None
    country_code: str | None = None
    line: int | None = None
    headshot_url: str | None = None
    source_timestamp: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "number": self.number,
            "code": self.code,
            "full_name": self.full_name,
            "broadcast_name": self.broadcast_name,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "team_name": self.team_name,
            "team_colour": self.team_colour,
            "country_code": self.country_code,
            "line": self.line,
            "headshot_url": self.headshot_url,
            "source_timestamp": _iso(self.source_timestamp),
        }


@dataclass
class Sector:
    """Sector de una vuelta."""

    index: int
    time: float | None = None
    personal_fastest: bool = False
    overall_fastest: bool = False
    stopped: bool = False
    valid: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "time": self.time,
            "time_display": format_lap_time(self.time),
            "personal_fastest": self.personal_fastest,
            "overall_fastest": self.overall_fastest,
            "stopped": self.stopped,
            "valid": self.valid,
        }


@dataclass
class TimingEntry:
    """Fila de clasificacion normalizada."""

    provider_id: str
    driver_number: str
    driver: Driver | None = None
    position: int | None = None
    show_position: bool = True
    best_lap_time: float | None = None
    best_lap_number: int | None = None
    best_lap_overall_fastest: bool = False
    last_lap_time: float | None = None
    sectors: list[Sector] = field(default_factory=list)
    gap_to_leader: str | None = None
    interval_to_ahead: str | None = None
    time_diff_to_fastest: str | None = None
    time_diff_to_position_ahead: str | None = None
    number_of_laps: int | None = None
    number_of_pit_stops: int | None = None
    in_pit: bool = False
    pit_out: bool = False
    stopped: bool = False
    retired: bool = False
    status_code: int | None = None
    tyre_compound: str | None = None
    tyre_age: int | None = None
    tyre_new: bool | None = None
    grid_position: int | None = None
    # Mejores vueltas por segmento de clasificacion (Q1/Q2/Q3).
    best_lap_times: dict[str, float | None] = field(default_factory=dict)
    speeds: dict[str, float | None] = field(default_factory=dict)
    source_timestamp: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "driver_number": self.driver_number,
            "driver": self.driver.as_dict() if self.driver else None,
            "position": self.position,
            "show_position": self.show_position,
            "best_lap_time": self.best_lap_time,
            "best_lap_time_display": format_lap_time(self.best_lap_time),
            "best_lap_number": self.best_lap_number,
            "best_lap_overall_fastest": self.best_lap_overall_fastest,
            "last_lap_time": self.last_lap_time,
            "last_lap_time_display": format_lap_time(self.last_lap_time),
            "sectors": [s.as_dict() for s in self.sectors],
            "gap_to_leader": self.gap_to_leader,
            "interval_to_ahead": self.interval_to_ahead,
            "time_diff_to_fastest": self.time_diff_to_fastest,
            "time_diff_to_position_ahead": self.time_diff_to_position_ahead,
            "number_of_laps": self.number_of_laps,
            "number_of_pit_stops": self.number_of_pit_stops,
            "in_pit": self.in_pit,
            "pit_out": self.pit_out,
            "stopped": self.stopped,
            "retired": self.retired,
            "status_code": self.status_code,
            "tyre_compound": self.tyre_compound,
            "tyre_age": self.tyre_age,
            "tyre_new": self.tyre_new,
            "grid_position": self.grid_position,
            "best_lap_times": {
                key: {
                    "time": value,
                    "time_display": format_lap_time(value),
                }
                for key, value in self.best_lap_times.items()
            },
            "speeds": dict(self.speeds),
            "source_timestamp": _iso(self.source_timestamp),
        }


@dataclass
class Lap:
    """Vuelta normalizada."""

    provider_id: str
    driver_number: str
    lap_number: int | None = None
    lap_duration: float | None = None
    sector_1: float | None = None
    sector_2: float | None = None
    sector_3: float | None = None
    compound: str | None = None
    tyre_age_at_start: int | None = None
    is_pit_out_lap: bool | None = None
    stint_number: int | None = None
    position: int | None = None
    deleted: bool | None = None
    date: datetime | None = None
    source_timestamp: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "driver_number": self.driver_number,
            "lap_number": self.lap_number,
            "lap_duration": self.lap_duration,
            "lap_duration_display": format_lap_time(self.lap_duration),
            "sector_1": self.sector_1,
            "sector_2": self.sector_2,
            "sector_3": self.sector_3,
            "compound": self.compound,
            "tyre_age_at_start": self.tyre_age_at_start,
            "is_pit_out_lap": self.is_pit_out_lap,
            "stint_number": self.stint_number,
            "position": self.position,
            "deleted": self.deleted,
            "date": _iso(self.date),
            "source_timestamp": _iso(self.source_timestamp),
        }


@dataclass
class Stint:
    """ stint de pneumatico normalizado."""

    provider_id: str
    driver_number: str
    stint_number: int | None = None
    compound: str | None = None
    lap_start: int | None = None
    lap_end: int | None = None
    tyre_age_at_start: int | None = None
    total_laps: int | None = None
    is_new: bool | None = None
    source_timestamp: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "driver_number": self.driver_number,
            "stint_number": self.stint_number,
            "compound": self.compound,
            "lap_start": self.lap_start,
            "lap_end": self.lap_end,
            "tyre_age_at_start": self.tyre_age_at_start,
            "total_laps": self.total_laps,
            "is_new": self.is_new,
            "source_timestamp": _iso(self.source_timestamp),
        }


@dataclass
class WeatherReport:
    """Clima normalizado (lectura puntual del circuito)."""

    provider_id: str
    air_temperature: float | None = None
    track_temperature: float | None = None
    humidity: float | None = None
    pressure: float | None = None
    rainfall: float | None = None
    wind_speed: float | None = None
    wind_direction: float | None = None
    source_timestamp: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "air_temperature": self.air_temperature,
            "track_temperature": self.track_temperature,
            "humidity": self.humidity,
            "pressure": self.pressure,
            "rainfall": self.rainfall,
            "wind_speed": self.wind_speed,
            "wind_direction": self.wind_direction,
            "source_timestamp": _iso(self.source_timestamp),
        }


@dataclass
class RaceControlEvent:
    """Evento del control de carrera normalizado."""

    provider_id: str
    message: str
    category: str | None = None
    flag: str | None = None
    scope: str | None = None
    utc: datetime | None = None
    source_timestamp: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "message": self.message,
            "category": self.category,
            "flag": self.flag,
            "scope": self.scope,
            "utc": _iso(self.utc),
            "source_timestamp": _iso(self.source_timestamp),
        }


@dataclass
class TelemetrySample:
    """Muestra de telemetria normalizada."""

    provider_id: str
    driver_number: str
    timestamp: datetime | None = None
    speed: float | None = None
    rpm: float | None = None
    gear: int | None = None
    throttle: float | None = None
    brake: float | None = None
    drs: int | None = None
    x: float | None = None
    y: float | None = None
    source_timestamp: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "driver_number": self.driver_number,
            "timestamp": _iso(self.timestamp),
            "speed": self.speed,
            "rpm": self.rpm,
            "gear": self.gear,
            "throttle": self.throttle,
            "brake": self.brake,
            "drs": self.drs,
            "x": self.x,
            "y": self.y,
            "source_timestamp": _iso(self.source_timestamp),
        }


@dataclass
class ProviderStatus:
    """Estado operacional de un proveedor, para el panel de diagnostico."""

    provider_id: str
    name: str
    endpoint: str
    state: str = OFFLINE
    is_connected: bool = False
    last_message_at: datetime | None = None
    data_age_seconds: float | None = None
    latency_ms: float | None = None
    last_error: str | None = None
    error_count: int = 0
    reconnect_count: int = 0
    capabilities: ProviderCapabilities | None = None
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "name": self.name,
            "endpoint": self.endpoint,
            "state": self.state,
            "is_connected": self.is_connected,
            "last_message_at": _iso(self.last_message_at),
            "data_age_seconds": self.data_age_seconds,
            "latency_ms": self.latency_ms,
            "last_error": self.last_error,
            "error_count": self.error_count,
            "reconnect_count": self.reconnect_count,
            "capabilities": self.capabilities.as_dict() if self.capabilities else None,
            "updated_at": _iso(self.updated_at),
        }


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Interfaz de proveedor
# --------------------------------------------------------------------------- #


class TimingProvider(ABC):
    """Interfaz que todo adaptador de proveedor debe implementar.

    Los metodos pueden lanzar :class:`UnsupportedCapability` cuando el
    proveedor no puede satisfacer la funcionalidad. El
    :class:`~providers.manager.ProviderManager` se encarga de buscar otro
    proveedor *con la misma semantica* (nunca uno de otra naturaleza).
    """

    provider_id: str = "abstract"
    display_name: str = "Proveedor abstracto"
    endpoint: str = ""

    # Cadencia minima entre comprobaciones de estado, en segundos.
    #
    # 0 (por defecto) significa "en cada ciclo de ingesta". Un proveedor
    # externo con limite de tasa (OpenF1, Jolpica) declara aqui un valor
    # mayor: la comprobacion de estado es una llamada de red real, y para un
    # proveedor historico consultarlo cada 3 segundos no aporta nada y si
    # consume la cuota compartida por IP.
    health_check_interval: float = 0.0

    def __init__(self) -> None:
        self.status = ProviderStatus(
            provider_id=self.provider_id,
            name=self.display_name,
            endpoint=self.endpoint,
        )

    # -- ciclo de vida ----------------------------------------------------- #

    @abstractmethod
    async def connect(self) -> bool:
        """Establece la conexion. Devuelve ``True`` si quedo operativo."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Libera la conexion de forma ordenada."""

    @abstractmethod
    async def health_check(self) -> ProviderStatus:
        """Comprueba el estado actual y actualiza ``self.status``."""

    @abstractmethod
    async def get_capabilities(self) -> ProviderCapabilities:
        """Capacidades **reales** de este proveedor."""

    # -- datos ------------------------------------------------------------- #

    @abstractmethod
    async def get_session(self) -> SessionInfo | None:
        """Sesion actual detectada por el proveedor."""

    @abstractmethod
    async def get_drivers(self) -> list[Driver]:
        ...

    @abstractmethod
    async def get_timing(self) -> list[TimingEntry]:
        ...

    @abstractmethod
    async def get_laps(self) -> list[Lap]:
        ...

    @abstractmethod
    async def get_stints(self) -> list[Stint]:
        ...

    @abstractmethod
    async def get_tyres(self) -> list[Stint]:
        ...

    @abstractmethod
    async def get_weather(self) -> WeatherReport | None:
        ...

    @abstractmethod
    async def get_race_control(self) -> list[RaceControlEvent]:
        ...

    @abstractmethod
    async def get_telemetry(self) -> list[TelemetrySample]:
        ...

    @abstractmethod
    async def get_positions(self) -> list[dict[str, Any]]:
        ...

    async def get_track_status(self) -> dict[str, Any]:
        """Estado de la pista (banderas, safety car).

        No todos los proveedores lo tienen, asi que el comportamiento por
        defecto es declararlo no soportado en vez de devolver un estado
        inventado.
        """
        raise self._unsupported("track_status")

    # -- utilidades -------------------------------------------------------- #

    def _unsupported(self, capability: str) -> UnsupportedCapability:
        return UnsupportedCapability(
            "%s no soporta la capacidad '%s'" % (self.provider_id, capability)
        )

    def _record_error(self, error: Exception) -> None:
        self.status.last_error = "%s: %s" % (type(error).__name__, error)
        self.status.error_count += 1
        self.status.state = ERROR
        self.status.is_connected = False
        self.status.updated_at = datetime.now(timezone.utc)

    def _record_success(self, latency_ms: float | None = None) -> None:
        self.status.state = LIVE if self.status.is_connected else OFFLINE
        self.status.last_error = None
        if latency_ms is not None:
            self.status.latency_ms = latency_ms
        self.status.updated_at = datetime.now(timezone.utc)


def sort_timing_entries(entries: Iterable[TimingEntry]) -> list[TimingEntry]:
    """Ordena la clasificacion por posicion.

    Pilotos sin posicion (o sin tiempo) van al final, manteniendo un orden
    estable por numero de dorsal para que la tabla no "bailen" entre polls.
    """
    def key(entry: TimingEntry):
        if entry.position is None:
            return (1, 9999, entry.driver_number)
        return (0, entry.position, entry.driver_number)

    return sorted(entries, key=key)
