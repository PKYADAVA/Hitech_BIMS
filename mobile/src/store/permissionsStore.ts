import { create } from "zustand";

import { ActionKind, fetchPermissions, ModuleActions, MODULE_NAV } from "@/api/permissions";

interface PermState {
  unrestricted: boolean;
  navGroups: Set<string>;
  tabs: Set<string>;
  moduleActions: Record<string, ModuleActions>;
  loaded: boolean;
  load: () => Promise<void>;
  reset: () => void;
  /** Can the user open this mobile module? (fail-open until loaded / on error). */
  canModule: (moduleKey: string) => boolean;
  /** Can the user perform an action (add/edit/delete) in this mobile module? */
  canAction: (moduleKey: string, action: ActionKind) => boolean;
  /** Can the user view a given backend tab code? */
  canTab: (tabCode: string) => boolean;
}

export const usePermissionsStore = create<PermState>((set, get) => ({
  unrestricted: false,
  navGroups: new Set(),
  tabs: new Set(),
  moduleActions: {},
  loaded: false,

  load: async () => {
    try {
      const p = await fetchPermissions();
      set({
        unrestricted: p.unrestricted,
        navGroups: new Set(p.nav_groups),
        tabs: new Set(p.tabs),
        moduleActions: p.module_actions ?? {},
        loaded: true,
      });
    } catch {
      // Fail-open: a transient error must never lock a user out of the app.
      set({ unrestricted: true, loaded: true });
    }
  },

  reset: () =>
    set({ unrestricted: false, navGroups: new Set(), tabs: new Set(), moduleActions: {}, loaded: false }),

  canModule: (moduleKey) => {
    const s = get();
    if (!s.loaded || s.unrestricted) return true;
    const nav = MODULE_NAV[moduleKey];
    return !nav || s.navGroups.has(nav);
  },

  canAction: (moduleKey, action) => {
    const s = get();
    if (!s.loaded || s.unrestricted) return true;
    const nav = MODULE_NAV[moduleKey];
    if (!nav) return true;
    return !!s.moduleActions[nav]?.[action];
  },

  canTab: (tabCode) => {
    const s = get();
    if (!s.loaded || s.unrestricted) return true;
    return s.tabs.has(tabCode);
  },
}));
