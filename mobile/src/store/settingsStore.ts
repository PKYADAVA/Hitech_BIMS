import { create } from "zustand";

import { storage } from "@/storage";

const KEY = "app_lock_enabled";

interface SettingsState {
  appLockEnabled: boolean;
  hydrated: boolean;
  hydrate: () => Promise<void>;
  setAppLock: (v: boolean) => Promise<void>;
}

/** Local device preferences (Keychain/Keystore on native, localStorage on web). */
export const useSettingsStore = create<SettingsState>((set) => ({
  appLockEnabled: false,
  hydrated: false,
  hydrate: async () => {
    try {
      const v = await storage.get(KEY);
      set({ appLockEnabled: v === "1", hydrated: true });
    } catch {
      set({ hydrated: true });
    }
  },
  setAppLock: async (v) => {
    await storage.set(KEY, v ? "1" : "0");
    set({ appLockEnabled: v });
  },
}));
