"""Genera el trazado de un circuito a partir de posiciones GPS reales.

El trazado no es un dibujo inventado: se deriva de las posiciones que los
propios autos registraron en una sesion real (endpoint ``location`` de
OpenF1). Se toma una vuelta completa de un piloto y se simplifica con
Ramer-Douglas-Peucker.

Uso:

    python manage.py build_track_outline --meeting-key 1297 --driver 44
    python manage.py build_track_outline --session-key 11389 --driver 44
"""

from __future__ import annotations

import json
import math
import os
import urllib.request
from typing import Any

from django.core.management.base import BaseCommand

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data")
OUTLINE_FILE = os.path.join(DATA_DIR, "track_outlines.json")

OPENF1_BASE = os.environ.get("OPENF1_BASE_URL", "https://api.openf1.org/v1").rstrip("/")


def _get(path: str, **params: Any) -> list[dict[str, Any]]:
    query = "&".join("%s=%s" % (key, value) for key, value in params.items() if value is not None)
    url = "%s/%s%s" % (OPENF1_BASE, path, ("?" + query) if query else "")
    request = urllib.request.Request(url, headers={"User-Agent": "RaceCenter/1.0"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)


def _rdp(points: list[tuple[float, float]], epsilon: float) -> list[tuple[float, float]]:
    """Ramer-Douglas-Peucker: simplifica una polilinea."""
    if len(points) < 3:
        return list(points)

    start, end = points[0], points[-1]
    dx, dy = end[0] - start[0], end[1] - start[1]
    norm = math.hypot(dx, dy)
    max_distance = 0.0
    index = 0

    for i in range(1, len(points) - 1):
        px, py = points[i]
        if norm == 0:
            distance = math.hypot(px - start[0], py - start[1])
        else:
            distance = abs(dy * px - dx * py + end[0] * start[1] - end[1] * start[0]) / norm
        if distance > max_distance:
            max_distance = distance
            index = i

    if max_distance > epsilon:
        left = _rdp(points[: index + 1], epsilon)
        right = _rdp(points[index:], epsilon)
        return left[:-1] + right
    return [start, end]


def _parse_time(value: str) -> float:
    try:
        from datetime import datetime

        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _pick_lap(
    points: list[dict[str, Any]],
    min_seconds: float = 45.0,
    max_seconds: float = 140.0,
    close_distance: float = 120.0,
) -> list[tuple[float, float]]:
    """Elige un segmento cerrado: una vuelta de verdad.

    Una ventana de tiempo fija no sirve: puede empezar en la salida de boxes y
    terminar en la entrada a boxes, y el resultado no cierra. Lo que se busca
    es un tramo que **vuelva al mismo punto**: se recorren los puntos hacia
    adelante hasta encontrar uno que este cerca del inicio y con una duracion
    plausible de vuelta.
    """
    if not points:
        return []

    ordered = sorted(points, key=lambda p: _parse_time(p.get("date")))
    coords = [(float(p.get("x") or 0.0), float(p.get("y") or 0.0)) for p in ordered]
    times = [_parse_time(p.get("date")) for p in ordered]

    best: list[tuple[float, float]] = []
    # Se prueba un inicio cada ~2 s: son ~90 vueltas posibles en una sesion.
    step = max(1, len(coords) // 120)
    for i in range(0, len(coords) - 2, step):
        x0, y0 = coords[i]
        t0 = times[i]
        for j in range(i + 2, len(coords)):
            elapsed = times[j] - t0
            if elapsed < min_seconds:
                continue
            if elapsed > max_seconds:
                break
            xj, yj = coords[j]
            if math.hypot(xj - x0, yj - y0) <= close_distance:
                segment = coords[i : j + 1]
                if len(segment) > len(best):
                    best = segment
                break

    if len(best) < 20:
        # Fallback: ventana de tiempo generica.
        start = times[0]
        window = [p for p in ordered if start <= _parse_time(p.get("date")) <= start + 100.0]
        best = [(float(p.get("x") or 0.0), float(p.get("y") or 0.0)) for p in window]
    return best


def _normalise(points: list[tuple[float, float]], size: int = 1000.0) -> dict[str, Any]:
    """Escala a un lienzo 0..size conservando la proporcion."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    width = (max_x - min_x) or 1.0
    height = (max_y - min_y) or 1.0
    scale = size / max(width, height)
    offset_x = (size - width * scale) / 2.0
    offset_y = (size - height * scale) / 2.0
    return {
        # El eje Y del SVG crece hacia abajo: se invierte.
        "points": [
            [round((x - min_x) * scale + offset_x, 2), round(size - ((y - min_y) * scale + offset_y), 2)]
            for x, y in points
        ],
        "bounds": {"min_x": min_x, "max_x": max_x, "min_y": min_y, "max_y": max_y},
        "size": size,
    }


class Command(BaseCommand):
    help = "Genera el trazado del circuito a partir de posiciones GPS reales."

    def add_arguments(self, parser):
        parser.add_argument("--session-key", type=int, default=None)
        parser.add_argument("--meeting-key", type=int, default=1297)
        parser.add_argument("--driver", type=int, default=44)
        parser.add_argument("--circuit-key", type=int, default=9)
        parser.add_argument("--circuit-name", default="Austin")
        parser.add_argument("--epsilon", type=float, default=45.0)
        parser.add_argument("--lap-seconds", type=float, default=100.0)

    def handle(self, *args, **options):
        meeting_key = options["meeting_key"]
        driver = options["driver"]
        session_key = options["session_key"]

        if session_key is None:
            sessions = _get("sessions", meeting_key=meeting_key)
            sessions = sorted(sessions, key=lambda s: s.get("date_start") or "")
            candidates = []
            for session in sessions:
                key = session.get("session_key")
                try:
                    sample = _get("location", session_key=key, driver_number=driver)
                except Exception:
                    continue
                if sample:
                    candidates.append((key, len(sample)))
            if not candidates:
                self.stderr.write(self.style.ERROR("Ninguna sesion del meeting tiene datos de posicion."))
                return
            session_key = candidates[0][0]
            self.stdout.write("Sesion con datos de posicion: %s" % session_key)

        self.stdout.write("Descargando posiciones de la sesion %s (piloto %s)..." % (session_key, driver))
        try:
            rows = _get("location", session_key=session_key, driver_number=driver)
        except Exception as exc:
            self.stderr.write(self.style.ERROR("No se pudieron descargar las posiciones: %s" % exc))
            return

        if not rows:
            self.stderr.write(self.style.ERROR("La sesion %s no tiene posiciones." % session_key))
            return

        lap = _pick_lap(rows, options["lap_seconds"])
        simplified = _rdp(lap, options["epsilon"])
        if len(simplified) > 3:
            simplified.append(simplified[0])  # cerrar el circuito
        outline = _normalise(simplified)

        data: dict[str, Any] = {}
        if os.path.exists(OUTLINE_FILE):
            with open(OUTLINE_FILE, "r", encoding="utf-8") as fh:
                data = json.load(fh)

        data[str(options["circuit_key"])] = {
            "circuit_key": options["circuit_key"],
            "circuit_name": options["circuit_name"],
            "source_session_key": session_key,
            "source_driver": driver,
            "source": "OpenF1 /location (posiciones GPS reales)",
            "point_count": len(outline["points"]),
            "points": outline["points"],
            "bounds": outline["bounds"],
            "size": outline["size"],
        }

        os.makedirs(DATA_DIR, exist_ok=True)
        with open(OUTLINE_FILE, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)

        self.stdout.write(
            self.style.SUCCESS(
                "Trazado de %s guardado: %d puntos (circuito %s)"
                % (options["circuit_name"], len(outline["points"]), options["circuit_key"])
            )
        )
