---
title: Globals
kind: global
longname: Globals
---

# Globals

---

## Instance Methods

<MemberHeading id="createdriversrouter" depth="3" name="createDriversRouter" sig="createDriversRouter(f1Client: F1LiveClient): express.Router" />

<MemberMeta sourceHref="/source/routes/drivers-js/#L14" sourceLabel="drivers.js:14" />

Creates and configures the driver directory Express router.

**Parameters**

- `f1Client` (F1LiveClient) — Active instance of F1LiveClient.

**Returns**

- `express.Router` — Express router instance.

<MemberHeading id="createleaderboardrouter" depth="3" name="createLeaderboardRouter" sig="createLeaderboardRouter(f1Client: F1LiveClient): express.Router" />

<MemberMeta sourceHref="/source/routes/leaderboard-js/#L15" sourceLabel="leaderboard.js:15" />

Creates and configures the leaderboard Express router.

**Parameters**

- `f1Client` (F1LiveClient) — Active instance of F1LiveClient.

**Returns**

- `express.Router` — Express router instance.

<MemberHeading id="createsessionrouter" depth="3" name="createSessionRouter" sig="createSessionRouter(f1Client: F1LiveClient): express.Router" />

<MemberMeta sourceHref="/source/routes/session-js/#L15" sourceLabel="session.js:15" />

Creates and configures the session and environmental data Express router.

**Parameters**

- `f1Client` (F1LiveClient) — Active instance of F1LiveClient.

**Returns**

- `express.Router` — Express router instance.

<MemberHeading id="createstandingsrouter" depth="3" name="createStandingsRouter" sig="createStandingsRouter(f1Client: F1LiveClient): express.Router" />

<MemberMeta sourceHref="/source/routes/standings-js/#L15" sourceLabel="standings.js:15" />

Creates and configures the dedicated standings Express router.

**Parameters**

- `f1Client` (F1LiveClient) — Active instance of F1LiveClient.

**Returns**

- `express.Router` — Express router instance.

<MemberHeading id="createtyresrouter" depth="3" name="createTyresRouter" sig="createTyresRouter(f1Client: F1LiveClient): express.Router" />

<MemberMeta sourceHref="/source/routes/tyres-js/#L15" sourceLabel="tyres.js:15" />

Creates and configures the tyre strategy Express router.

**Parameters**

- `f1Client` (F1LiveClient) — Active instance of F1LiveClient.

**Returns**

- `express.Router` — Express router instance.

<MemberHeading
  id="sortracingnumbers"
  depth="3"
  name="sortRacingNumbers"
  sig="sortRacingNumbers(
	racingNumbers: Array.<string>,
	lines: Object,
): Array.<string>"
/>

<MemberMeta sourceHref="/source/services/leaderboard-service-js/#L15" sourceLabel="leaderboard-service.js:15" />

Helper to sort a list of racing numbers dynamically by live Position, fallback to GridPos/Line.

**Parameters**

- `racingNumbers` (Array.\<string>) — Array of driver racing number IDs.
- `lines` (Object) — Keyed object containing driver telemetry/metadata.

**Returns**

- `Array.<string>` — Sorted array of racing number IDs.

<MemberHeading id="getliveleaderboard" depth="3" name="getLiveLeaderboard" sig="getLiveLeaderboard(f1Client: F1LiveClient): Object" />

<MemberMeta sourceHref="/source/services/leaderboard-service-js/#L46" sourceLabel="leaderboard-service.js:46" />

Builds the comprehensive live leaderboard merging DriverList, TimingData, and TimingAppData per driver.

**Parameters**

- `f1Client` (F1LiveClient) — Instance of F1LiveClient.

**Returns**

- `Object` — All-in-one structured response.

<MemberHeading id="getdriverleaderboard" depth="3" name="getDriverLeaderboard" sig="getDriverLeaderboard()" />

<MemberMeta sourceHref="/source/services/leaderboard-service-js/#L88" sourceLabel="leaderboard-service.js:88" />

Retrieves full combined data for a specific racing number.

<MemberHeading id="getlivestandings" depth="3" name="getLiveStandings" sig="getLiveStandings()" />

<MemberMeta sourceHref="/source/services/leaderboard-service-js/#L105" sourceLabel="leaderboard-service.js:105" />

Builds dedicated driver standings and classification, combining only DriverList and TimingData (no tyre stint arrays or root session overhead). Perfect for pure leaderboard display.

<MemberHeading id="getdriverstandings" depth="3" name="getDriverStandings" sig="getDriverStandings()" />

<MemberMeta sourceHref="/source/services/leaderboard-service-js/#L139" sourceLabel="leaderboard-service.js:139" />

Retrieves standings data for a single specific driver.

<MemberHeading id="getlivetyres" depth="3" name="getLiveTyres" sig="getLiveTyres()" />

<MemberMeta sourceHref="/source/services/leaderboard-service-js/#L156" sourceLabel="leaderboard-service.js:156" />

Builds tyre strategy and stint history from TimingAppData, enriched with driver basic identity (Tla, BroadcastName, TeamName, TeamColour) from DriverList for instant visual mapping.

