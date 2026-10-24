const WebSocket = require('ws');
const fs = require('fs');
const path = require('path');
const { deepMerge } = require('./utils/merge');

const F1_ORIGIN_URL = 'https://www.formula1.com';
const F1_HTTP_URL = 'https://livetiming.formula1.com/signalrcore';
const F1_WS_URL = 'wss://livetiming.formula1.com/signalrcore';

const NEGOTIATE_VERSION = '1';
const RECORD_SEP = '\x1e';
const SUBSCRIBE_INVOCATION_ID = '0';

const MSG_INVOCATION = 1;
const MSG_COMPLETION = 3;

const HANDSHAKE_MESSAGE = `{"protocol":"json","version":1}${RECORD_SEP}`;

const SUBSCRIBE_CHANNELS = [
    'TimingData',
    'TimingDataF1',
    'TimingAppData',
    'DriverList',
    'SessionInfo',
    'WeatherData',
    'RaceControlMessages',
    'LapCount',
    'TeamRadio',
    // [Race Center addition] CarData carries per-car X/Y/Z track coordinates and telemetry.
    'CarData',
    // [Race Center addition] Positions carries the per-car X/Y/Z coordinates on
    // track. `CarData` only carries the telemetry (speed, rpm, gear...).
    'Positions',
    // [Race Center addition] TrackStatus carries the track flags and safety car state.
    'TrackStatus'
];

class F1LiveClient {
    constructor(broadcastCallback) {
        this.broadcast = broadcastCallback || (() => {});
        this.ws = null;
        this.isConnected = false;
        this.lastMessageAt = null;

        // Global State Cache preserving exact SignalR Core PascalCase structure and fields
        this.timingData = { Lines: {} };
        this.driverList = {};
        this.timingAppData = { Lines: {} };
        this.weather = {};
        this.session = {};
        this.lapCount = {};
        this.raceControl = [];
        this.teamRadio = [];
        // [Race Center addition] Live car positions and telemetry (X/Y/Z, speed, rpm, gear...).
        this.carData = {};
        // [Race Center addition] Live car coordinates (X/Y/Z) on the track.
        // `CarData` carries the telemetry (speed, rpm, gear, throttle, brake);
        // the *coordinates* come in their own channel, `Positions`.
        this.positions = {};
        // [Race Center addition] Track flags and safety car state.
        this.trackStatus = {};

        this.watchdogTimer = null;
    }

    /**
     * @description Initiates connection to F1 SignalR live timing endpoint.
     * @returns {Promise<void>} Resolves when initial connection sequence completes.
     */
    connect() {
        return new Promise((resolve) => {
            let isDone = false;
            const finish = () => {
                if (!isDone) {
                    isDone = true;
                    resolve();
                }
            };

            const timeout = setTimeout(finish, 10000);
            this._startConnection(finish, timeout);
        });
    }

    /**
     * @description Negotiates HTTP session and starts WebSocket connection.
     * @param {Function} [onReady] - Callback invoked when connection sequence finishes.
     * @param {NodeJS.Timeout} [timeout] - Safety timer for connection initialisation.
     * @returns {Promise<void>} Resolves when connection attempt concludes.
     */
    async _startConnection(onReady, timeout) {
        try {
            console.log('\n[F1Client] Pre-negotiating with F1 SignalR...');
            const preNegResp = await fetch(`${F1_HTTP_URL}/negotiate`, {
                method: 'OPTIONS',
                headers: { 'User-Agent': 'BestHTTP', Origin: F1_ORIGIN_URL }
            });
            const rawCookie = preNegResp.headers.get('set-cookie') || '';
            const awsMatch = rawCookie.match(/AWSALBCORS=([^;]+)/);
            const awsAlbCors = awsMatch ? awsMatch[1] : '';

            const negotiateHeaders = {
                'User-Agent': 'BestHTTP',
                Origin: F1_ORIGIN_URL,
                'Content-Type': 'text/plain'
            };
            if (awsAlbCors) negotiateHeaders['Cookie'] = `AWSALBCORS=${awsAlbCors}`;

            const negotiateResp = await fetch(`${F1_HTTP_URL}/negotiate?negotiateVersion=${NEGOTIATE_VERSION}`, {
                method: 'POST',
                headers: negotiateHeaders
            });

            if (!negotiateResp.ok) throw new Error(`Negotiate failed — HTTP ${negotiateResp.status}`);

            const negotiateData = await negotiateResp.json();
            const connectionToken = encodeURIComponent(negotiateData.connectionToken);

            let wsUrl = `${F1_WS_URL}?id=${connectionToken}`;
            const wsHeaders = {
                'User-Agent': 'BestHTTP',
                Origin: F1_ORIGIN_URL
            };
            if (awsAlbCors) wsHeaders['Cookie'] = `AWSALBCORS=${awsAlbCors}`;

            console.log('[F1Client] Connecting to F1 SignalR Core WebSocket...');
            this.ws = new WebSocket(wsUrl, { headers: wsHeaders });
            this.setupListeners(onReady, timeout);
        } catch (error) {
            console.error('[F1Client] Connection error:', error);
            if (timeout) clearTimeout(timeout);
            if (onReady) onReady();
            setTimeout(() => this.connect(), 5000);
        }
    }

