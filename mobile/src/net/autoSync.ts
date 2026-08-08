import { onlineManager } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { queryClient } from "@/query/queryClient";
import { usePermissionsStore } from "@/store/permissionsStore";

/**
 * Bring everything up to date the moment the connection comes back.
 *
 * React Query refetches the queries a screen is *currently showing* on
 * reconnect, which is not enough here: a supervisor walks a round of sheds
 * offline and comes back into signal on a screen that happens to be showing
 * nothing. Every other register would stay on yesterday's figures until it was
 * next opened, and look no different from live.
 *
 * So the whole cache is invalidated. The visible screens refetch at once; the
 * rest are marked stale and refresh as they are opened. Permissions ride along
 * — an access change made while the phone was out of signal should apply on
 * the next glance, not the next login.
 */
export function useAutoSync(): "offline" | "syncing" | "online" {
  const [state, setState] = useState<"offline" | "syncing" | "online">(
    onlineManager.isOnline() ? "online" : "offline");

  useEffect(() => {
    let wasOnline = onlineManager.isOnline();
    let live = true;

    const unsubscribe = onlineManager.subscribe((online) => {
      if (!live) return;
      // Only the crossing matters. onlineManager also fires when a listener is
      // re-attached, and re-syncing on every one of those would refetch the
      // whole cache for nothing.
      if (online && !wasOnline) {
        setState("syncing");
        Promise.allSettled([
          queryClient.invalidateQueries(),
          usePermissionsStore.getState().refresh(),
        ]).then(() => {
          if (live) setState("online");
        });
      } else if (!online) {
        setState("offline");
      }
      wasOnline = online;
    });

    return () => {
      live = false;
      unsubscribe();
    };
  }, []);

  return state;
}
