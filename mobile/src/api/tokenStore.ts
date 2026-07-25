import * as SecureStore from "expo-secure-store";

/**
 * Persists JWT tokens in the device keychain/keystore (via expo-secure-store),
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
    accessToken = await SecureStore.getItemAsync(ACCESS_KEY);
    refreshToken = await SecureStore.getItemAsync(REFRESH_KEY);
  },

  getAccess(): string | null {
    return accessToken;
  },

  getRefresh(): string | null {
    return refreshToken;
  },

  async set(access: string, refresh?: string): Promise<void> {
    accessToken = access;
    await SecureStore.setItemAsync(ACCESS_KEY, access);
    if (refresh) {
      refreshToken = refresh;
      await SecureStore.setItemAsync(REFRESH_KEY, refresh);
    }
  },

  async clear(): Promise<void> {
    accessToken = null;
    refreshToken = null;
    await SecureStore.deleteItemAsync(ACCESS_KEY);
    await SecureStore.deleteItemAsync(REFRESH_KEY);
  },
};
