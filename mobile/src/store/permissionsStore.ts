import { create } from "zustand";

import {
  ActionKind,
  fetchPermissions,
  ModuleActions,
  MODULE_NAV,
  RESOURCE_TABS,
  TabActions,
} from "@/api/permissions";

interface PermState {
  unrestricted: boolean;
  navGroups: Set<string>;
  navOrder: string[];
  tabs: Set<string>;
  moduleActions: Record<string, ModuleActions>;
  tabActions: Record<string, TabActions>;
  loaded: boolean;
  load: () => Promise<void>;
  /** Re-read permissions, keeping the last known answer on failure. */
  refresh: () => Promise<void>;
  reset: () => void;
  /** Can the user open this mobile module? (fail-open until loaded / on error). */
  canModule: (moduleKey: string) => boolean;
  /** Can the user perform an action (add/edit/delete) in this mobile module? */
  canAction: (moduleKey: string, action: ActionKind) => boolean;
  /** Can the user view a given backend tab code? */
  canTab: (tabCode: string) => boolean;
  /** Can the user perform an action on one screen? Prefer over canAction. */
  canTabAction: (tabCode: string, action: ActionKind | "view") => boolean;
  /** Module keys in home-hub order. */
  moduleOrder: () => string[];
  /**
   * Can the user perform an action on one resource screen?
   *
   * This is what UI should call. `canAction` is module-wide and answers true
   * when *any* screen in the module allows it, so gating an Edit button on it
   * shows the button on every screen in the module — including the ones where
   * Mobile Access has just switched Edit off.
   */
  canResource: (resourceKey: string, moduleKey: string, action: ActionKind) => boolean;
}

export const usePermissionsStore = create<PermState>((set, get) => ({
  unrestricted: false,
  navGroups: new Set(),
  navOrder: [],
  tabs: new Set(),
  moduleActions: {},
  tabActions: {},
  loaded: false,

  load: async () => {
    try {
      const p = await fetchPermissions();
      set({
        unrestricted: p.unrestricted,
        navGroups: new Set(p.nav_groups),
        navOrder: p.nav_order ?? [],
        tabs: new Set(p.tabs),
        moduleActions: p.module_actions ?? {},
        tabActions: p.tab_actions ?? {},
        loaded: true,
      });
    } catch {
      // Fail-open: a transient error must never lock a user out of the app.
      // Only on the *first* load though — see refresh(), which keeps the last
      // known answer rather than throwing the doors open on a flaky network.
      if (!get().loaded) set({ unrestricted: true, loaded: true });
    }
  },

  /**
   * Re-read permissions without the fail-open.
   *
   * Called when the app returns to the foreground, so an access change takes
   * effect without a re-login — the store used to load once and cache until
   * the session ended, which meant revoking access did nothing until logout.
   * A failure here keeps what we already had: falling open on a dropped
   * connection would *widen* access, which is the wrong way to fail once we
   * have a real answer.
   */
  refresh: async () => {
    try {
      const p = await fetchPermissions();
      set({
        unrestricted: p.unrestricted,
        navGroups: new Set(p.nav_groups),
        navOrder: p.nav_order ?? [],
        tabs: new Set(p.tabs),
        moduleActions: p.module_actions ?? {},
        tabActions: p.tab_actions ?? {},
        loaded: true,
      });
    } catch {
      // keep the last known state
    }
  },

  reset: () =>
    set({
      unrestricted: false,
      navGroups: new Set(),
      navOrder: [],
      tabs: new Set(),
      moduleActions: {},
      tabActions: {},
      loaded: false,
    }),

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

  /**
   * Can the user perform an action on one *screen*?
   *
   * Prefer this over `canAction` for anything inside a module: the module-wide
   * flags are true when *any* screen allows the action, so hiding an Edit
   * button from them would leave it on every screen in the module. Falls back
   * to the module flags for a screen the server did not send actions for.
   */
  canTabAction: (tabCode, action) => {
    const s = get();
    if (!s.loaded || s.unrestricted) return true;
    const perms = s.tabActions[tabCode];
    if (!perms) return s.tabs.has(tabCode);
    return !!perms[action];
  },

  /** Module keys in the order the home hub should lay them out. */
  moduleOrder: () => get().navOrder,

  canResource: (resourceKey, moduleKey, action) => {
    const s = get();
    if (!s.loaded || s.unrestricted) return true;
    const tab = RESOURCE_TABS[resourceKey];
    // A screen with no tab mapped, or one the server sent no actions for, is
    // not something Mobile Access claims to govern — fall back to the module
    // rather than refusing something nobody decided to refuse.
    if (!tab || !s.tabActions[tab]) return s.canAction(moduleKey, action);
    return !!s.tabActions[tab][action];
  },
}));
