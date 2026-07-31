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

export const REQUEST_TIMEOUT_MS = 20000;
