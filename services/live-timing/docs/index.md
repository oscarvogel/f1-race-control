---
title: Home
kind: index
---

# F1 Live Timing REST API (`f1-livetiming-api`)

Host your own high-performance, real-time REST API server for Formula 1 live timing, driver standings, tyre strategies, and race control telemetry. Connected directly to the official F1 SignalR Core streaming endpoint (`livetiming.formula1.com`).

---

## Core Architecture & Data Principles

Designed for absolute data fidelity and zero-latency local consumption, `f1-livetiming-api` is built on three pillars:

1. **Zero Field Renaming (1:1 PascalCase Fidelity)**: Every telemetry property emitted by Formula 1 SignalR servers is preserved verbatim in its native **PascalCase** convention (`Position`, `GapToLeader`, `BestLapTime`, `TeamColour`, `Stints`, etc.). No artificial camelCase transformations or hardcoded driver dictionaries are used; driver identities are natively sourced from the official `DriverList` stream.
1. **Background Delta-Merge Synchronisation**: F1 SignalR operates via a delta protocol (transmitting only modified properties per tick). The server maintains an in-memory state store powered by a custom deep-merge engine ([src/utils/merge.js](src/utils/merge.js)). Incoming deltas are seamlessly merged into server RAM in the background without overwriting adjacent objects or arrays.
1. **Zero Outbound HTTP Overhead (100% Local Reads)**: When your dashboard, frontend, or script queries any endpoint on this server, **zero requests are dispatched to Formula 1 servers**. All REST responses read straight from local memory in sub-millisecond time. You can poll the local endpoints at 1,000 requests per second with **zero risk of rate-limiting or IP bans**.

```
[ Official F1 SignalR WebSocket (livetiming.formula1.com) ]
                             │
                             │ (Continuous streaming JSON deltas in background)
                             ▼
 [ src/f1-client.js ] ──► In-Memory Deep Merge via [ src/utils/merge.js ]
                             │
                             ▼ (Real-time RAM cache: TimingData, DriverList, TimingAppData...)
 [ Specialized Express Route Handlers & Telemetry Services ]
                             │
                             ▼
 [ HTTP Consumer ] ◄── GET /api/standings, /api/tyres, /api/weather, etc. (0ms latency)
```

---

## Specialized & Decoupled REST Endpoints

To avoid monolithic responses and enable clean modular frontend designs, telemetry feeds are separated into distinct, targeted domain endpoints. All endpoints default to port `3000` (override via `PORT` environment variable) with standard JSON format and CORS enabled.

### Driver Standings & Leaderboards

| Method  | Endpoint               | Alias | Description                                                                                                                                                                                                 |
| ------- | ---------------------- | ----- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **GET** | `/api/standings`       | _-_   | Dedicated driver classification sorted by live `Position`. Combines driver identity and timing intervals (`GapToLeader`, `BestLapTime`, `Sectors`, `Speeds`) without tyre stint arrays or meeting overhead. |
| **GET** | `/api/standings/:id`   | _-_   | Retrieves live timing and rank for a specific driver by their racing number (e.g., `/api/standings/1` or `/api/standings/44`).                                                                              |
| **GET** | `/api/leaderboard`     | _-_   | All-in-one comprehensive view combining driver metadata, live gaps, tyre stints, current lap count, and session meeting data into a single unified response.                                                |
| **GET** | `/api/leaderboard/:id` | _-_   | Comprehensive unified telemetry package for an individual driver.                                                                                                                                           |

### Tyre Strategies & Stint Chronology

| Method  | Endpoint         | Alias             | Description                                                                                                                                                                                                   |
| ------- | ---------------- | ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **GET** | `/api/tyres`     | `/api/stints`     | Decoupled tyre strategy feed. Exposes compounds (`SOFT`, `MEDIUM`, `HARD`, `INTERMEDIATE`, `WET`), total lap wear per set, grid vs current line positions, enriched with driver acronyms and team hex colors. |
| **GET** | `/api/tyres/:id` | `/api/stints/:id` | Detailed stint chronology and active compound allocation for a specific driver.                                                                                                                               |

### Driver Directory & Meeting Metadata

| Method  | Endpoint           | Description                                                                                                                                                                  |
| ------- | ------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **GET** | `/api/drivers`     | Official meeting driver roster (`DriverList`), providing full names, broadcasting acronyms (`Tla`), team names, hex RGB team colors, country codes, and headshot references. |
| **GET** | `/api/drivers/:id` | Specific team and personal metadata for a designated racing number.                                                                                                          |

