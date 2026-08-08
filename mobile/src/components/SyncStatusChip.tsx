import { useNavigation } from "@react-navigation/native";
import React from "react";
import { Pressable, Text, View } from "react-native";

import { useSyncSummary } from "@/offline/useSync";
import { makeStyles, radius, spacing, type } from "@/theme";

/**
 * The state of the connection and the queue, in the header.
 *
 * Small on purpose. This sits on every screen, and a supervisor filling a
 * round should be able to ignore it — right up to the moment they want to know
 * whether what they just filed has left the phone. It answers that in a glance
 * and opens the Sync Center on a tap; it never interrupts.
 *
 * Online with nothing waiting is the ordinary state, so it says the least
 * there: a quiet green dot rather than a badge competing with the screen title.
 */
export function SyncStatusChip({ tint = "#fff" }: { tint?: string }) {
  const styles = useStyles();
  const navigation = useNavigation<any>();
  const s = useSyncSummary();

  const waiting = s.pending + s.failed + s.conflicts;
  const state = !s.online ? "offline"
    : s.syncing ? "syncing"
    : s.conflicts ? "conflict"
    : s.failed ? "failed"
    : waiting ? "pending"
    : "online";

  const label = {
    offline: waiting ? `Offline · ${waiting}` : "Offline",
    syncing: `Syncing ${s.pending}…`,
    conflict: `${s.conflicts} conflict${s.conflicts === 1 ? "" : "s"}`,
    failed: `${s.failed} failed`,
    pending: `${waiting} pending`,
    online: "Online",
  }[state];

  const dot = {
    offline: styles.dotOffline,
    syncing: styles.dotSyncing,
    conflict: styles.dotFailed,
    failed: styles.dotFailed,
    pending: styles.dotPending,
    online: styles.dotOnline,
  }[state];

  return (
    <Pressable
      onPress={() => navigation.navigate("SyncCenter")}
      hitSlop={10}
      style={[styles.chip, state === "online" && styles.chipQuiet]}
      accessibilityRole="button"
      accessibilityLabel={`${label}. Open Sync Center`}
    >
      <View style={[styles.dot, dot]} />
      <Text style={[styles.text, { color: tint }]} numberOfLines={1}>{label}</Text>
    </Pressable>
  );
}

const useStyles = makeStyles((c) => ({
  chip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingVertical: 3,
    paddingHorizontal: spacing.sm,
    borderRadius: radius.pill ?? 999,
    backgroundColor: "rgba(255,255,255,0.16)",
  },
  // Nothing to report: present, but not asking to be read.
  chipQuiet: { backgroundColor: "transparent" },
  dot: { width: 8, height: 8, borderRadius: 4 },
  dotOnline: { backgroundColor: "#22c55e" },
  dotOffline: { backgroundColor: "#ef4444" },
  dotSyncing: { backgroundColor: "#3b82f6" },
  dotPending: { backgroundColor: "#f59e0b" },
  dotFailed: { backgroundColor: "#ef4444" },
  text: { ...type.caption, fontWeight: "700" },
}));