    /**
     * @description Registers WebSocket event listeners for messages and state changes.
     * @param {Function} [onReady] - Callback invoked when initial handshake completes.
     * @param {NodeJS.Timeout} [timeout] - Safety timer for connection initialisation.
     * @returns {void}
     */
    setupListeners(onReady, timeout) {
        let isHandshakeComplete = false;

        this.ws.on('open', () => {
            console.log('[F1Client] WebSocket open — sending handshake...');
            this.ws.send(HANDSHAKE_MESSAGE);
        });

        this.ws.on('message', (data) => {
            this.lastMessageAt = new Date().toISOString();
            if (this.watchdogTimer) clearTimeout(this.watchdogTimer);
            this.watchdogTimer = setTimeout(() => {
                if (this.isConnected) {
                    console.error('[F1Client] Watchdog timeout: No data received for 20s. Forcing reconnect...');
                    try {
                        this.ws.terminate();
                    } catch (e) {}
                }
            }, 20000);

            try {
                const raw = data.toString('utf-8');
                for (const segment of raw.split(RECORD_SEP)) {
                    if (segment.length === 0) continue;
                    const frame = JSON.parse(segment);

                    if (!isHandshakeComplete) {
                        if (frame.error) {
                            console.error('[F1Client] Handshake rejected:', frame.error);
                            if (timeout) clearTimeout(timeout);
                            if (onReady) onReady();
                            this.ws.close();
                            return;
                        }
                        isHandshakeComplete = true;
                        this.isConnected = true;
                        console.log('[F1Client] Handshake complete. Subscribing to channels...');
                        if (timeout) clearTimeout(timeout);
                        if (onReady) onReady();

                        try {
                            const logPath = path.join(__dirname, '../signalr_connections.log');
                            const timestamp = new Date().toLocaleString('fr-FR', { timeZone: 'Europe/Paris' });
                            fs.appendFileSync(
                                logPath,
                                `[${timestamp}] F1 SignalR connection successfully established.\n`
                            );
                        } catch (err) {
                            console.error('[F1Client] Failed to write to connection log:', err.message);
                        }

                        this.sendSubscribe();
                        return;
                    }

                    if (frame.type === MSG_COMPLETION && frame.invocationId === SUBSCRIBE_INVOCATION_ID) {
                        if (frame.result) {
                            this.handleSnapshot(frame.result);
                        }
                    }

                    if (frame.type === MSG_INVOCATION && frame.target === 'feed') {
                        const args = frame.arguments;
                        if (args && args.length >= 2) {
                            const channel = args[0];
                            const payload = args[1];
                            this.routeData(channel, payload);
                        }
                    }
                }
            } catch (err) {
                // Silent catch for partial frames or malformed segments
            }
        });

        this.ws.on('close', () => {
            this.isConnected = false;
            if (this.watchdogTimer) clearTimeout(this.watchdogTimer);
            console.log('[F1Client] Disconnected. Reconnecting in 5s...');
            setTimeout(() => this.connect(), 5000);
        });

        this.ws.on('error', (err) => {
            console.error('[F1Client] Error:', err);
            if (timeout) clearTimeout(timeout);
            if (onReady) onReady();
        });
    }

    sendSubscribe() {
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
        const msg = JSON.stringify({
            type: MSG_INVOCATION,
            invocationId: SUBSCRIBE_INVOCATION_ID,
            target: 'Subscribe',
            arguments: [SUBSCRIBE_CHANNELS]
        });
        this.ws.send(`${msg}${RECORD_SEP}`);
    }