<MemberHeading id="getdrivertyres" depth="3" name="getDriverTyres" sig="getDriverTyres()" />

<MemberMeta sourceHref="/source/services/leaderboard-service-js/#L201" sourceLabel="leaderboard-service.js:201" />

Retrieves tyre compound and stint history for a single specific driver.

<MemberHeading id="getdriversdirectory" depth="3" name="getDriversDirectory" sig="getDriversDirectory()" />

<MemberMeta sourceHref="/source/services/leaderboard-service-js/#L216" sourceLabel="leaderboard-service.js:216" />

Retrieves official driver directory and metadata from F1 SignalR DriverList channel.

<MemberHeading id="getenrichedteamradio" depth="3" name="getEnrichedTeamRadio" sig="getEnrichedTeamRadio()" />

<MemberMeta sourceHref="/source/services/leaderboard-service-js/#L226" sourceLabel="leaderboard-service.js:226" />

Retrieves team radio transmissions enriched with driver basic identity from DriverList.

<MemberHeading id="isplainobject" depth="3" name="isPlainObject" sig="isPlainObject(item: any): boolean" />

<MemberMeta sourceHref="/source/utils/merge-js/#L14" sourceLabel="merge.js:14" />

Checks if a value is a plain object (and not null, array, Date, etc.).

**Parameters**

- `item` (any) — Value to check.

**Returns**

- `boolean` — True if the value is a plain object.

<MemberHeading id="deepmerge" depth="3" name="deepMerge" sig="deepMerge(target: Object, source: Object): Object" />

<MemberMeta sourceHref="/source/utils/merge-js/#L26" sourceLabel="merge.js:26" />

Deeply merges a source object (SignalR delta) into a target object (in-memory state). Modifies target directly and returns it. Does not modify key names or cases.

**Parameters**

- `target` (Object) — The destination state object.
- `source` (Object) — The delta object to merge into target.

**Returns**

- `Object` — The merged target object.

## Other

<MemberHeading id="routesdriversjs" depth="3" name="routes/drivers.js" sig="routes/drivers.js" />

<MemberMeta sourceHref="/source/routes/drivers-js/#L6" sourceLabel="drivers.js:6" />

Express routes for querying the official Formula 1 DriverList directory and metadata.

<MemberHeading id="routesleaderboardjs" depth="3" name="routes/leaderboard.js" sig="routes/leaderboard.js" />

<MemberMeta sourceHref="/source/routes/leaderboard-js/#L7" sourceLabel="leaderboard.js:7" />

Express routes for retrieving live F1 driver standings and classification. Returns exact SignalR Core PascalCase properties without renaming.

<MemberHeading id="routessessionjs" depth="3" name="routes/session.js" sig="routes/session.js" />

<MemberMeta sourceHref="/source/routes/session-js/#L7" sourceLabel="session.js:7" />

Express routes exposing specialized session state, meteorological telemetry, lap progress, race control messages, and team radio transmissions.

<MemberHeading id="routesstandingsjs" depth="3" name="routes/standings.js" sig="routes/standings.js" />

<MemberMeta sourceHref="/source/routes/standings-js/#L7" sourceLabel="standings.js:7" />

Express routes for retrieving driver standings, positions, intervals, and lap timing metrics decoupled from tyre stint histories and root session metadata.

<MemberHeading id="routestyresjs" depth="3" name="routes/tyres.js" sig="routes/tyres.js" />

<MemberMeta sourceHref="/source/routes/tyres-js/#L7" sourceLabel="tyres.js:7" />

Express routes for retrieving driver tyre compound allocations, stint histories, and strategy data. Enriched with driver TLA, TeamColour, and BroadcastName without altering native PascalCase SignalR properties.

<MemberHeading id="serverjs" depth="3" name="server.js" sig="server.js" />

<MemberMeta sourceHref="/source/server-js/#L7" sourceLabel="server.js:7" />

Main entry point for the F1 Live Timing REST API Server. Connects to Formula 1 SignalR Core live telemetry and exposes modular REST endpoints.

<MemberHeading id="servicesleaderboard-servicejs" depth="3" name="services/leaderboard-service.js" sig="services/leaderboard-service.js" />

<MemberMeta sourceHref="/source/services/leaderboard-service-js/#L7" sourceLabel="leaderboard-service.js:7" />

Service responsible for assembling live telemetry, driver standings, tyre strategies, and session diagnostics directly from SignalR Core raw data streams without altering field names or case (PascalCase preserved).

<MemberHeading id="utilsmergejs" depth="3" name="utils/merge.js" sig="utils/merge.js" />

<MemberMeta sourceHref="/source/utils/merge-js/#L9" sourceLabel="merge.js:9" />

Utility for deeply merging F1 SignalR Core delta payloads into an existing state tree. F1 SignalR uses a delta protocol where only changed fields in channels like TimingData or TimingAppData are sent in each message. Deep merging ensures that nested structures (such as Sectors, Speeds, or Stints) are cleanly updated without overwriting existing sibling fields.
