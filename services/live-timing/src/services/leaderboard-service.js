/**
 * @file leaderboard-service.js
 * @description Service responsible for assembling live telemetry, driver standings, tyre strategies,
 * and session diagnostics directly from SignalR Core raw data streams without altering field names or case (PascalCase preserved).
 */

const { deepMerge } = require('../utils/merge');

/**
 * Helper to sort a list of racing numbers dynamically by live Position, fallback to GridPos/Line.
 * @param {Array<string>} racingNumbers - Array of driver racing number IDs.
 * @param {Object} lines - Keyed object containing driver telemetry/metadata.
 * @returns {Array<string>} Sorted array of racing number IDs.
 */
function sortRacingNumbers(racingNumbers, lines) {
    return Array.from(racingNumbers).sort((numA, numB) => {
        const driverA = lines[numA] || {};
        const driverB = lines[numB] || {};

        const posA = driverA.Position ? parseInt(driverA.Position, 10) : 999;
        const posB = driverB.Position ? parseInt(driverB.Position, 10) : 999;

        const validPosA = !isNaN(posA) ? posA : 999;
        const validPosB = !isNaN(posB) ? posB : 999;

        if (validPosA !== validPosB) {
            return validPosA - validPosB;
        }

        const gridA = driverA.GridPos ? parseInt(driverA.GridPos, 10) : driverA.Line || 999;
        const gridB = driverB.GridPos ? parseInt(driverB.GridPos, 10) : driverB.Line || 999;

        if (gridA !== gridB) {
            return gridA - gridB;
        }

        return parseInt(numA, 10) - parseInt(numB, 10);
    });
}

/**
 * Builds the comprehensive live leaderboard merging DriverList, TimingData, and TimingAppData per driver.
 * @param {F1LiveClient} f1Client - Instance of F1LiveClient.
 * @returns {Object} All-in-one structured response.
 */
function getLiveLeaderboard(f1Client) {
    const timingData = f1Client.getTimingData() || {};
    const timingLines = timingData.Lines || {};
    const driverList = f1Client.getDriverList() || {};
    const timingAppData = f1Client.getTimingAppData() || {};
    const appLines = timingAppData.Lines || {};
    const sessionInfo = f1Client.getSessionInfo() || {};
    const lapCount = f1Client.getLapCount() || {};

    const racingNumbers = new Set([...Object.keys(driverList), ...Object.keys(timingLines), ...Object.keys(appLines)]);

    const mergedLines = {};
    for (const racingNumber of racingNumbers) {
        const driverMeta = driverList[racingNumber] || {};
        const driverApp = appLines[racingNumber] || {};
        const driverTiming = timingLines[racingNumber] || {};

        const unifiedDriver = {};
        deepMerge(unifiedDriver, driverMeta);
        deepMerge(unifiedDriver, driverApp);
        deepMerge(unifiedDriver, driverTiming);

        if (!unifiedDriver.RacingNumber) {
            unifiedDriver.RacingNumber = racingNumber;
        }

        mergedLines[racingNumber] = unifiedDriver;
    }

    const sortedLeaderboard = sortRacingNumbers(racingNumbers, mergedLines);

    return {
        Session: sessionInfo,
        LapCount: lapCount,
        Leaderboard: sortedLeaderboard,
        Lines: mergedLines
    };
}

/**
 * Retrieves full combined data for a specific racing number.
 */
function getDriverLeaderboard(f1Client, racingNumber) {
    const leaderboardData = getLiveLeaderboard(f1Client);
    if (!leaderboardData.Lines[racingNumber]) {
        return null;
    }

    const rankIndex = leaderboardData.Leaderboard.indexOf(racingNumber);
    return {
        Rank: rankIndex >= 0 ? rankIndex + 1 : null,
        Data: leaderboardData.Lines[racingNumber]
    };
}

/**
 * Builds dedicated driver standings and classification, combining only DriverList and TimingData
 * (no tyre stint arrays or root session overhead). Perfect for pure leaderboard display.
 */
