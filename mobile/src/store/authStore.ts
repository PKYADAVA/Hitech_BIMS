import { create } from "zustand";

import { logout as apiLogout, fetchMe } from "@/api/auth";
import { requestLogin, setSessionExpiredHandler } from "@/api/client";
import { tokenStore } from "@/api/tokenStore";
import { registerForPush } from "@/push";
import { ApiError, AuthUser } from "@/api/types";
import { setQueueUser } from "@/offline/queue";
import { clearCachedData } from "@/query/cache";

interface AuthState {
  status: "loading" | "signedOut" | "signedIn";
  user: AuthUser | null;
  error: string | null;
  /** Load persisted tokens on app start and resolve the session. */
  bootstrap: () => Promise<void>;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  status: "loading",
  user: null,
  error: null,

  bootstrap: async () => {
    // When a refresh fails deep in the axios layer, drop straight to signedOut.
    setSessionExpiredHandler(() => set({ status: "signedOut", user: null }));

    await tokenStore.hydrate();
    if (!tokenStore.getAccess()) {
      set({ status: "signedOut" });
      return;
    }
    try {
      const user = await fetchMe();
      setQueueUser(String(user.id));
      set({ status: "signedIn", user });
      void registerForPush();
    } catch {
      await tokenStore.clear();
      set({ status: "signedOut" });
    }
  },

  login: async (username, password) => {
    set({ error: null });
    try {
      const result = await requestLogin(username, password);
      await tokenStore.set(result.access, result.refresh);
      // Anything this user queued on a previous session becomes sendable
      // again; anyone else's stays where it is.
      setQueueUser(String(result.user.id));
      set({ status: "signedIn", user: result.user });
      // Registered after sign-in, not at launch: the token is stored against
      // the user, and posting it before there is a session would 401.
      void registerForPush();
    } catch (e) {
      const message =
        e instanceof ApiError && e.code === "not_authenticated"
          ? "Incorrect username or password."
          : e instanceof ApiError
          ? e.message
          : "Unable to sign in. Check your connection.";
      set({ error: message });
      throw e;
    }
  },

  logout: async () => {
    await apiLogout();
    // The read cache is on disk and outlives the session. Left there, the next
    // person to sign in on this handset opens a register and sees the last
    // one's farms — data their own scope may never have allowed them. Clearing
    // is part of signing out, not a nicety.
    await clearCachedData();
    // The outbox is deliberately NOT cleared. A day's entry saved with no
    // signal exists nowhere else, and a supervisor ending their shift before
    // reaching signal would lose the round. Detaching the user is enough:
    // the writes stay on disk and go when that user signs in again, never
    // under the next person's token.
    setQueueUser(null);
    set({ status: "signedOut", user: null, error: null });
  },
}));
