#!/usr/bin/env python3
"""Verifica el estado de InPit en el snapshot actual."""
import json
import urllib.request

with urllib.request.urlopen("http://127.0.0.1:8000/api/sessions/current/", timeout=15) as r:
    d = json.load(r)

timing = d.get("timing") or []
print("data_state:", d.get("data_state"))
print("session state:", (d.get("session") or {}).get("state"))
print("total pilotos:", len(timing))
pit = [t for t in timing if t.get("in_pit")]
print("con in_pit=True:", len(pit))
print("con pit_out=True:", len([t for t in timing if t.get("pit_out")]))
print("con stopped=True:", len([t for t in timing if t.get("stopped")]))
print("con retired=True:", len([t for t in timing if t.get("retired")]))
print("positions:", sorted([t.get("position") for t in timing if t.get("position") is not None]))
print()
print("primeros 5:")
for t in timing[:5]:
    print("  #%-3s pos=%-3s in_pit=%-5s pit_out=%-5s stopped=%-5s laps=%-3s best=%s gap=%s" % (
        t.get("driver_number"), t.get("position"), t.get("in_pit"), t.get("pit_out"),
        t.get("stopped"), t.get("number_of_laps"),
        t.get("best_lap_time_display"), t.get("time_diff_to_fastest")))
