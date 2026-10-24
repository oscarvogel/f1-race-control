"""Trazados de circuitos.

El trazado de cada circuito **no** es un dibujo inventado: se deriva de las
posiciones GPS que los propios autos registraron en sesiones reales
(endpoint ``location`` de OpenF1). Ver el comando de gestion
``build_track_outline``.

El archivo se cachea en memoria porque no cambia durante la sesion.
"""

from __future__ import annotations

import json
import os
from typing import Any

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OUTLINE_FILE = os.path.join(DATA_DIR, "track_outlines.json")

_cache: dict[str, Any] | None = None


def load_outlines() -> dict[str, Any]:
    """Carga (y cachea) el catalogo de trazados."""
    global _cache
    if _cache is None:
        try:
            with open(OUTLINE_FILE, "r", encoding="utf-8") as fh:
                _cache = json.load(fh)
        except (OSError, ValueError):
            _cache = {}
    return _cache


def get_outline(circuit_key: str | int) -> dict[str, Any] | None:
    """Trazado de un circuito por su clave."""
    return load_outlines().get(str(circuit_key))


def outline_catalog() -> list[dict[str, Any]]:
    """Resumen de los circuitos disponibles (sin los puntos)."""
    catalog = []
    for key, outline in load_outlines().items():
        catalog.append(
            {
                "circuit_key": outline.get("circuit_key", key),
                "circuit_name": outline.get("circuit_name"),
                "source_session_key": outline.get("source_session_key"),
                "source_driver": outline.get("source_driver"),
                "source": outline.get("source"),
                "point_count": outline.get("point_count"),
                "size": outline.get("size", 1000),
            }
        )
    return catalog
