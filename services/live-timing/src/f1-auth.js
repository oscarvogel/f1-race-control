/**
 * Autenticacion contra la cuenta de Formula 1.
 *
 * [Race Center addition]
 *
 * El feed de cronometraje entrega los canales de cronometraje (TimingData,
 * SessionInfo, RaceControl...) sin credenciales, pero **las coordenadas y la
 * telemetria por auto** (`Position.z` y `CarData.z`) y los archivos estaticos
 * del feed responden **401** a una conexion anonima. Para obtenerlos hay que
 * iniciar sesion en la cuenta de formula1.com y mandar el token como
 * `Authorization: Bearer`.
 *
 * El flujo es OAuth2 Authorization-Code + PKCE contra el proveedor de identidad
 * de F1 (PingOne), con la variante "DaVinci" del formulario de usuario y
 * contrasena:
 *
 *   1. se lee la configuracion publica del frontend de account.formula1.com
 *      (objeto `davinci:{...}`) para obtener `clientId` y `acrValues`;
 *   2. GET /as/authorize con `response_mode=pi.flow` devuelve el formulario
 *      de inicio de sesion en JSON y la url a la que enviarlo;
 *   3. POST a esa url con usuario y contrasena devuelve el codigo de
 *      autorizacion;
 *   4. POST /as/token cambia el codigo por el token de acceso;
 *   5. el claim `subscriptionToken` de ese token es el que se manda como
 *      Bearer. Sin suscripcion F1TV activa el claim no viene: en ese caso el
 *      timing sigue funcionando y las coordenadas no.
 *
 * Mismo comportamiento que FastF1 (fastf1/internals/f1account).
 *
 * Las credenciales se leen de las variables de entorno `F1_USERNAME` y
 * `F1_PASSWORD`. Nunca se escriben en el codigo ni en el repositorio.
 */

const crypto = require('crypto');

const ACCOUNT_ORIGIN = 'https://account.formula1.com';
const IDP_ORIGIN = 'https://id.formula1.com';
const AUTHORIZE_URL = `${IDP_ORIGIN}/as/authorize`;
const TOKEN_URL = `${IDP_ORIGIN}/as/token`;
const CONFIG_SCRIPT_URL = `${ACCOUNT_ORIGIN}/scripts/main.min.js`;

const USER_AGENT =
  'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 ' +
  '(KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36';

/** Cabecera que le dice al IdP que se speak JSON y no HTML. */
const PING_SDK_HEADERS = { 'X-Requested-With': 'ping-sdk' };

/** Margen para renovar el token antes de que expire (segundos). */
const EXPIRY_MARGIN = 300;

/** Token en memoria: basta con uno por proceso. */
let tokenEnMemoria = null;

/** Jar de cookies minimo: el IdP encadena los pasos con cookies. */
class CookieJar {
  constructor() {
    this.cookies = new Map();
  }

   guardar(response) {
    const lista = typeof response.headers.getSetCookie === 'function'
      ? response.headers.getSetCookie()
      : [response.headers.get('set-cookie') || ''];
    for (const raw of lista) {
      const par = raw.split(';')[0];
      const i = par.indexOf('=');
      if (i > 0) this.cookies.set(par.slice(0, i).trim(), par.slice(i + 1).trim());
    }
  }

  header() {
    return [...this.cookies.entries()].map(([k, v]) => `${k}=${v}`).join('; ');
  }
}

/** Lee el `exp` de un JWT sin verificar la firma. */
function expiryDe(jwt) {
  try {
    const partes = String(jwt).split('.');
    if (partes.length < 2) return null;
    const payload = JSON.parse(Buffer.from(partes[1], 'base64url').toString('utf8'));
    return payload.exp ? Number(payload.exp) : null;
  } catch {
    return null;
  }
}

/** Lee los claims de un JWT sin verificar la firma. */
function claimsDe(jwt) {
  try {
    const partes = String(jwt).split('.');
    if (partes.length < 2) return {};
    return JSON.parse(Buffer.from(partes[1], 'base64url').toString('utf8'));
  } catch {
    return {};
  }
}

/** Extrae clientId y acrValues del bundle publico del frontend de F1. */
function parsearConfig(script) {
  const obj = script.match(/\bdavinci:\{([^}]*)\}/);
  if (!obj) throw new Error('No se encontro la configuracion davinci en el frontend de F1.');
  const campo = (nombre) => {
    const m = obj[1].match(new RegExp(`\\b${nombre}:"([^"]+)"`));
    if (!m) throw new Error(`La configuracion de F1 no trae ${nombre}.`);
    return m[1];
  };
  return { clientId: campo('clientId'), policyId: campo('acrValues') };
}

/** Challenge PKCE S256 (RFC 7636). */
function codeChallenge(verifier) {
  return crypto.createHash('sha256').update(verifier, 'ascii').digest('base64url');
}

/**
 * Hace el inicio de sesion completo.
 *
 * @param {string} usuario
 * @param {string} contrasena
 * @returns {Promise<string>} token de suscripcion (JWT de F1TV)
 */
