import { onlineManager } from "@tanstack/react-query";
import React, { useCallback, useEffect, useState } from "react";
import { Pressable, RefreshControl, ScrollView, Text, View } from "react-native";

import { AppIcon } from "@/components/AppIcon";
import { Loading } from "@/components/ui";
import {
  discardEntry, resolveConflict, retryAllFailed, retryEntry, runSync,
} from "@/offline/engine";
import { listEntries, subscribeToQueue } from "@/offline/queue";
import { OfflineEntry, SyncStatus } from "@/offline/types";
import { useSyncProgress, useSyncSummary } from "@/offline/useSync";
import { makeStyles, radius, spacing, type } from "@/theme";
import { confirm, notify } from "@/ui/confirm";

/**
 * Everything this phone is holding, and the state of getting it to the ERP.
 *
 * The header chip says a number; this is where the number becomes a list a
 * supervisor can act on. Three questions have to be answerable here without
 * anyone explaining synchronisation: is my round safe, has it gone, and if not
 * why not.
 */

const STATUS_LOOK: Record<SyncStatus, { dot: string; text: string }> = {
  pending: { dot: "#f59e0b", text: "Pending" },
  syncing: { dot: "#3b82f6", text: "Syncing" },
  synced: { dot: "#22c55e", text: "Synced" },
  failed: { dot: "#ef4444", text: "Failed" },
  conflict: { dot: "#a855f7", text: "Conflict" },
};

export function SyncCenterScreen() {
  const styles = useStyles();
  const summary = useSyncSummary();
  const progress = useSyncProgress();
  const [entries, setEntries] = useState<OfflineEntry[] | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => setEntries(await listEntries()), []);

  useEffect(() => {
    void reload();
    return subscribeToQueue(() => { void reload(); });
  }, [reload]);

  const sync = async () => {
    if (!onlineManager.isOnline()) {
      await notify("No connection",
        "Nothing can be sent right now. Your entries are safely stored on this " +
        "device and will sync automatically once you are back in range.");
      return;
    }
    setBusy(true);
    try {
      const { sent, failed, conflicts } = await runSync();
      if (!sent && !failed && !conflicts) {
        await notify("Nothing to send", "Everything on this phone is already on the ERP.");
      } else {
        await notify(
          failed || conflicts ? "Sync finished with issues" : "Sync complete",
          [sent ? `${sent} ${sent === 1 ? "entry" : "entries"} sent.` : "",
           failed ? `${failed} could not be sent.` : "",
           conflicts ? `${conflicts} need${conflicts === 1 ? "s" : ""} your decision.` : ""]
            .filter(Boolean).join("\n"));
      }
    } finally {
      setBusy(false);
    }
  };

  const drop = async (entry: OfflineEntry) => {
    if (!(await confirm({
      title: "Discard this entry?",
      message: `${entry.transaction_label} ${entry.offline_no} has not reached the ` +
        "ERP. Discarding means this record is gone for good — it exists nowhere else.",
      confirmLabel: "Discard",
      destructive: true,
    }))) return;
    await discardEntry(entry.local_id);
  };

  if (entries === null) return <Loading label="Reading your entries…" />;

  const groups: { status: SyncStatus; title: string; note?: string }[] = [
    { status: "conflict", title: "Needs your decision",
      note: "The ERP already holds a different figure. Nothing is overwritten " +
            "until you choose." },
    { status: "failed", title: "Could not be sent",
      note: "Still stored on this phone. Fix the cause on the ERP, then try again." },
    { status: "syncing", title: "Sending" },
    { status: "pending", title: "Waiting to sync" },
    { status: "synced", title: "Sent to the ERP" },
  ];

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={false} onRefresh={reload} />}
    >
      <View style={styles.card}>
        <View style={styles.connRow}>
          <View style={[styles.dot, { backgroundColor: summary.online ? "#22c55e" : "#ef4444" }]} />
          <Text style={styles.connText}>{summary.online ? "Online" : "Offline"}</Text>
          {summary.lastSyncAt ? (
            <Text style={styles.connWhen}>Last sync {shortTime(summary.lastSyncAt)}</Text>
          ) : null}
        </View>

        <View style={styles.counters}>
          <Counter label="Pending" value={summary.pending} tone="#f59e0b" />
          <Counter label="Failed" value={summary.failed} tone="#ef4444" />
          <Counter label="Conflicts" value={summary.conflicts} tone="#a855f7" />
          <Counter label="Synced" value={summary.synced} tone="#22c55e" />
        </View>

        {progress ? (
          <Text style={styles.progress}>
            {progress.done} / {progress.total}
            {progress.current ? ` · ${progress.current.transaction_label}` : ""}
          </Text>
        ) : null}

        <Pressable
          onPress={sync}
          disabled={busy || summary.syncing || !summary.pending}
          style={[styles.syncBtn,
                  (busy || summary.syncing || !summary.pending) && styles.syncBtnOff]}
          accessibilityRole="button"
        >
          <AppIcon name="sync" size={16} color="#fff" />
          <Text style={styles.syncText}>
            {busy || summary.syncing ? "Syncing…" : "Sync Now"}
          </Text>
        </Pressable>
      </View>

      {summary.byType.length ? (
        <View style={styles.card}>
          <Text style={styles.cardTitle}>Pending by type</Text>
          {summary.byType.map((t) => (
            <View key={t.type} style={styles.typeRow}>
              <Text style={styles.typeName}>{t.label}</Text>
              <Text style={styles.typeCount}>{t.count}</Text>
            </View>
          ))}
        </View>
      ) : null}

      {summary.failed ? (
        <Pressable onPress={retryAllFailed} style={styles.retryAll} accessibilityRole="button">
          <AppIcon name="refresh" size={14} color="#2563eb" />
          <Text style={styles.retryAllText}>Try all failed entries again</Text>
        </Pressable>
      ) : null}

      {!entries.length ? (
        <View style={styles.empty}>
          <AppIcon name="cloud-check-outline" size={40} color="#94a3b8" />
          <Text style={styles.emptyTitle}>Everything is on the ERP</Text>
          <Text style={styles.emptyText}>
            Anything you save without a signal is stored here until there is one.
          </Text>
        </View>
      ) : null}

      {groups.map(({ status, title, note }) => {
        const rows = entries.filter((e) => e.sync_status === status);
        if (!rows.length) return null;
        return (
          <View key={status}>
            <Text style={styles.section}>{title}</Text>
            {note ? <Text style={styles.sectionNote}>{note}</Text> : null}
            {rows.map((e) => (
              <EntryCard
                key={e.local_id}
                entry={e}
                onDiscard={() => drop(e)}
                onRetry={status === "failed" ? () => retryEntry(e.local_id) : undefined}
                onResolve={status === "conflict"
                  ? (choice) => resolveConflict(e.local_id, choice)
                  : undefined}
              />
            ))}
          </View>
        );
      })}
    </ScrollView>
  );
}

