import { http } from "./client";
import { tokenStore } from "./tokenStore";
import { AuthUser, Envelope } from "./types";

/** Fetch the current user's profile (`GET /auth/me`). */
export async function fetchMe(): Promise<AuthUser> {
  const resp = await http.get<Envelope<AuthUser>>("/auth/me");
  return resp.data.data;
}

/**
 * Log out on the server (blacklists the refresh token → per-device logout),
 * then clear local tokens. Server errors are ignored: local logout must always
 * succeed so the user is never trapped in a broken session.
 */
export async function logout(): Promise<void> {
  const refresh = tokenStore.getRefresh();
  try {
    if (refresh) await http.post("/auth/logout", { refresh });
  } catch {
    // ignore — logout is best-effort on the server, guaranteed locally
  } finally {
    await tokenStore.clear();
  }
}
