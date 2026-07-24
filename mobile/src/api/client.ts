import axios, {
  AxiosError,
  AxiosInstance,
  AxiosResponse,
  InternalAxiosRequestConfig,
} from "axios";

import { API_BASE_URL, REQUEST_TIMEOUT_MS } from "@/config";
import { tokenStore } from "./tokenStore";
import { ApiError, ApiErrorBody, Envelope, LoginResult } from "./types";

/**
 * The single axios instance for the whole app.
 *
 * Request interceptor  -> attaches `Authorization: Bearer <access>`.
 * Response interceptor -> on a 401 it performs a *single-flight* refresh
 *   (concurrent 401s share one refresh call), updates the stored tokens, and
 *   replays the original request. If refresh fails, it clears the session and
 *   notifies the app to route back to Login. All other errors are normalized
 *   into an `ApiError` carrying the envelope's {code, message, fields}.
 */
export const http: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: REQUEST_TIMEOUT_MS,
  headers: { "Content-Type": "application/json" },
});

// --- session-expiry callback (registered by the auth store) --------------- //
let onSessionExpired: (() => void) | null = null;
export function setSessionExpiredHandler(fn: () => void): void {
  onSessionExpired = fn;
}

// --- request: attach bearer ------------------------------------------------ //
http.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = tokenStore.getAccess();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// --- single-flight refresh ------------------------------------------------- //
let refreshPromise: Promise<string> | null = null;

async function refreshAccessToken(): Promise<string> {
  const refresh = tokenStore.getRefresh();
  if (!refresh) throw new Error("No refresh token");

  // A bare axios call (no interceptors) avoids recursion on the refresh call.
  const resp = await axios.post<Envelope<{ access: string; refresh?: string }>>(
    `${API_BASE_URL}/auth/refresh`,
    { refresh },
    { timeout: REQUEST_TIMEOUT_MS }
  );
  const data = resp.data.data;
  await tokenStore.set(data.access, data.refresh);
  return data.access;
}

// --- response: envelope errors + auto refresh ------------------------------ //
http.interceptors.response.use(
  (response: AxiosResponse) => response,
  async (error: AxiosError<Envelope<unknown>>) => {
    const original = error.config as InternalAxiosRequestConfig & { _retried?: boolean };
    const status = error.response?.status;

    // Attempt one transparent refresh + replay on 401.
    if (status === 401 && original && !original._retried && tokenStore.getRefresh()) {
      original._retried = true;
      try {
        refreshPromise = refreshPromise ?? refreshAccessToken();
        const newAccess = await refreshPromise;
        refreshPromise = null;
        original.headers.Authorization = `Bearer ${newAccess}`;
        return http(original);
      } catch {
        refreshPromise = null;
        await tokenStore.clear();
        onSessionExpired?.();
      }
    }

    throw toApiError(error);
  }
);

function toApiError(error: AxiosError<Envelope<unknown>>): ApiError {
  const body = error.response?.data?.error as ApiErrorBody | undefined;
  if (body) return new ApiError(body, error.response?.status);
  return new ApiError(
    { code: "network_error", message: error.message || "Network error", fields: {} },
    error.response?.status
  );
}

/** Login hits the token endpoint directly (no bearer yet). */
export async function requestLogin(username: string, password: string): Promise<LoginResult> {
  const resp = await http.post<Envelope<LoginResult>>("/auth/login", { username, password });
  return resp.data.data;
}