async function iniciarSesion(usuario, contrasena) {
  const jar = new CookieJar();
  const cabeceras = {
    'User-Agent': USER_AGENT,
    'Accept-Language': 'en-US,en;q=0.9',
  };

  // 1. Configuracion publica del cliente.
  const cfgResp = await fetch(CONFIG_SCRIPT_URL, { headers: cabeceras });
  if (!cfgResp.ok) throw new Error(`No se pudo leer la configuracion de F1 (HTTP ${cfgResp.status}).`);
  jar.guardar(cfgResp);
  const config = parsearConfig(await cfgResp.text());

  // 2. Arranque del flujo DaVinci.
  const verifier = crypto.randomBytes(64).toString('base64url');
  const state = crypto.randomBytes(24).toString('base64url');
  const nonce = crypto.randomBytes(24).toString('base64url');

  const url = new URL(AUTHORIZE_URL);
  url.searchParams.set('client_id', config.clientId);
  url.searchParams.set('response_type', 'code');
  url.searchParams.set('response_mode', 'pi.flow');
  url.searchParams.set('scope', 'openid');
  url.searchParams.set('state', state);
  url.searchParams.set('nonce', nonce);
  url.searchParams.set('code_challenge', codeChallenge(verifier));
  url.searchParams.set('code_challenge_method', 'S256');
  url.searchParams.set('acr_values', config.policyId);

  const authResp = await fetch(url, {
    headers: { ...cabeceras, ...PING_SDK_HEADERS, Cookie: jar.header() },
  });
  jar.guardar(authResp);
  if (!authResp.ok) throw new Error(`El inicio de sesion de F1 fallo (HTTP ${authResp.status}).`);
  const form = await authResp.json();

  const submitUrl = form?._links?.next?.href;
  const interactionId = form?.interactionId;
  const flowId = form?.id;
  const eventName = form?.eventName;
  if (!submitUrl || !submitUrl.startsWith(`${IDP_ORIGIN}/`)) {
    throw new Error('Respuesta inesperada al iniciar el inicio de sesion de F1.');
  }

  // 3. Usuario y contrasena.
  const submitResp = await fetch(submitUrl, {
    method: 'POST',
    headers: {
      ...cabeceras,
      ...PING_SDK_HEADERS,
      interactionId,
      Cookie: jar.header(),
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      id: flowId,
      eventName,
      interactionId,
      parameters: {
        eventType: 'submit',
        data: {
          actionKey: 'SIGNIN',
          formData: { username: usuario, password: contrasena },
        },
      },
    }),
  });
  jar.guardar(submitResp);

  let data;
  try {
    data = await submitResp.json();
  } catch {
    throw new Error('Respuesta inesperada del inicio de sesion de F1.');
  }
  if (data?.status !== 'COMPLETED') {
    throw new Error(
      data?.message || 'El inicio de sesion de F1 fallo: usuario o contrasena incorrectos.'
    );
  }
  const auth = data?.authorizeResponse || {};
  if (auth.state !== state) throw new Error('El inicio de sesion de F1 devolvio un estado inesperado.');
  const code = auth.code;
  if (!code) throw new Error('El inicio de sesion de F1 no devolvio codigo de autorizacion.');

  // 4. Codigo por token de acceso.
  const tokenResp = await fetch(TOKEN_URL, {
    method: 'POST',
    headers: { ...cabeceras, Cookie: jar.header(), 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      grant_type: 'authorization_code',
      client_id: config.clientId,
      code,
      code_verifier: verifier,
    }).toString(),
  });
  if (!tokenResp.ok) throw new Error(`El cambio de codigo por token fallo (HTTP ${tokenResp.status}).`);
  const tokenData = await tokenResp.json();
  const accessToken = tokenData?.access_token;
  if (!accessToken) throw new Error('La respuesta del token de F1 no trae access_token.');

  // 5. El claim `subscriptionToken` es el que se usa como Bearer.
  const claims = claimsDe(accessToken);
  const subscription = claims.subscriptionToken;
  if (!subscription) {
    throw new Error(
      'La cuenta de F1 no tiene una suscripcion F1TV activa: el feed no entrega coordenadas ni telemetria sin ella.'
    );
  }
  return subscription;
}

/**
 * Devuelve el token de suscripcion, iniciando sesion solo si hace falta.
 *
 * @returns {Promise<string|null>} null si no hay credenciales configuradas.
 */
async function getSubscriptionToken() {
  if (tokenEnMemoria) {
    const exp = expiryDe(tokenEnMemoria);
    if (!exp || exp - EXPIRY_MARGIN > Date.now() / 1000) return tokenEnMemoria;
  }

  const usuario = process.env.F1_USERNAME || '';
  const contrasena = process.env.F1_PASSWORD || '';
  if (!usuario || !contrasena) return null;

  try {
    tokenEnMemoria = await iniciarSesion(usuario, contrasena);
    console.log('[F1Auth] Sesion iniciada: el feed puede entregar coordenadas y telemetria.');
    return tokenEnMemoria;
  } catch (error) {
    console.error('[F1Auth] Fallo el inicio de sesion:', error.message);
    return null;
  }
}

module.exports = { getSubscriptionToken, expiryDe, claimsDe };
