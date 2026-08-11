import Constants from "expo-constants";
import { Platform } from "react-native";

/**
 * API base URL resolution order:
 *   1. EXPO_PUBLIC_API_BASE_URL env var (set in .env or the shell)
 *   2. app.json -> expo.extra.apiBaseUrl
 *   3. localhost fallback (simulator only)
 *
 * On a physical device, localhost points at the phone itself — set
 * EXPO_PUBLIC_API_BASE_URL to your machine's LAN IP, e.g.
 *   EXPO_PUBLIC_API_BASE_URL=http://192.168.1.20:8000/api/v1
 * and add that host to Django's ALLOWED_HOSTS.
 */
const extra = (Constants.expoConfig?.extra ?? {}) as { apiBaseUrl?: string };

const absoluteBaseUrl =
  process.env.EXPO_PUBLIC_API_BASE_URL ||
  extra.apiBaseUrl ||
  "http://localhost:8000/api/v1";

/** Path-only form of the base URL, e.g. "https://host/api/v1" -> "/api/v1". */
function toProxyPath(url: string): string {
  try {
    return new URL(url).pathname.replace(/\/$/, "");
  } catch {
    return "/api/v1";
  }
}

/**
 * Web talks to a same-origin path; native calls the API directly.
 *
 * The browser enforces CORS and the backend sends no Access-Control-* headers,
 * so a cross-origin call from the dev server is blocked before the app sees a
 * response. The Metro dev server proxies this path to the real backend (see
 * metro.config.js), which keeps the request same-origin so CORS never applies.
 */
export const API_BASE_URL: string =
  Platform.OS === "web" ? toProxyPath(absoluteBaseUrl) : absoluteBaseUrl;

/** The API's path prefix, e.g. "/api/v1" — what `API_BASE_URL` contributes to
 *  a request path, whichever platform resolved it. */
export const API_PATH_PREFIX: string = toProxyPath(absoluteBaseUrl);

/**
 * Where uploaded files live, e.g. "http://localhost:8000".
 *
 * Always absolute, unlike API_BASE_URL. A stored file's url comes back
 * server-relative ("/media/..."), and on web the API is reached through a
 * same-origin proxy path — so resolving media against *that* points the
 * browser at the Metro dev server, which serves no media and renders every
 * photograph as a blank tile. CORS does not apply here: an <img> loads
 * cross-origin freely, it is only XHR the browser guards.
 */
export const MEDIA_BASE_URL: string =
  absoluteBaseUrl.replace(/\/api\/v1\/?$/, "");

/**
 * A server-built link, re-pointed at the base URL this app was configured with.
 *
 * DRF writes pagination `next`/`previous` as absolute URLs, using whatever host
 * Django saw the request arrive on. Behind the web build's proxy that is the
 * backend's own address, not the origin the page is served from — so following
 * the link verbatim leaves the proxy, becomes cross-origin, and the browser
 * blocks it before the app sees a response. That is the CORS problem the proxy
 * exists to avoid, re-entered through the back door on the second page of every
 * list long enough to have one.
 *
 * Only the path and query survive; the host is the server's opinion about
 * itself and no business of the client's.
 */
export function toApiPath(link: string): string {
  // An empty link resolves to "/", which would ask for the API root instead of
  // failing — worse than handing back what came in.
  if (!link) return link;
  try {
    const url = new URL(link, "http://placeholder");
    const path = url.pathname.startsWith(API_PATH_PREFIX)
      ? url.pathname.slice(API_PATH_PREFIX.length)
      : url.pathname;
    return `${path}${url.search}`;
  } catch {
    return link;
  }
}

export const REQUEST_TIMEOUT_MS = 20000;

/** This build's own version, as shipped — read from app.json rather than
 *  hand-kept in sync with it, so a screen that shows it can never drift from
 *  what was actually built. */
export const APP_VERSION: string = Constants.expoConfig?.version ?? "0.0.0";
export const APP_VERSION_CODE: number = Constants.expoConfig?.android?.versionCode ?? 0;