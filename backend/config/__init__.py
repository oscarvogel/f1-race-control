"""Configuracion del proyecto Django de Race Center.

Los proveedores se crean de forma **perezosa**: importarlos aqui cargaria los
modelos de Django antes de ``django.setup()`` y fallaria.
"""

from __future__ import annotations

from typing import Any

_manager: Any = None


def get_manager():
    """Devuelve el :class:`ProviderManager` compartido del proceso web."""
    global _manager
    if _manager is None:
        from core.ingest import build_manager

        _manager = build_manager()
    return _manager
