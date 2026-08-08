import { onlineManager } from "@tanstack/react-query";
import React, { useCallback, useEffect, useState } from "react";
import { Pressable, RefreshControl, ScrollView, Text, View } from "react-native";

import { AppIcon } from "@/components/AppIcon";
import { Loading } from "@/components/ui";
import {
  discardWrite, flushOutbox, outboxState, pendingWrites, retryWrite,
  subscribeToOutbox,
} from "@/net/outbox";
import { OutboxEntry } from "@/net/outboxTypes";
import { makeStyles, radius, spacing, type } from "@/theme";
import { confirm, notify } from "@/ui/confirm";

/**
 * What this phone has saved that the ERP has not seen yet.
 *
 * The bar at the top of every screen says a count; this is where that count
 * becomes a list. A supervisor who filled six farms out of range needs to know
 * which six, that nothing was lost, and — before handing the phone in or
 * signing off — that the queue is empty.
 *
 * The manual sync is not a shortcut for the automatic one. The app already
 * sends by itself when the connection returns, but "the connection returned"
 * is a claim the phone makes about its radio, and a rural link can be up by
 * that measure and useless in practice. A button the user can press is what
 * turns "it should have gone" into something they can check.
 */
export function OfflineEntriesScreen() {
  const styles = useStyles();
  const [entries, setEntries] = useState<OutboxEntry[] | null>(null);
  const [syncing, setSyncing] = useState(false);

  const reload = useCallback(async () => setEntries(await pendingWrites()), []);

  useEffect(() => {
    void reload();
    // The queue changes under this screen while a flush runs, and a list that
    // does not follow it would show rows that have already gone.
    return subscribeToOutbox(() => { void reload(); });
  }, [reload]);

  const sync = async () => {
    if (!onlineManager.isOnline()) {
      await notify("No connection",
        "Nothing can be sent right now. These are safe on the phone and will " +
        "go by themselves once you are back in range.");
      return;
    }
    setSyncing(true);
    try {
      const { sent, failed } = await flushOutbox();
      const left = outboxState().pending;
      if (!sent && !failed) {
        await notify("Nothing to send", left
          ? "Could not reach the ERP. Try again when the signal is steadier."
          : "Everything on this phone is already on the ERP.");
      } else {
        await notify(
          failed ? "Sent, with some refused" : "Sent",
          [sent ? `${sent} ${sent === 1 ? "entry" : "entries"} sent to the ERP.` : "",
           failed ? `${failed} ${failed === 1 ? "was" : "were"} refused — see below.` : "",
           left ? `${left} still waiting.` : ""].filter(Boolean).join("\n"));
      }
    } finally {
      setSyncing(false);
    }
  };

  const remove = async (entry: OutboxEntry) => {
    if (!(await confirm({
      title: "Discard this entry?",
      message: `${entry.label} has not reached the ERP. Discarding it means ` +
        "this record is gone for good — it exists nowhere else.",
      confirmLabel: "Discard",
      destructive: true,
    }))) return;
    await discardWrite(entry.id);
  };

  if (entries === null) return <Loading label="Reading the queue…" />;

  const waiting = entries.filter((e) => !e.rejected);
  const refused = entries.filter((e) => e.rejected);

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={false} onRefresh={reload} />}
    >
      <View style={styles.summary}>
        <View style={{ flex: 1 }}>
          <Text style={styles.summaryCount}>{waiting.length}</Text>
          <Text style={styles.summaryLabel}>
            {waiting.length === 1 ? "entry waiting to sync" : "entries waiting to sync"}
          </Text>
        </View>
        <Pressable
          onPress={sync}
          disabled={syncing || !waiting.length}
          style={[styles.syncBtn, (syncing || !waiting.length) && styles.syncBtnOff]}
          accessibilityRole="button"
        >
          <AppIcon name="sync" size={16} color="#fff" />
          <Text style={styles.syncText}>{syncing ? "Syncing…" : "Sync now"}</Text>
        </Pressable>
      </View>

      {!entries.length ? (
        <View style={styles.empty}>
          <AppIcon name="cloud-check-outline" size={40} color="#94a3b8" />
          <Text style={styles.emptyTitle}>Everything is on the ERP</Text>
          <Text style={styles.emptyText}>
            Anything you save without a signal waits here until there is one.
          </Text>
        </View>
      ) : null}

      {waiting.length ? (
        <>
          <Text style={styles.section}>Waiting to sync</Text>
          {waiting.map((e) => (
            <EntryCard key={e.id} entry={e} onDiscard={() => remove(e)} />
          ))}
        </>
      ) : null}

      {refused.length ? (
        <>
          <Text style={styles.section}>The ERP would not accept</Text>
          <Text style={styles.sectionNote}>
            These are still on the phone. Fix the cause on the ERP, then try
            again — or discard them if they are no longer wanted.
          </Text>
          {refused.map((e) => (
            <EntryCard
              key={e.id}
              entry={e}
              onDiscard={() => remove(e)}
              onRetry={() => retryWrite(e.id)}
            />
          ))}
        </>
      ) : null}
    </ScrollView>
  );
}

