import { onlineManager } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";

import { isSyncing, runSync, watchSync } from "./engine";
import { subscribeToQueue, summarise } from "./queue";
import { SyncProgress } from "./engine";
import { SyncSummary } from "./types";

const EMPTY: SyncSummary = {
  online: true, syncing: false, pending: 0, failed: 0, conflicts: 0,
  synced: 0, byType: [], lastSyncAt: null,
};

/**
 * The counters, kept current, for whatever wants to show them.
 *
 * One subscription serves the header chip, the sidebar badge and the Sync
 * Center, so the three can never disagree about how many entries are waiting —
 * which they would if each counted for itself.
 */
export function useSyncSummary(): SyncSummary {
  const [summary, setSummary] = useState<SyncSummary>(EMPTY);

  const refresh = useCallback(async () => {
    setSummary(await summarise(onlineManager.isOnline(), isSyncing()));
  }, []);

  useEffect(() => {
    void refresh();
    const offQueue = subscribeToQueue(() => { void refresh(); });
    const offSync = watchSync(() => { void refresh(); });
    const offOnline = onlineManager.subscribe(() => { void refresh(); });
    return () => {
      offQueue();
      offSync();
      offOnline();
    };
  }, [refresh]);

  return summary;
}

/** Live progress while a run is going, or null when it is not. */
export function useSyncProgress(): SyncProgress | null {
  const [progress, setProgress] = useState<SyncProgress | null>(null);
  useEffect(() => watchSync(setProgress), []);
  return progress;
}

/** Start a run by hand. Resolves when it has finished. */
export function syncNow() {
  return runSync();
}
