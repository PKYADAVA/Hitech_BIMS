import { onlineManager } from "@tanstack/react-query";
import { Platform } from "react-native";

import { http } from "@/api/client";
import { discardOfflineFile } from "./files";
import {
  currentQueueUser, deleteEntry, entryProducing, getEntry, listEntries,
  pruneSynced, sendableEntries, updateEntry,
} from "./queue";
import { OfflineEntry, SyncConflict } from "./types";

/**
 * Sending what the phone holds, in the order the ERP needs it.
 *
 * The engine is deliberately dull: it asks the queue what may go, sends one
 * entry at a time, and records what happened. Everything interesting — which
 * entry is next, whether a parent has landed, whether a retry is due — is a
 * question the queue answers, so the ordering rules live with the data they
 * order rather than in a loop that is hard to reason about.
 */

/** Given up on for now after this many tries; kept, shown, retryable by hand. */
const MAX_ATTEMPTS = 6;

/**
 * How long to wait before trying again, per attempt.
 *
 * Doubling, and capped. A rural link comes back in minutes, not milliseconds,
 * and a handset retrying every second on a dead connection flattens its own
 * battery and — with a hundred handsets doing it — the server as well.
 */
const BACKOFF_MS = [30_000, 60_000, 300_000, 900_000, 1_800_000, 3_600_000];

/**
 * How many times a run will re-ask what may go.
 *
 * A pass can unlock the entries that were waiting on it, so the run keeps
 * going while it is making progress. The cap is a guard against a cycle in the
 * dependencies — which should be impossible, and would otherwise spin here.
 */
const MAX_PASSES = 10;

export interface SyncProgress {
  total: number;
  done: number;
  current: OfflineEntry | null;
}

export interface SyncOutcome {
  sent: number;
  failed: number;
  conflicts: number;
  /** True when it stopped early because nothing more could be sent. */
  stopped: boolean;
}

let running = false;
const watchers = new Set<(p: SyncProgress | null) => void>();

export function isSyncing(): boolean {
  return running;
}

export function watchSync(fn: (p: SyncProgress | null) => void): () => void {
  watchers.add(fn);
  return () => watchers.delete(fn);
}

function report(progress: SyncProgress | null): void {
  watchers.forEach((fn) => fn(progress));
}

// --- one entry -------------------------------------------------------------

/** Placeholders resolved to the ids the ERP issued during this run. */
type Resolved = Map<string, string>;

/** Replace every "tmp:…" reference with the id its parent came back with. */
export function substitute<T>(value: T, ids: Resolved): T {
  if (typeof value === "string") return (ids.get(value) ?? value) as unknown as T;
  if (Array.isArray(value)) return value.map((v) => substitute(v, ids)) as unknown as T;
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      out[k] = substitute(v, ids);
    }
    return out as unknown as T;
  }
  return value;
}

async function buildBody(entry: OfflineEntry, ids: Resolved): Promise<{
  body: unknown;
  headers: Record<string, string | undefined>;
}> {
  const headers: Record<string, string | undefined> = {
    // The idempotency key. The same value on every attempt is what stops a
    // request that landed but lost its answer being performed twice.
    "Idempotency-Key": entry.local_id,
    // Carried so the ERP can record when the entry was actually filed, rather
    // than stamping it with the moment it happened to reach the server.
    "X-Offline-Created-At": entry.device_created_at,
    "X-Offline-No": entry.offline_no,
    "X-Device-Id": entry.device_id ?? undefined,
  };
  const payload = substitute(entry.payload, ids);
  if (!entry.files.length) return { body: payload, headers };

  const form = new FormData();
  for (const [field, value] of Object.entries(payload)) {
    if (value === undefined || value === null) continue;
    form.append(field, String(value));
  }
  for (const file of entry.files) {
    if (Platform.OS === "web") {
      form.append(file.field, await (await fetch(file.uri)).blob(), file.name);
    } else {
      form.append(file.field,
        { uri: file.uri, name: file.name, type: file.type } as unknown as Blob);
    }
  }
  // The boundary comes from the runtime on native and the browser on web; a
  // hand-set multipart header without one is rejected.
  headers["Content-Type"] = Platform.OS === "web" ? undefined : "multipart/form-data";
  return { body: form, headers };
}

