import Constants from "expo-constants";

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

export const API_BASE_URL: string =
  process.env.EXPO_PUBLIC_API_BASE_URL ||
  extra.apiBaseUrl ||
  "http://localhost:8000/api/v1";

export const REQUEST_TIMEOUT_MS = 20000;
