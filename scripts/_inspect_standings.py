#!/usr/bin/env python3
"""Inspecciona la estructura real de /api/standings para el normalizador."""
import json
import urllib.request

BASE = "http://127.0.0.1:3000"


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=10) as resp:
        return json.load(resp)


data = get("/api/standings")
lb = data.get("Leaderboard") or []
lines = data.get("Lines") or {}
print("Leaderboard:", lb)
print("total Line keys:", len(lines))
print()
kf = lines.get("_kf")
print("_kf type:", type(kf).__name__)
print("_kf value:", json.dumps(kf)[:600])
print()
if lb:
    leader = lines.get(lb[0]) or {}
    print("--- LIDER", lb[0], "claves:", sorted(leader.keys()))
    print()
    for key in (
        "RacingNumber", "FullName", "Tla", "TeamName", "TeamColour", "Position",
        "ShowPosition", "Retired", "InPit", "PitOut", "Stopped", "Status",
        "TimeDiffToFastest", "TimeDiffToPositionAhead", "GapToLeader",
        "IntervalToPositionAhead", "BestLapTime", "LastLapTime",
        "BestLapTimes", "NumberOfLaps", "NumberOfPitStops", "Sectors",
    ):
        if key in leader:
            print("  %-28s = %s" % (key, json.dumps(leader[key])[:220]))
    print()
    print("--- SECTORS estructura ---")
    for sk, sv in (leader.get("Sectors") or {}).items():
        print("  sector %s -> %s" % (sk, json.dumps(sv)[:260]))
    print()
    print("--- BestLapTimes (Q1/Q2/Q3) ---")
    print("  ", json.dumps(leader.get("BestLapTimes"))[:600])
print()
print("--- claves presentes en cada Line (union) ---")
union = set()
for v in lines.values():
    if isinstance(v, dict):
        union |= set(v.keys())
print(sorted(union))
print()
print("--- TimingData cruda: claves de primer nivel ---")
td = get("/api/leaderboard")
print(json.dumps(td, indent=1)[:1200])
