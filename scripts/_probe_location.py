#!/usr/bin/env python3
"""Comprueba si el feed trae coordenadas GPS reales (Austin 2026)."""
import json
import urllib.request

BASE = "https://api.openf1.org/v1"


def get(path, **params):
    if params:
        path += "?" + "&".join("%s=%s" % (k, v) for k, v in params.items())
    req = urllib.request.Request(path, headers={"User-Agent": "RaceCenter/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


for key, name in ((11389, "Practice 1"), (11391, "Practice 3")):
    print("### session_key=%s (%s) ###" % (key, name))
    try:
        rows = get(BASE + "/location", session_key=key)
    except Exception as exc:
        print("  ERROR:", exc)
        continue
    if not rows:
        print("  sin datos")
        continue
    print("  muestras:", len(rows))
    print("  primeras 3:", json.dumps(rows[:3]))
    # Variacion de coordenadas por piloto
    per_driver = {}
    for r in rows:
        d = str(r.get("driver_number"))
        per_driver.setdefault(d, []).append((r.get("x"), r.get("y"), r.get("z")))
    nonzero = {d: v for d, v in per_driver.items() if any(p[0] or p[1] for p in v)}
    print("  pilotos con coordenadas no nulas: %d de %d" % (len(nonzero), len(per_driver)))
    for d, pts in list(nonzero.items())[:3]:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        print("    #%s  x:[%s..%s] y:[%s..%s]  (variacion x=%s y=%s)" % (
            d, min(xs), max(xs), min(ys), max(ys), max(xs) - min(xs), max(ys) - min(ys)))
    print()

print("### car_data (telemetria) de P3 ###")
try:
    cd = get(BASE + "/car_data", session_key=11391)
    print("  muestras:", len(cd))
    print("  ejemplo:", json.dumps(cd[0]) if cd else "vacio")
except Exception as exc:
    print("  ERROR:", exc)