function Counter({ label, value, tone }: { label: string; value: number; tone: string }) {
  const styles = useStyles();
  return (
    <View style={styles.counter}>
      <Text style={[styles.counterValue, value > 0 && { color: tone }]}>{value}</Text>
      <Text style={styles.counterLabel}>{label}</Text>
    </View>
  );
}

/** "09:12" today, else "8 Aug 09:12" — a round is read against its own day. */
function shortTime(iso: string): string {
  const at = new Date(iso);
  const time = at.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  const sameDay = at.toDateString() === new Date().toDateString();
  return sameDay ? time
    : `${at.toLocaleDateString(undefined, { day: "numeric", month: "short" })} ${time}`;
}

function EntryCard({
  entry, onDiscard, onRetry, onResolve,
}: {
  entry: OfflineEntry;
  onDiscard: () => void;
  onRetry?: () => void;
  onResolve?: (choice: "server" | "local") => void;
}) {
  const styles = useStyles();
  const look = STATUS_LOOK[entry.sync_status];
  const where = [entry.farm_id && `Farm ${entry.farm_id}`,
                 entry.shed_id && `Shed ${entry.shed_id}`,
                 entry.batch_id && `Batch ${entry.batch_id}`]
    .filter(Boolean).join(" · ");

  return (
    <View style={styles.entry}>
      <View style={styles.entryHead}>
        <View style={[styles.dot, { backgroundColor: look.dot }]} />
        <Text style={styles.entryTitle} numberOfLines={1}>{entry.transaction_label}</Text>
        <Text style={styles.entryStatus}>{look.text}</Text>
      </View>

      {/* The offline number is what a supervisor reads out when the office
          asks which entry they mean, so it is on the card, not buried. */}
      <Text style={styles.entryNo}>
        {entry.offline_no}
        {entry.server_id ? `  →  ${entry.server_id}` : ""}
      </Text>

      <Text style={styles.entryMeta}>
        Filled {shortTime(entry.device_created_at)}
        {entry.transaction_date ? ` · for ${entry.transaction_date}` : ""}
      </Text>
      {where ? <Text style={styles.entryMeta}>{where}</Text> : null}
      {entry.files.length ? (
        <Text style={styles.entryMeta}>
          {entry.files.length} photo{entry.files.length === 1 ? "" : "s"}
        </Text>
      ) : null}
      {entry.gps_latitude != null ? (
        <Text style={styles.entryMeta}>
          GPS captured{entry.gps_accuracy ? ` · ${Math.round(entry.gps_accuracy)} m` : ""}
        </Text>
      ) : null}
      {entry.sync_attempts > 0 ? (
        <Text style={styles.entryMeta}>
          {entry.sync_attempts} attempt{entry.sync_attempts === 1 ? "" : "s"}
          {entry.last_sync_at ? ` · last ${shortTime(entry.last_sync_at)}` : ""}
        </Text>
      ) : null}
      {entry.sync_error ? (
        <Text style={styles.entryError} numberOfLines={3}>{entry.sync_error}</Text>
      ) : null}

      {entry.conflict ? (
        <View style={styles.conflict}>
          {entry.conflict.fields.map((f) => (
            <View key={f.field} style={styles.conflictRow}>
              <Text style={styles.conflictLabel}>{f.label}</Text>
              <Text style={styles.conflictValue}>ERP {f.server}</Text>
              <Text style={styles.conflictValue}>Yours {f.local}</Text>
            </View>
          ))}
        </View>
      ) : null}

      <View style={styles.actions}>
        {onResolve ? (
          <>
            <Pressable onPress={() => onResolve("server")} style={styles.action}>
              <Text style={styles.actionText}>Keep ERP</Text>
            </Pressable>
            <Pressable onPress={() => onResolve("local")} style={styles.action}>
              <Text style={styles.actionText}>Accept mine</Text>
            </Pressable>
          </>
        ) : null}
        {onRetry ? (
          <Pressable onPress={onRetry} style={styles.action}>
            <AppIcon name="refresh" size={14} color="#2563eb" />
            <Text style={styles.actionText}>Try again</Text>
          </Pressable>
        ) : null}
        {entry.sync_status !== "synced" ? (
          <Pressable onPress={onDiscard} style={styles.action}>
            <AppIcon name="trash-can-outline" size={14} color="#dc2626" />
            <Text style={[styles.actionText, styles.actionDanger]}>Discard</Text>
          </Pressable>
        ) : null}
      </View>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  screen: { flex: 1, backgroundColor: c.bg },
  content: { padding: spacing.md, paddingBottom: spacing.xxl },
  card: {
    backgroundColor: c.surface, borderRadius: radius.md, borderWidth: 1,
    borderColor: c.border, padding: spacing.md, marginBottom: spacing.md,
  },
  cardTitle: { ...type.label, color: c.textMuted, marginBottom: spacing.xs },
  connRow: { flexDirection: "row", alignItems: "center", gap: spacing.xs },
  connText: { ...type.title, color: c.text },
  connWhen: { ...type.caption, color: c.textMuted, marginLeft: "auto" },
  dot: { width: 10, height: 10, borderRadius: 5 },
  counters: { flexDirection: "row", marginTop: spacing.md, marginBottom: spacing.md },
  counter: { flex: 1, alignItems: "center" },
  counterValue: { ...type.h1, color: c.textMuted },
  counterLabel: { ...type.caption, color: c.textMuted },
  progress: { ...type.caption, color: c.textMuted, marginBottom: spacing.sm, textAlign: "center" },
  syncBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: spacing.xs, backgroundColor: c.tint,
    paddingVertical: spacing.sm, borderRadius: radius.md,
  },
  syncBtnOff: { opacity: 0.45 },
  syncText: { ...type.body, color: "#fff", fontWeight: "700" },
  typeRow: {
    flexDirection: "row", justifyContent: "space-between",
    paddingVertical: spacing.xs,
  },
  typeName: { ...type.body, color: c.text },
  typeCount: { ...type.body, color: c.text, fontWeight: "700" },
  retryAll: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: spacing.xs, paddingVertical: spacing.sm, marginBottom: spacing.sm,
  },
  retryAllText: { ...type.caption, color: "#2563eb", fontWeight: "700" },
  section: { ...type.label, color: c.textMuted, marginTop: spacing.sm, marginBottom: 2 },
  sectionNote: { ...type.caption, color: c.textMuted, marginBottom: spacing.sm },
  entry: {
    backgroundColor: c.surface, borderRadius: radius.md, borderWidth: 1,
    borderColor: c.border, padding: spacing.md, marginBottom: spacing.sm,
  },
  entryHead: { flexDirection: "row", alignItems: "center", gap: spacing.xs },
  entryTitle: { ...type.body, color: c.text, fontWeight: "700", flex: 1 },
  entryStatus: { ...type.caption, color: c.textMuted, fontWeight: "700" },
  entryNo: { ...type.caption, color: c.text, marginTop: 2, fontWeight: "600" },
  entryMeta: { ...type.caption, color: c.textMuted, marginTop: 2 },
  entryError: { ...type.caption, color: c.danger, marginTop: spacing.xs },
  conflict: {
    marginTop: spacing.sm, padding: spacing.sm,
    backgroundColor: c.bg, borderRadius: radius.sm,
  },
  conflictRow: { flexDirection: "row", justifyContent: "space-between", gap: spacing.xs },
  conflictLabel: { ...type.caption, color: c.text, fontWeight: "700", flex: 1 },
  conflictValue: { ...type.caption, color: c.textMuted },
  actions: { flexDirection: "row", gap: spacing.md, marginTop: spacing.sm, flexWrap: "wrap" },
  action: { flexDirection: "row", alignItems: "center", gap: 4 },
  actionText: { ...type.caption, color: "#2563eb", fontWeight: "700" },
  actionDanger: { color: "#dc2626" },
  empty: { alignItems: "center", paddingVertical: spacing.xxl, gap: spacing.xs },
  emptyTitle: { ...type.title, color: c.text },
  emptyText: { ...type.caption, color: c.textMuted, textAlign: "center", paddingHorizontal: spacing.lg },
}));