async function send(entry: OfflineEntry, ids: Resolved): Promise<unknown> {
  const path = substitute(entry.path, ids);
  const { body, headers } = await buildBody(entry, ids);
  if (entry.method === "DELETE") {
    return (await http.delete(path, { headers })).data?.data;
  }
  const method = entry.method.toLowerCase() as "post" | "put" | "patch";
  return (await http[method](path, body, { headers })).data?.data;
}

// --- reading a failure -----------------------------------------------------

interface Failure {
  status?: number;
  code?: string;
  message?: string;
  conflict?: SyncConflict;
}

/** Nothing came back, or the server may yet recover: worth another attempt. */
function isTransient(e: Failure): boolean {
  if (e.status == null) return true;                       // no response at all
  if (e.status === 409 && e.code === "idempotency_in_progress") return true;
  if (e.status === 401) return true;                       // token refresh in flight
  if (e.status === 408 || e.status === 429) return true;
  return e.status >= 500;
}

/** The server refusing to overwrite what it already holds. */
function asConflict(e: Failure): SyncConflict | null {
  if (e.status !== 409 || e.code !== "sync_conflict") return null;
  return e.conflict ?? { message: e.message ?? "This entry conflicts with the ERP.", fields: [] };
}

/**
 * What to tell the person holding the phone.
 *
 * Never the transport's own words. "Socket exception" and "HTTP 503" describe
 * the plumbing to someone who only wants to know whether their round is safe.
 */
export function humanError(e: Failure): string {
  if (e.status == null) return "No connection to the ERP. It will retry by itself.";
  if (e.status === 401) return "Signed out. Sign in again and it will send.";
  if (e.status >= 500) return "The ERP is not answering. It will retry by itself.";
  if (e.status === 403) return "You do not have access to save this.";
  if (e.status === 400 || e.status === 422) {
    return e.message || "The ERP would not accept this entry. Check the details.";
  }
  return e.message || "Could not send this entry.";
}

// --- the run ---------------------------------------------------------------

/**
 * Send everything that may go, in order, stopping when nothing more can.
 *
 * A transient failure ends the run rather than skipping ahead: the entries
 * behind it may depend on it, and in any case if the link is down for one it
 * is down for all. A refusal is recorded against that entry alone and the run
 * continues, because one bad payload must not hold up a whole round.
 */
export async function runSync(): Promise<SyncOutcome> {
  if (running || !onlineManager.isOnline()) {
    return { sent: 0, failed: 0, conflicts: 0, stopped: true };
  }
  running = true;
  const outcome: SyncOutcome = { sent: 0, failed: 0, conflicts: 0, stopped: false };
  const ids: Resolved = new Map();

  try {
    // Asked again after each pass, not snapshotted once. An entry held back
    // because its parent had not landed becomes sendable the moment it does,
    // and a run that took the list up front would leave the child sitting
    // there until the next reconnect — for a chain of three, three reconnects.
    let sent = 0;
    for (let pass = 0; pass < MAX_PASSES; pass += 1) {
      const queue = await sendableEntries();
      if (!queue.length) break;
      const before = outcome.sent;
      await sendBatch(queue, ids, outcome, sent);
      sent = outcome.sent;
      if (outcome.stopped || outcome.sent === before) break;
    }
    await pruneSynced();
    return outcome;
  } finally {
    running = false;
    report(null);
  }
}

