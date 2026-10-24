#!/usr/bin/env python3
"""Vista previa del trazado generado (comprobacion visual)."""
import json
import os

path = "/mnt/c/Programacion/proyectos/actives/f1-race-center/backend/core/data/track_outlines.json"
with open(path, encoding="utf-8") as fh:
    data = json.load(fh)

for key, outline in data.items():
    pts = outline["points"]
    size = outline["size"]
    poly = " ".join("%s,%s" % (p[0], p[1]) for p in pts)
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d">'
        '<rect width="%d" height="%d" fill="#05080f"/>'
        '<polyline points="%s" fill="none" stroke="#e8112d" stroke-width="6" '
        'stroke-linejoin="round" stroke-linecap="round"/>'
        "</svg>" % (size, size, size, size, size, size, poly)
    )
    out = "/tmp/track_%s.svg" % key
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(svg)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    print("circuito %s (%s): %d puntos" % (key, outline["circuit_name"], len(pts)))
    print("  x: %.0f..%.0f   y: %.0f..%.0f" % (min(xs), max(xs), min(ys), max(ys)))
    print("  svg: %s" % out)
