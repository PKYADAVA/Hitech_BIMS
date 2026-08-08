import React from "react";
import { Text, View } from "react-native";

import { queryClient } from "@/query/queryClient";
import { useAutoSync } from "@/net/autoSync";
import { useSyncSummary } from "@/offline/useSync";
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

/** "1 save" / "3 saves" — the count matters more than the wording. */
const saves = (n: number) => `${n} save${n === 1 ? "" : "s"}`;

/**
 * Says the screen is showing what was kept, not what is true now — and what is
 * still waiting to go the other way.
 *
 * The cache survives on disk, so a register opens on a farm with no signal and
 * looks exactly like a live one. That is the risk worth naming: a supervisor
 * reading yesterday's stock as today's makes a decision on it.
 *
 * Queued saves are named for the same reason. A day's entry filed with no
 * signal is on the phone and nowhere else, and a supervisor who is not told
 * that has no way to know the round is not yet on the ERP.
 */
export function OfflineBar() {
  const state = useAutoSync();
  const outbox = useSyncSummary();
  const styles = useStyles();

  if (state === "online" && !outbox.pending && !outbox.failed) return null;

  if (state === "syncing" || (outbox.syncing && state === "online")) {
    return (
      <View style={[styles.bar, styles.syncing]}>
        <Text style={[styles.text, styles.syncingText]} numberOfLines={1}>
          {outbox.pending
            ? `Back online — sending ${saves(outbox.pending)}…`
            : "Back online — updating from the ERP…"}
        </Text>
      </View>
    );
  }

  // Everything reached the ERP except what it refused. Nothing is waiting on
  // the network, so an offline bar would be telling the user the wrong thing.
  if (state === "online") {
    if (!outbox.failed) return null;
    return (
      <View style={[styles.bar, styles.rejected]}>
        <Text style={[styles.text, styles.rejectedText]} numberOfLines={1}>
          {saves(outbox.failed)} the ERP would not accept — open Menu to review
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
        {outbox.pending ? ` · ${saves(outbox.pending)} waiting to send` : ""}
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
  rejected: { backgroundColor: colors.dangerLight },
  rejectedText: { color: colors.danger },
}));