/** One pass over the entries that may go right now. */
async function sendBatch(
  queue: OfflineEntry[], ids: Resolved, outcome: SyncOutcome, alreadySent: number
): Promise<void> {
  {
    const total = queue.length + alreadySent;
    report({ total, done: alreadySent, current: null });

    for (const [index, entry] of queue.entries()) {
      // Re-read: a run is not instant, and the user may have discarded this
      // one from the Sync Center while an earlier entry was in flight.
      const live = await getEntry(entry.local_id);
      if (!live || live.sync_status === "synced") continue;

      report({ total, done: alreadySent + index, current: live });
      await updateEntry(live.local_id, { sync_status: "syncing" });

      try {
        const result = await send(live, ids);
        const serverId = (result as { id?: number | string } | undefined)?.id;
        if (live.produces_ref && serverId != null) {
          ids.set(live.produces_ref, String(serverId));
        }
        await Promise.all(live.files.map(discardOfflineFile));
        await updateEntry(live.local_id, {
          sync_status: "synced",
          server_id: serverId != null ? String(serverId) : null,
          last_sync_at: new Date().toISOString(),
          sync_error: null,
          files: [],
        });
        outcome.sent += 1;
      } catch (error) {
        const failure = error as Failure;
        const stop = await recordFailure(live, failure);
        if (asConflict(failure)) outcome.conflicts += 1;
        else outcome.failed += 1;
        if (stop) {
          outcome.stopped = true;
          break;
        }
      }
    }
  }
}

/** Write down what went wrong. Returns true when the run should stop. */
async function recordFailure(entry: OfflineEntry, failure: Failure): Promise<boolean> {
  const attempts = entry.sync_attempts + 1;
  const conflict = asConflict(failure);
  const now = new Date();

  if (conflict) {
    // Never resolved silently. A supervisor's ten birds and the office's seven
    // are both somebody's count of the same shed, and picking one without
    // asking loses a real number.
    await updateEntry(entry.local_id, {
      sync_status: "conflict", conflict, sync_attempts: attempts,
      last_sync_at: now.toISOString(),
      sync_error: conflict.message,
    });
    return false;
  }

  if (isTransient(failure) && attempts < MAX_ATTEMPTS) {
    const wait = BACKOFF_MS[Math.min(attempts - 1, BACKOFF_MS.length - 1)];
    await updateEntry(entry.local_id, {
      sync_status: "pending",
      sync_attempts: attempts,
      next_attempt_at: new Date(now.getTime() + wait).toISOString(),
      last_sync_at: now.toISOString(),
      sync_error: humanError(failure),
    });
    return true;   // the link is the problem; the rest will fare no better
  }

  await updateEntry(entry.local_id, {
    sync_status: "failed",
    sync_attempts: attempts,
    last_sync_at: now.toISOString(),
    sync_error: humanError(failure),
  });
  return false;
}

// --- what the user can ask for --------------------------------------------

/** Put a given-up entry back in the queue — the cause was fixed elsewhere. */
export async function retryEntry(localId: string): Promise<void> {
  await updateEntry(localId, {
    sync_status: "pending", sync_attempts: 0,
    next_attempt_at: null, sync_error: null, conflict: null,
  });
}

/** Try everything that has been given up on. */
export async function retryAllFailed(): Promise<void> {
  for (const entry of await listEntries("failed")) {
    await retryEntry(entry.local_id);
  }
}

/**
 * Drop an entry for good, at the user's explicit say-so.
 *
 * The only route by which an unsynced entry is ever destroyed. Nothing in the
 * system deletes one on its own — not low storage, not age, not a failed run.
 */
export async function discardEntry(localId: string): Promise<void> {
  const entry = await getEntry(localId);
  await Promise.all((entry?.files ?? []).map(discardOfflineFile));
  await deleteEntry(localId);
}

/**
 * Resolve a conflict the way the user chose.
 *
 * "server" abandons this phone's version and records that it was seen —
 * keeping the row so the decision is auditable rather than vanishing.
 * "local" sends it again with a header telling the ERP the clash was reviewed
 * and this value is meant to stand.
 */
export async function resolveConflict(
  localId: string,
  choice: "server" | "local"
): Promise<void> {
  const entry = await getEntry(localId);
  if (!entry) return;
  if (choice === "server") {
    await updateEntry(localId, {
      sync_status: "synced",
      server_id: entry.conflict?.server_id != null ? String(entry.conflict.server_id) : null,
      last_sync_at: new Date().toISOString(),
      sync_error: "Kept the ERP's version.",
    });
    return;
  }
  await updateEntry(localId, {
    sync_status: "pending",
    sync_attempts: 0,
    next_attempt_at: null,
    conflict: null,
    sync_error: null,
    payload: { ...entry.payload, __resolve_conflict: "accept_offline" },
  });
}

/** The entry a placeholder names, for the Sync Center's dependency lines. */
export { entryProducing };
