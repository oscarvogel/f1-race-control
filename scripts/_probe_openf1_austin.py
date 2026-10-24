#!/usr/bin/env python3
"""Mapea las sesiones de Austin 2026 en OpenF1."""
import json
import urllib.parse
import urllib.request

BASE = "https://api.openf1.org/v1"


def get(path, **params):
    if params:
        path = path + "?" + urllib.parse.urlencode(params, safe=">=<")
    req = urllib.request.Request(path, headers={"User-Agent": "RaceCenter/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


sessions = get(BASE + "/sessions", meeting_key=1297)
print("### SESIONES DE AUSTIN 2026 (meeting_key=1297) ###")
print("%-8s %-12s %-12s %-22s %-22s" % ("key", "tipo", "nombre", "inicio UTC", "fin UTC"))
for s in sorted(sessions, key=lambda x: x.get("date_start") or ""):
    print("%-8s %-12s %-12s %-22s %-22s" % (
        s.get("session_key"), s.get("session_type"), s.get("session_name"),
        s.get("date_start"), s.get("date_end")))

print()
print("### MEETING 1297 ###")
m = get(BASE + "/meetings", meeting_key=1297)
if m:
    mm = m[0]
    for key in ("meeting_key", "meeting_name", "meeting_official_name", "location",
                "country_name", "country_code", "circuit_key", "circuit_short_name",
                "season", "year", "meeting_start_date"):
        if key in mm:
            print("  %-24s = %s" % (key, mm[key]))

print()
print("### HAY DATOS DE LAS SESIONES? ###")
for s in sorted(sessions, key=lambda x: x.get("date_start") or ""):
    key = s.get("session_key")
    for ep in ("drivers", "laps", "session_result"):
        try:
            data = get(BASE + "/" + ep, session_key=key)
            n = len(data)
        except Exception as exc:
            n = "ERR %s" % exc
        print("  %-8s %-16s %s" % (key, ep, n))

print()
print("### ULTIMAS SESIONES (para replay) ###")
recent = get(BASE + "/sessions", date_start=">=2026-10-01")
for s in sorted(recent, key=lambda x: x.get("date_start") or "")[-12:]:
    print("  %-8s %-12s %-14s %-22s %s" % (
        s.get("session_key"), s.get("session_type"), s.get("circuit_short_name"),
        s.get("date_start"), s.get("meeting_key")))
