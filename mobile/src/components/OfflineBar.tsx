import React from "react";
import { Text, View } from "react-native";

import { queryClient } from "@/query/queryClient";
import { useAutoSync } from "@/net/autoSync";
import { makeStyles, spacing, type } from "@/theme";

/**
 * When the last answer from the server arrived.
 *
 * Read off the cache rather than kept in a store of its own: every query
 * already records when its data landed, and a second bookkeeping copy is one
 * more thing that can disagree with what is on screen.
 */
export function lastSyncedAt(): number | null {
  const times = queryClient.getQueryCache().getAll()
    .map((q) => q.state.dataUpdatedAt)
    .filter((t) => t > 0);
  return times.length ? Math.max(...times) : null;
}

/** "10:42" today, "Tue 10:42" earlier in the week, else a date. */
function when(ts: number): string {
  const at = new Date(ts);
  const time = at.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  const days = Math.floor((Date.now() - ts) / 86_400_000);
  if (days < 1) return time;
  if (days < 7) return `${at.toLocaleDateString(undefined, { weekday: "short" })} ${time}`;
  return at.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/**
 * Says the screen is showing what was kept, not what is true now.
 *
 * The cache survives on disk, so a register opens on a farm with no signal and
 * looks exactly like a live one. That is the risk worth naming: a supervisor
 * reading yesterday's stock as today's makes a decision on it. The bar says
 * when the figures came from, and disappears the moment the connection does.
 */
export function OfflineBar() {
  const state = useAutoSync();
  const styles = useStyles();
  if (state === "online") return null;

  if (state === "syncing") {
    return (
      <View style={[styles.bar, styles.syncing]}>
        <Text style={[styles.text, styles.syncingText]} numberOfLines={1}>
          Back online — updating from the ERP…
        </Text>
      </View>
    );
  }

  const synced = lastSyncedAt();
  return (
    <View style={styles.bar}>
      <Text style={styles.text} numberOfLines={1}>
        Offline — showing saved data
        {synced ? ` · last synced ${when(synced)}` : ""}
      </Text>
    </View>
  );
}

const useStyles = makeStyles((colors) => ({
  bar: {
    backgroundColor: colors.warningLight,
    paddingVertical: spacing.xs,
    paddingHorizontal: spacing.md,
  },
  text: { ...type.caption, color: "#8a5a00", textAlign: "center", fontWeight: "700" },
  syncing: { backgroundColor: colors.infoLight },
  syncingText: { color: colors.info },
}));
