import { create } from "zustand";

import { fetchPermissions, MODULE_NAV } from "@/api/permissions";

interface PermState {
  unrestricted: boolean;
  navGroups: Set<string>;
  tabs: Set<string>;
  loaded: boolean;
  load: () => Promise<void>;
  reset: () => void;
  /** Can the user open this mobile module? (fail-open until loaded / on error). */
  canModule: (moduleKey: string) => boolean;
  /** Can the user view a given backend tab code? */
  canTab: (tabCode: string) => boolean;
}

export const usePermissionsStore = create<PermState>((set, get) => ({
  unrestricted: false,
  navGroups: new Set(),
  tabs: new Set(),
  loaded: false,

  load: async () => {
    try {
      const p = await fetchPermissions();
      set({
        unrestricted: p.unrestricted,
        navGroups: new Set(p.nav_groups),
        tabs: new Set(p.tabs),
        loaded: true,
      });
    } catch {
      // Fail-open: a transient error must never lock a user out of the app.
      set({ unrestricted: true, loaded: true });
    }
  },

  reset: () => set({ unrestricted: false, navGroups: new Set(), tabs: new Set(), loaded: false }),

  canModule: (moduleKey) => {
    const s = get();
    if (!s.loaded || s.unrestricted) return true;
    const nav = MODULE_NAV[moduleKey];
    return !nav || s.navGroups.has(nav);
  },

  canTab: (tabCode) => {
    const s = get();
    if (!s.loaded || s.unrestricted) return true;
    return s.tabs.has(tabCode);
  },
}));