    handleSnapshot(result) {
        if (result.DriverList) this.routeData('DriverList', result.DriverList);
        if (result.TimingAppData) this.routeData('TimingAppData', result.TimingAppData);
        if (result.TimingData) this.routeData('TimingData', result.TimingData);
        if (result.TimingDataF1) this.routeData('TimingDataF1', result.TimingDataF1);
        if (result.SessionInfo) this.routeData('SessionInfo', result.SessionInfo);
        if (result.WeatherData) this.routeData('WeatherData', result.WeatherData);
        if (result.RaceControlMessages) this.routeData('RaceControlMessages', result.RaceControlMessages);
        if (result.LapCount) this.routeData('LapCount', result.LapCount);
        if (result.TeamRadio) this.routeData('TeamRadio', result.TeamRadio);
        // [Race Center addition] Initial snapshot may already contain car positions.
        if (result.CarData) this.routeData('CarData', result.CarData);
        // [Race Center addition] Track status may arrive in the initial snapshot.
        if (result.TrackStatus) this.routeData('TrackStatus', result.TrackStatus);
    }

    /**
     * Routes incoming channel feeds or deltas into the state store using deep merge,
     * preserving all SignalR Core PascalCase field names.
     * @param {string} channel - SignalR channel name.
     * @param {string|Object} dataStr - JSON string or object payload.
     */
    routeData(channel, dataStr) {
        if (!dataStr) return;
        const data = typeof dataStr === 'string' ? JSON.parse(dataStr) : dataStr;

        switch (channel) {
            case 'DriverList':
                deepMerge(this.driverList, data);
                this.broadcast({ type: 'DriverList', data: this.driverList });
                break;
            case 'TimingAppData':
                deepMerge(this.timingAppData, data);
                this.broadcast({ type: 'TimingAppData', data: this.timingAppData });
                break;
            case 'TimingData':
            case 'TimingDataF1':
                deepMerge(this.timingData, data);
                this.broadcast({ type: channel, data: this.timingData });
                break;
            case 'SessionInfo':
                deepMerge(this.session, data);
                this.broadcast({ type: 'SessionInfo', data: this.session });
                break;
            case 'WeatherData':
                deepMerge(this.weather, data);
                this.broadcast({ type: 'WeatherData', data: this.weather });
                break;
            case 'LapCount':
                deepMerge(this.lapCount, data);
                this.broadcast({ type: 'LapCount', data: this.lapCount });
                break;
            case 'RaceControlMessages':
                if (data.Messages) {
                    const msgs = Array.isArray(data.Messages) ? data.Messages : Object.values(data.Messages);
                    this.raceControl = [...this.raceControl, ...msgs].slice(-50);
                    this.broadcast({ type: 'RaceControlMessages', data: this.raceControl });
                }
                break;
            case 'CarData':
                // [Race Center addition] The Entries array is replaced wholesale by the merge
                // engine, which is exactly what we want: the latest state of every car.
                deepMerge(this.carData, data);
                this.broadcast({ type: 'CarData', data: this.carData });
                break;
            case 'Positions':
                // [Race Center addition] Track coordinates (X/Y/Z) of every car.
                // This is the channel that actually carries the positions:
                // `CarData` only carries the telemetry.
                deepMerge(this.positions, data);
                this.broadcast({ type: 'Positions', data: this.positions });
                break;
            case 'TrackStatus':
                // [Race Center addition] Track flags and safety car state.
                deepMerge(this.trackStatus, data);
                this.broadcast({ type: 'TrackStatus', data: this.trackStatus });
                break;
            case 'TeamRadio':
                if (data.Captures) {
                    const caps = Array.isArray(data.Captures) ? data.Captures : Object.values(data.Captures);
                    this.teamRadio = [...this.teamRadio, ...caps].slice(-30);
                    this.broadcast({ type: 'TeamRadio', data: this.teamRadio });
                }
                break;
        }
    }

    // Getters for REST API integration
    getTimingData() {
        return this.timingData;
    }

    getDriverList() {
        return this.driverList;
    }

    getTimingAppData() {
        return this.timingAppData;
    }

    getSessionInfo() {
        return this.session;
    }

    getLapCount() {
        return this.lapCount;
    }

    getWeatherData() {
        return this.weather;
    }

    getRaceControlMessages() {
        return this.raceControl;
    }

    getTeamRadio() {
        return this.teamRadio;
    }

    /**
     * [Race Center addition] Latest known state of every car (positions + telemetry).
     * @returns {Object} The in-memory CarData channel state.
     */
    getCarData() {
        return this.carData;
    }

    /**
     * [Race Center addition] Latest known track coordinates (X/Y/Z) of every car.
     * @returns {Object} The in-memory Positions channel state.
     */
    getPositions() {
        return this.positions;
    }

    /**
     * [Race Center addition] Track flags and safety car state.
     * @returns {Object} The in-memory TrackStatus channel state.
     */
    getTrackStatus() {
        return this.trackStatus;
    }

    getConnectionStatus() {
        return {
            isConnected: this.isConnected,
            lastMessageAt: this.lastMessageAt
        };
    }
}

module.exports = F1LiveClient;
