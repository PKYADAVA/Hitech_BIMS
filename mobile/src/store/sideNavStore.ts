import { create } from "zustand";

/**
 * Whether the sidebar is showing, and which module it should mark as current.
 *
 * A store rather than local state because the button that opens it lives in a
 * navigator header while the panel renders at the root — there is no common
 * parent to hold a `useState` between them.
 */
interface SideNavState {
  open: boolean;
  /** Key of the module to highlight; "dashboard" on Home. */
  active: string;
  openNav: (active?: string) => void;
  close: () => void;
  setActive: (active: string) => void;
}

export const useSideNav = create<SideNavState>((set) => ({
  open: false,
  active: "dashboard",
  openNav: (active) => set((s) => ({ open: true, active: active ?? s.active })),
  close: () => set({ open: false }),
  setActive: (active) => set({ active }),
}));