/** "2 minutes ago" / "at 14:05" / "8 Aug 14:05" — recent times read better. */
function savedAt(ts: number): string {
  const mins = Math.floor((Date.now() - ts) / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const at = new Date(ts);
  const time = at.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  if (mins < 60 * 24) return `at ${time}`;
  return `${at.toLocaleDateString(undefined, { day: "numeric", month: "short" })} ${time}`;
}

/** The plain-English shape of what is queued, from the record itself. */
function describe(entry: OutboxEntry): string {
  const files = entry.files?.length ?? 0;
  const parts = [
    { POST: "New", PUT: "Change", PATCH: "Change", DELETE: "Deletion" }[entry.method],
    files ? `· ${files} photo${files === 1 ? "" : "s"}` : "",
  ];
  return parts.filter(Boolean).join(" ");
}

function EntryCard({
  entry, onDiscard, onRetry,
}: {
  entry: OutboxEntry;
  onDiscard: () => void;
  onRetry?: () => void;
}) {
  const styles = useStyles();
  return (
    <View style={[styles.card, entry.rejected && styles.cardBad]}>
      <View style={styles.cardHead}>
        <Text style={styles.cardTitle} numberOfLines={1}>{entry.label}</Text>
        <Text style={styles.cardWhen}>{savedAt(entry.createdAt)}</Text>
      </View>
      <Text style={styles.cardMeta}>{describe(entry)}</Text>
      {entry.lastError ? (
        <Text style={styles.cardError} numberOfLines={3}>{entry.lastError}</Text>
      ) : null}
      {entry.attempts > 0 && !entry.rejected ? (
        <Text style={styles.cardMeta}>
          Tried {entry.attempts} {entry.attempts === 1 ? "time" : "times"}
        </Text>
      ) : null}
      <View style={styles.cardActions}>
        {onRetry ? (
          <Pressable onPress={onRetry} style={styles.action} accessibilityRole="button">
            <AppIcon name="refresh" size={14} color="#2563eb" />
            <Text style={styles.actionText}>Try again</Text>
          </Pressable>
        ) : null}
        <Pressable onPress={onDiscard} style={styles.action} accessibilityRole="button">
          <AppIcon name="trash-can-outline" size={14} color="#dc2626" />
          <Text style={[styles.actionText, styles.actionDanger]}>Discard</Text>
        </Pressable>
      </View>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  screen: { flex: 1, backgroundColor: c.bg },
  content: { padding: spacing.md, paddingBottom: spacing.xxl },
  summary: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: c.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: c.border,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  summaryCount: { ...type.h1, color: c.text },
  summaryLabel: { ...type.caption, color: c.textMuted },
  syncBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.xs,
    backgroundColor: c.tint,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    borderRadius: radius.md,
  },
  syncBtnOff: { opacity: 0.45 },
  syncText: { ...type.body, color: "#fff", fontWeight: "700" },
  section: { ...type.label, color: c.textMuted, marginTop: spacing.sm, marginBottom: spacing.xs },
  sectionNote: { ...type.caption, color: c.textMuted, marginBottom: spacing.sm },
  card: {
    backgroundColor: c.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: c.border,
    padding: spacing.md,
    marginBottom: spacing.sm,
  },
  cardBad: { borderColor: c.danger },
  cardHead: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  cardTitle: { ...type.body, color: c.text, fontWeight: "700", flex: 1 },
  cardWhen: { ...type.caption, color: c.textMuted },
  cardMeta: { ...type.caption, color: c.textMuted, marginTop: 2 },
  cardError: { ...type.caption, color: c.danger, marginTop: spacing.xs },
  cardActions: { flexDirection: "row", gap: spacing.md, marginTop: spacing.sm },
  action: { flexDirection: "row", alignItems: "center", gap: 4 },
  actionText: { ...type.caption, color: "#2563eb", fontWeight: "700" },
  actionDanger: { color: "#dc2626" },
  empty: { alignItems: "center", paddingVertical: spacing.xxl, gap: spacing.xs },
  emptyTitle: { ...type.title, color: c.text },
  emptyText: { ...type.caption, color: c.textMuted, textAlign: "center", paddingHorizontal: spacing.lg },
}));
