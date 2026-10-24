/**
 * @file server.js
 * @description Main entry point for the F1 Live Timing REST API Server.
 * Connects to Formula 1 SignalR Core live telemetry and exposes modular REST endpoints.
 */

const express = require('express');
const cors = require('cors');
const path = require('path');
const F1LiveClient = require('./f1-client');
const { createLeaderboardRouter } = require('./routes/leaderboard');
const { createStandingsRouter } = require('./routes/standings');
const { createTyresRouter } = require('./routes/tyres');
const { createDriversRouter } = require('./routes/drivers');
const { createSessionRouter } = require('./routes/session');
// [Race Center addition] Route for the CarData channel (track positions + telemetry).
const { createCarDataRouter, createTrackStatusRouter } = require('./routes/car-data');

const app = express();
const PORT = process.env.PORT || 3000;
// [Race Center patch] Upstream calls app.listen(PORT) with no host, which binds 0.0.0.0.
// We bind loopback by default so the live-timing service is NOT reachable from the LAN.
// Set HOST=0.0.0.0 to restore the upstream behaviour.
const HOST = process.env.HOST || '127.0.0.1';

// Enable JSON body parsing and CORS for downstream client/dashboard access
// [Race Center patch] Restrict CORS to loopback origins instead of cors() (allows any origin).
// Requests without an Origin header (server-to-server, i.e. the Django backend) are allowed.
const CORS_ORIGINS = (
    process.env.CORS_ORIGINS ||
    'http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:8000,http://localhost:8000'
)
    .split(',')
    .map((origin) => origin.trim())
    .filter(Boolean);
app.use(
    cors({
        origin: (origin, callback) => {
            if (!origin) return callback(null, true);
            if (CORS_ORIGINS.includes(origin)) return callback(null, true);
            return callback(null, false);
        },
    })
);
app.use(express.json());



// Instantiate and initiate the F1 SignalR live timing connection
console.log('[Server] Initialising F1LiveClient and connecting to F1 SignalR Core...');
const f1Client = new F1LiveClient();
f1Client.connect().then(() => {
    console.log('[Server] F1 SignalR connection negotiation initiated.');
});

// Mount specialized REST API routers
app.use('/api/leaderboard', createLeaderboardRouter(f1Client));
app.use('/api/standings', createStandingsRouter(f1Client));

const tyresRouter = createTyresRouter(f1Client);
app.use('/api/tyres', tyresRouter);
app.use('/api/stints', tyresRouter);

app.use('/api/drivers', createDriversRouter(f1Client));

// Mount session, weather, lap-count, race-control, and radio routes under /api
app.use('/api', createSessionRouter(f1Client));

// [Race Center addition] Live car positions and telemetry.
app.use('/api/car-data', createCarDataRouter(f1Client));
app.use('/api/track-status', createTrackStatusRouter(f1Client));

/**
 * GET /api/status
 * Returns WebSocket connection state, uptime, and last received message timestamp.
 */
app.get('/api/status', (req, res) => {
    const status = f1Client.getConnectionStatus();
    res.status(200).json({
        service: 'f1-livetiming-api',
        status: status.isConnected ? 'CONNECTED' : 'DISCONNECTED',
        isConnected: status.isConnected,
        lastMessageAt: status.lastMessageAt,
        uptimeSeconds: Math.floor(process.uptime()),
        timestamp: new Date().toISOString()
    });
});

/**
 * Fallback handler for undefined API endpoints.
 */
app.use((req, res) => {
    res.status(404).json({
        error: 'Endpoint not found.',
        documentationUrl: '/docs',
        availableRoutes: [
            '/api/status',
            '/api/standings',
            '/api/leaderboard',
            '/api/tyres',
            '/api/drivers',
            '/api/session',
            '/api/lap-count',
            '/api/weather',
            '/api/race-control',
            '/api/radio',
            '/docs'
        ]
    });
});

// Start listening for HTTP requests
const server = app.listen(PORT, HOST, () => {
    console.log(`\n====================================================================`);
    console.log(`  F1 Live Timing REST API Running`);
    console.log(`  Bind: http://${HOST}:${PORT}`);
    console.log(`  CORS origins: ${CORS_ORIGINS.join(', ')}`);
    console.log(`  Documentation Website: http://localhost:${PORT}/docs`);
    console.log(`  Available Endpoints:`);
    console.log(`    - GET http://localhost:${PORT}/api/status`);
    console.log(`    - GET http://localhost:${PORT}/api/standings`);
    console.log(`    - GET http://localhost:${PORT}/api/leaderboard`);
    console.log(`    - GET http://localhost:${PORT}/api/tyres         (alias: /api/stints)`);
    console.log(`    - GET http://localhost:${PORT}/api/drivers`);
    console.log(`    - GET http://localhost:${PORT}/api/session`);
    console.log(`    - GET http://localhost:${PORT}/api/lap-count     (alias: /api/laps)`);
    console.log(`    - GET http://localhost:${PORT}/api/weather`);
    console.log(`    - GET http://localhost:${PORT}/api/race-control  (alias: /api/flags)`);
    console.log(`    - GET http://localhost:${PORT}/api/radio         (alias: /api/team-radio)`);
    console.log(`====================================================================\n`);
});

module.exports = { app, server, f1Client };