### Track Status, Weather & Race Control

| Method  | Endpoint            | Alias             | Description                                                                                                                                                       |
| ------- | ------------------- | ----------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **GET** | `/api/session`      | _-_               | Current meeting identifier, official session name, session type (`Practice`, `Qualifying`, `Race`, `Sprint`), and lifecycle status.                               |
| **GET** | `/api/lap-count`    | `/api/laps`       | Live lap counter and scheduled total meeting laps (`{ "CurrentLap": 24, "TotalLaps": 57 }`).                                                                      |
| **GET** | `/api/weather`      | _-_               | Real-time meteorological telemetry: Air temperature, track surface temperature, relative humidity, wind speed/direction, and rain detection sensors.              |
| **GET** | `/api/race-control` | `/api/flags`      | Official FIA Race Control broadcasts: Track flag statuses (`GREEN`, `YELLOW`, `RED`), safety car deployments (`SC`, `VSC`), DRS enablement, and penalty warnings. |
| **GET** | `/api/radio`        | `/api/team-radio` | Recent team radio broadcast audio capture notifications, enriched with driver and team identity.                                                                  |

### Server Health Diagnostics

| Method  | Endpoint      | Description                                                                                                                                                                             |
| ------- | ------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **GET** | `/api/status` | Real-time diagnostics detailing WebSocket connectivity state (`CONNECTED` / `DISCONNECTED`), server process uptime in seconds, and timestamp of the last received SignalR transmission. |

---

## Session Schema Variations (Practice vs Race)

Because F1 SignalR adjusts its broadcast payload according to session discipline, the schema-agnostic deep merge natively reflects these variations across the API:

### Race & Sprint Sessions

Focus is placed on track positioning, intervals, and pit lane activity:

- **`Position`**: Live numeric racing position used for automatic leaderboard ranking.
- **`GapToLeader`**: Object detailing gap to P1 (e.g., `{"Value": "+4.128", "Catching": false}` or `{"Value": "LEADER"}`).
- **`IntervalToPositionAhead`**: Distance interval to the immediate preceding driver.
- **`InPit`** / **`PitOut`**: Live boolean indicators of pit lane transit.
- **`NumberOfPitStops`**: Official count of completed box stops.
- **`Retired`** / **`Stopped`**: DNF status flags, automatically shifting retired cars to the classification tail during dynamic sorting.

### Practice, Qualifying & Shootout Sessions

Focus shifts to timed lap speed, sector accuracy, and qualification drop zone thresholds:

- **`BestLapTime`**: Current session personal benchmark (`{"Value": "1:28.914", "PersonalFastest": true, "OverallFastest": true}`).
- **`BestLapTimes`**: Dictionary separating fastest laps by qualification segment (key `"0"` for Q1, `"1"` for Q2, `"2"` for Q3).
- **`Stats`**: Qualifying gap statistics including time variance to session leader (`TimeDiffToFastest`) and immediate ranking predecessor (`TimeDifftoPositionAhead`).
- **`Sectors`** / **`Speeds`**: Sector performance blocks and speed trap recordings at the Finish Line (`FL`), maximum Speed Trap (`ST`), and intermediate sectors (`I1`, `I2`).

---

## Installation & Server Startup

### Prerequisites

Requires Node.js (v18 or newer recommended for native `fetch` support during HTTP SignalR negotiation).

```
# Navigate to the API workspace
cd f1-livetiming-api

# Install dependencies (ws, express, cors, nodemon)
npm install
```

### Running the Server

```
# Standard production execution
npm start

# Development mode with automatic live reloading on file changes
npm run dev
```

Upon initialization, the server will display its routing manifest and initiate F1 SignalR Core connection sequences:

```
[Server] Initialising F1LiveClient and connecting to F1 SignalR Core...
[F1Client] Pre-negotiating with F1 SignalR...
[F1Client] Connecting to F1 SignalR Core WebSocket...
[F1Client] Handshake complete. Subscribing to channels...

====================================================================
  F1 Live Timing REST API Running
  Port: http://localhost:3000
  Available Endpoints:
    - GET http://localhost:3000/api/status
    - GET http://localhost:3000/api/standings
    - GET http://localhost:3000/api/leaderboard
    - GET http://localhost:3000/api/tyres         (alias: /api/stints)
    - GET http://localhost:3000/api/drivers
    - GET http://localhost:3000/api/session
    - GET http://localhost:3000/api/lap-count     (alias: /api/laps)
    - GET http://localhost:3000/api/weather
    - GET http://localhost:3000/api/race-control  (alias: /api/flags)
    - GET http://localhost:3000/api/radio         (alias: /api/team-radio)
====================================================================
```

