#!/usr/bin/env python3
"""Diagnostico del proveedor historico."""
import asyncio
import os
import sys

sys.path.insert(0, "/mnt/c/Programacion/proyectos/actives/f1-race-center/backend")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from providers.openf1 import OpenF1Provider
from providers.free_live import FreeLiveTimingProvider


async def main():
    print("=== OPENF1 ===")
    p = OpenF1Provider()
    ok = await p.connect()
    print("connect:", ok)
    try:
        rows = await p._get_json("/sessions", {"session_key": "11389"})
        print("rows /sessions?session_key=11389 ->", len(rows))
        if rows:
            print("  ejemplo:", {k: rows[0].get(k) for k in ("session_key", "session_type", "session_name", "meeting_key", "circuit_short_name")})
        s = await p.get_session("11389")
        print("get_session ->", (s.provider_session_id, s.session_name, s.meeting_name) if s else None)
    except Exception as exc:
        print("ERROR:", type(exc).__name__, exc)

    print()
    print("=== LIVE ===")
    live = FreeLiveTimingProvider()
    ok2 = await live.connect()
    print("connect:", ok2, "status:", live.status.state, "err:", live.status.last_error)
    try:
        s2 = await live.get_session()
        print("get_session ->", (s2.provider_session_id, s2.session_name) if s2 else None)
    except Exception as exc:
        print("ERROR:", type(exc).__name__, exc)


asyncio.run(main())
