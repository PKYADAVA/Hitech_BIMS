import * as SecureStore from "expo-secure-store";
import { create } from "zustand";

const KEY = "app_lock_enabled";

interface SettingsState {
  appLockEnabled: boolean;
  hydrated: boolean;
  hydrate: () => Promise<void>;
  setAppLock: (v: boolean) => Promise<void>;
}

/** Local device preferences (persisted in the Keychain/Keystore via SecureStore). */
export const useSettingsStore = create<SettingsState>((set) => ({
  appLockEnabled: false,
  hydrated: false,
  hydrate: async () => {
    try {
      const v = await SecureStore.getItemAsync(KEY);
      set({ appLockEnabled: v === "1", hydrated: true });
    } catch {
      set({ hydrated: true });
    }
  },
  setAppLock: async (v) => {
    await SecureStore.setItemAsync(KEY, v ? "1" : "0");
    set({ appLockEnabled: v });
  },
}));