---

## Quick Usage Examples (cURL & JSON)

### 1. Fetch Dedicated Driver Standings (`/api/standings`)

Returns clean driver classification sorted by live position, stripped of heavy tyre stint histories.

```
curl http://localhost:3000/api/standings
```

**Example JSON Response:**

```
{
  "Leaderboard": ["1", "16", "44"],
  "Lines": {
    "1": {
      "RacingNumber": "1",
      "Position": "1",
      "BroadcastName": "M VERSTAPPEN",
      "FullName": "Max VERSTAPPEN",
      "Tla": "VER",
      "TeamName": "RED BULL RACING",
      "TeamColour": "3671C6",
      "GapToLeader": {
        "Value": "LEADER"
      },
      "BestLapTime": {
        "Value": "1:32.410",
        "PersonalFastest": true,
        "OverallFastest": true
      },
      "InPit": false,
      "NumberOfPitStops": 1,
      "Sectors": {
        "0": { "Value": "28.912" },
        "1": { "Value": "39.105" },
        "2": { "Value": "24.393" }
      }
    },
    "16": {
      "RacingNumber": "16",
      "Position": "2",
      "BroadcastName": "C LECLERC",
      "Tla": "LEC",
      "TeamName": "FERRARI",
      "TeamColour": "E8002D",
      "GapToLeader": {
        "Value": "+1.842",
        "Catching": false
      },
      "InPit": false,
      "NumberOfPitStops": 1
    }
  }
}
```

---

### 2. Fetch Tyre Strategies & Stints (`/api/tyres` or `/api/stints`)

Ideal for strategic dashboards tracking tyre degradation and compound allocations.

```
curl http://localhost:3000/api/tyres
```

**Example JSON Response:**

```
{
  "Leaderboard": ["1", "16", "44"],
  "Lines": {
    "1": {
      "RacingNumber": "1",
      "BroadcastName": "M VERSTAPPEN",
      "Tla": "VER",
      "TeamColour": "3671C6",
      "GridPos": "1",
      "Position": "1",
      "Stints": [
        {
          "Compound": "SOFT",
          "TotalLaps": 16,
          "New": true
        },
        {
          "Compound": "HARD",
          "TotalLaps": 8,
          "New": true
        }
      ]
    }
  }
}
```

---

### 3. Fetch Real-Time Meteorological Telemetry (`/api/weather`)

Retrieves atmospheric sensors directly from trackside F1 instrumentation.

```
curl http://localhost:3000/api/weather
```

**Example JSON Response:**

```
{
  "Weather": {
    "AirTemp": "28.4",
    "Humidity": "52",
    "Pressure": "1012.8",
    "Rainfall": "0",
    "TrackTemp": "41.9",
    "WindDirection": "165",
    "WindSpeed": "2.8"
  }
}
```

---

### 4. Monitor Server & WebSocket Health (`/api/status`)

Used by uptime monitors or UI polling guards to verify active live timing stream health.

```
curl http://localhost:3000/api/status
```

**Example JSON Response:**

```
{
  "service": "f1-livetiming-api",
  "status": "CONNECTED",
  "isConnected": true,
  "lastMessageAt": "2026-07-28T09:42:15.824Z",
  "uptimeSeconds": 3840,
  "timestamp": "2026-07-28T09:42:16.000Z"
}
```

---

## Source Directory Overview

```
f1-livetiming-api/
│
├── package.json                   # Express, CORS, and WebSocket dependencies
├── README.md                      # Architecture guide and endpoint reference (English)
└── src/
    ├── server.js                  # Application root, middleware, and router mounts
    ├── f1-client.js               # SignalR Core WebSocket engine & background delta subscriber
    ├── routes/
    │   ├── standings.js           # /api/standings router (classification table)
    │   ├── tyres.js               # /api/tyres & /api/stints router (compound strategy)
    │   ├── drivers.js             # /api/drivers router (DriverList official directory)
    │   ├── session.js             # /api/session, /lap-count, /weather, /race-control, & /radio routers
    │   └── leaderboard.js         # /api/leaderboard all-in-one consolidated telemetry router
    ├── services/
    │   └── leaderboard-service.js # Domain data extraction, deep merging & dynamic position sorting
    └── utils/
        └── merge.js               # SignalR delta recursive deep-merge engine
```
