import { storage } from "@/storage";

/**
 * Persists JWT tokens in the device keychain/keystore (localStorage on web),
 * with an in-memory mirror so the axios request interceptor can attach the
 * access token synchronously without awaiting secure storage on every call.
 */
const ACCESS_KEY = "bims_access";
const REFRESH_KEY = "bims_refresh";

let accessToken: string | null = null;
let refreshToken: string | null = null;

export const tokenStore = {
  /** Load tokens from secure storage into memory (call once on app start). */
  async hydrate(): Promise<void> {
    accessToken = await storage.get(ACCESS_KEY);
    refreshToken = await storage.get(REFRESH_KEY);
  },

  getAccess(): string | null {
    return accessToken;
  },

  getRefresh(): string | null {
    return refreshToken;
  },

  async set(access: string, refresh?: string): Promise<void> {
    accessToken = access;
    await storage.set(ACCESS_KEY, access);
    if (refresh) {
      refreshToken = refresh;
      await storage.set(REFRESH_KEY, refresh);
    }
  },

  async clear(): Promise<void> {
    accessToken = null;
    refreshToken = null;
    await storage.remove(ACCESS_KEY);
    await storage.remove(REFRESH_KEY);
  },
};