function getLiveStandings(f1Client) {
    const timingData = f1Client.getTimingData() || {};
    const timingLines = timingData.Lines || {};
    const driverList = f1Client.getDriverList() || {};

    const racingNumbers = new Set([...Object.keys(driverList), ...Object.keys(timingLines)]);

    const standingsLines = {};
    for (const racingNumber of racingNumbers) {
        const driverMeta = driverList[racingNumber] || {};
        const driverTiming = timingLines[racingNumber] || {};

        const unifiedDriver = {};
        deepMerge(unifiedDriver, driverMeta);
        deepMerge(unifiedDriver, driverTiming);

        if (!unifiedDriver.RacingNumber) {
            unifiedDriver.RacingNumber = racingNumber;
        }

        standingsLines[racingNumber] = unifiedDriver;
    }

    const sortedLeaderboard = sortRacingNumbers(racingNumbers, standingsLines);

    return {
        Leaderboard: sortedLeaderboard,
        Lines: standingsLines
    };
}

/**
 * Retrieves standings data for a single specific driver.
 */
function getDriverStandings(f1Client, racingNumber) {
    const standingsData = getLiveStandings(f1Client);
    if (!standingsData.Lines[racingNumber]) {
        return null;
    }

    const rankIndex = standingsData.Leaderboard.indexOf(racingNumber);
    return {
        Rank: rankIndex >= 0 ? rankIndex + 1 : null,
        Data: standingsData.Lines[racingNumber]
    };
}

/**
 * Builds tyre strategy and stint history from TimingAppData, enriched with driver basic identity
 * (Tla, BroadcastName, TeamName, TeamColour) from DriverList for instant visual mapping.
 */
function getLiveTyres(f1Client) {
    const timingAppData = f1Client.getTimingAppData() || {};
    const appLines = timingAppData.Lines || {};
    const driverList = f1Client.getDriverList() || {};
    const timingData = f1Client.getTimingData() || {};
    const timingLines = timingData.Lines || {};

    const racingNumbers = new Set([...Object.keys(driverList), ...Object.keys(appLines)]);

    const tyreLines = {};
    for (const racingNumber of racingNumbers) {
        const driverMeta = driverList[racingNumber] || {};
        const driverApp = appLines[racingNumber] || {};
        const driverTiming = timingLines[racingNumber] || {};

        // Extract basic identification properties without renaming
        const identity = {
            RacingNumber: racingNumber,
            BroadcastName: driverMeta.BroadcastName || null,
            Tla: driverMeta.Tla || null,
            TeamName: driverMeta.TeamName || null,
            TeamColour: driverMeta.TeamColour || null,
            Position: driverTiming.Position || driverApp.Position || null,
            GridPos: driverApp.GridPos || null,
            Line: driverApp.Line !== undefined ? driverApp.Line : driverMeta.Line || null
        };

        const unifiedTyreDriver = {};
        deepMerge(unifiedTyreDriver, identity);
        deepMerge(unifiedTyreDriver, driverApp);

        tyreLines[racingNumber] = unifiedTyreDriver;
    }

    const sortedLeaderboard = sortRacingNumbers(racingNumbers, tyreLines);

    return {
        Leaderboard: sortedLeaderboard,
        Lines: tyreLines
    };
}

/**
 * Retrieves tyre compound and stint history for a single specific driver.
 */
function getDriverTyres(f1Client, racingNumber) {
    const tyreData = getLiveTyres(f1Client);
    if (!tyreData.Lines[racingNumber]) {
        return null;
    }

    return {
        RacingNumber: racingNumber,
        Data: tyreData.Lines[racingNumber]
    };
}

/**
 * Retrieves official driver directory and metadata from F1 SignalR DriverList channel.
 */
function getDriversDirectory(f1Client) {
    const driverList = f1Client.getDriverList() || {};
    return {
        Drivers: driverList
    };
}

/**
 * Retrieves team radio transmissions enriched with driver basic identity from DriverList.
 */
function getEnrichedTeamRadio(f1Client) {
    const teamRadio = f1Client.getTeamRadio() || [];
    const driverList = f1Client.getDriverList() || {};

    const enrichedCaptures = teamRadio.map((capture) => {
        const racingNumber = capture.RacingNumber;
        const driverMeta = driverList[racingNumber] || {};
        return {
            ...capture,
            Tla: driverMeta.Tla || null,
            BroadcastName: driverMeta.BroadcastName || null,
            TeamName: driverMeta.TeamName || null,
            TeamColour: driverMeta.TeamColour || null
        };
    });

    return {
        Captures: enrichedCaptures
    };
}

module.exports = {
    getLiveLeaderboard,
    getDriverLeaderboard,
    getLiveStandings,
    getDriverStandings,
    getLiveTyres,
    getDriverTyres,
    getDriversDirectory,
    getEnrichedTeamRadio
};
