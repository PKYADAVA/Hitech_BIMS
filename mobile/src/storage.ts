import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";

/**
 * Platform-aware key/value storage for small secrets (JWTs, device prefs).
 *
 * Native uses expo-secure-store (Keychain / Keystore). SecureStore ships no web
 * implementation and throws in the browser, so web falls back to localStorage.
 * That fallback is NOT encrypted at rest — it exists so the app is runnable in a
 * browser for development, not as a security-equivalent path.
 *
 * `get` deliberately swallows read errors and returns null: callers treat a null
 * token as "signed out", which degrades to the login screen. Letting it throw
 * strands `authStore.bootstrap()` on its unguarded await and the app hangs on the
 * splash screen with nothing rendered.
 */
const isWeb = Platform.OS === "web";

export const storage = {
  async get(key: string): Promise<string | null> {
    try {
      return isWeb
        ? window.localStorage.getItem(key)
        : await SecureStore.getItemAsync(key);
    } catch {
      return null;
    }
  },

  async set(key: string, value: string): Promise<void> {
    if (isWeb) {
      window.localStorage.setItem(key, value);
      return;
    }
    await SecureStore.setItemAsync(key, value);
  },

  async remove(key: string): Promise<void> {
    if (isWeb) {
      window.localStorage.removeItem(key);
      return;
    }
    await SecureStore.deleteItemAsync(key);
  },
};
