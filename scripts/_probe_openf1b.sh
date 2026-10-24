#!/usr/bin/env bash
t() { printf "%-62s " "$1"; curl -s -o /tmp/o.json -w "%{http_code}" --max-time 25 "$2"; printf "  "; head -c 220 /tmp/o.json; echo ""; }

echo "### SESIONES ###"
t "sessions (sin filtro)"            'https://api.openf1.org/v1/sessions'
t "sessions?year=2026"               'https://api.openf1.org/v1/sessions?year=2026'
t "sessions?year=2025"               'https://api.openf1.org/v1/sessions?year=2025'
t "sessions?year=2024"               'https://api.openf1.org/v1/sessions?year=2024'
t "sessions?session_key=9159"        'https://api.openf1.org/v1/sessions?session_key=9159'
t "sessions?date_start>=2026-10-20"  'https://api.openf1.org/v1/sessions?date_start>=2026-10-20'

echo ""
echo "### MEETINGS ###"
t "meetings (sin filtro)"             'https://api.openf1.org/v1/meetings'
t "meetings?year=2026"                'https://api.openf1.org/v1/meetings?year=2026'
t "meetings?year=2025"                'https://api.openf1.org/v1/meetings?year=2025'
t "meetings?meeting_key=1219"         'https://api.openf1.org/v1/meetings?meeting_key=1219'

echo ""
echo "### OTROS ###"
t "laps?session_key=9159"             'https://api.openf1.org/v1/laps?session_key=9159'
t "drivers?session_key=9159"          'https://api.openf1.org/v1/drivers?session_key=9159'
t "stints?session_key=9159"           'https://api.openf1.org/v1/stints?session_key=9159'
t "weather?session_key=9159"          'https://api.openf1.org/v1/weather?session_key=9159'
t "race_control?session_key=9159"     'https://api.openf1.org/v1/race_control?session_key=9159'
t "position?session_key=9159"         'https://api.openf1.org/v1/position?session_key=9159'
t "location?session_key=9159"         'https://api.openf1.org/v1/location?session_key=9159'
t "session_result?session_key=9159"   'https://api.openf1.org/v1/session_result?session_key=9159'
t "intervals?session_key=9159"        'https://api.openf1.org/v1/intervals?session_key=9159'
t "pit?session_key=9159"              'https://api.openf1.org/v1/pit?session_key=9159'
t "overtakes?session_key=9159"        'https://api.openf1.org/v1/overtakes?session_key=9159'
t "starting_grid?session_key=9159"    'https://api.openf1.org/v1/starting_grid?session_key=9159'
t "championship_drivers"              'https://api.openf1.org/v1/championship_drivers?session_key=9159'
t "championship_teams"                'https://api.openf1.org/v1/championship_teams?session_key=9159'
