import { database } from "./db";
import {
  OfflineEntry, OfflineFile, SyncConflict, SyncMethod, SyncStatus, SyncSummary,
} from "./types";

/**
 * Reading and writing the offline queue.
 *
 * Every statement lives here so the sync engine, the Sync Center and the
 * header chip all see the same rows through the same rules — in particular the
 * organisational one: an entry belongs to the user who filed it, and is never
 * shown to, counted for, or sent under anyone else.
 */

const COLUMNS = [
  "local_id", "offline_no", "server_id", "transaction_type", "transaction_label",
  "transaction_date", "method", "path", "payload", "files",
  "employee_id", "user_id", "company_id", "branch_id", "warehouse_id",
  "farm_id", "shed_id", "batch_id",
  "gps_latitude", "gps_longitude", "gps_accuracy", "gps_captured_at",
  "device_id", "priority", "depends_on", "produces_ref",
  "device_created_at", "created_at", "updated_at",
  "sync_status", "sync_attempts", "next_attempt_at", "last_sync_at",
  "sync_error", "server_version", "conflict",
] as const;

const listeners = new Set<() => void>();
let currentUserId: string | null = null;

/**
 * Whose queue is active.
 *
 * Signing out does not empty the queue — an entry filed with no signal exists
 * nowhere else, and ending a shift before reaching signal must not lose the
 * round. It changes whose entries are counted and sent, so one person's work
 * can never go up under another's token.
 */
export function setQueueUser(userId: string | null): void {
  currentUserId = userId;
  notify();
}

export function currentQueueUser(): string | null {
  return currentUserId;
}

export function subscribeToQueue(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function notify(): void {
  listeners.forEach((fn) => fn());
}

// --- mapping ---------------------------------------------------------------

function toEntry(row: Record<string, unknown>): OfflineEntry {
  const parse = <T,>(value: unknown, fallback: T): T => {
    if (value == null || value === "") return fallback;
    try {
      return JSON.parse(String(value)) as T;
    } catch {
      // A row whose JSON will not parse is still a record of something the
      // user filed. Returning the fallback keeps it visible and discardable
      // rather than throwing every read of the whole queue.
      return fallback;
    }
  };
  const num = (v: unknown) => (v == null || v === "" ? null : Number(v));
  const str = (v: unknown) => (v == null ? null : String(v));
  return {
    local_id: String(row.local_id),
    offline_no: String(row.offline_no),
    server_id: str(row.server_id),
    transaction_type: String(row.transaction_type),
    transaction_label: String(row.transaction_label),
    transaction_date: str(row.transaction_date),
    method: String(row.method) as SyncMethod,
    path: String(row.path),
    payload: parse<Record<string, unknown>>(row.payload, {}),
    files: parse<OfflineFile[]>(row.files, []),
    employee_id: str(row.employee_id),
    user_id: str(row.user_id),
    company_id: str(row.company_id),
    branch_id: str(row.branch_id),
    warehouse_id: str(row.warehouse_id),
    farm_id: str(row.farm_id),
    shed_id: str(row.shed_id),
    batch_id: str(row.batch_id),
    gps_latitude: num(row.gps_latitude),
    gps_longitude: num(row.gps_longitude),
    gps_accuracy: num(row.gps_accuracy),
    gps_captured_at: str(row.gps_captured_at),
    device_id: str(row.device_id),
    priority: Number(row.priority ?? 50),
    depends_on: str(row.depends_on),
    produces_ref: str(row.produces_ref),
    device_created_at: String(row.device_created_at),
    created_at: String(row.created_at),
    updated_at: String(row.updated_at),
    sync_status: String(row.sync_status) as SyncStatus,
    sync_attempts: Number(row.sync_attempts ?? 0),
    next_attempt_at: str(row.next_attempt_at),
    last_sync_at: str(row.last_sync_at),
    sync_error: str(row.sync_error),
    server_version: str(row.server_version),
    conflict: parse<SyncConflict | null>(row.conflict, null),
  };
}

// --- writing ---------------------------------------------------------------

export async function insertEntry(entry: OfflineEntry): Promise<void> {
  const db = await database();
  const values: unknown[] = COLUMNS.map((c) => {
    const v = entry[c as keyof OfflineEntry];
    if (c === "payload" || c === "files" || c === "conflict") return JSON.stringify(v ?? null);
    return v ?? null;
  });
  await db.run(
    `INSERT INTO sync_queue (${COLUMNS.join(", ")}) VALUES (${COLUMNS.map(() => "?").join(", ")})`,
    values);
  notify();
}

/** Patch a row. Only the columns given are touched. */
export async function updateEntry(
  localId: string,
  patch: Partial<Record<keyof OfflineEntry, unknown>>
): Promise<void> {
  const db = await database();
  const fields = { ...patch, updated_at: new Date().toISOString() };
  const keys = Object.keys(fields);
  const values = keys.map((k) => {
    const v = fields[k as keyof OfflineEntry];
    if (k === "payload" || k === "files" || k === "conflict") return JSON.stringify(v ?? null);
    return v ?? null;
  });
  await db.run(
    `UPDATE sync_queue SET ${keys.map((k) => `${k} = ?`).join(", ")} WHERE local_id = ?`,
    [...values, localId]);
  notify();
}

export async function deleteEntry(localId: string): Promise<void> {
  const db = await database();
  await db.run("DELETE FROM sync_queue WHERE local_id = ?", [localId]);
  notify();
}

/**
 * Forget entries the ERP has confirmed.
 *
 * Synced rows are kept for a while so the Sync Center can say "142 synced" and
 * a supervisor can point at what went up this morning. They are not kept for
 * ever: the ERP holds the record, and this is a queue, not an archive.
 */
export async function pruneSynced(olderThanHours = 48): Promise<number> {
  const db = await database();
  const cutoff = new Date(Date.now() - olderThanHours * 3_600_000).toISOString();
  const rows = await db.all("SELECT * FROM sync_queue");
  const doomed = rows
    .map(toEntry)
    .filter((e) => e.sync_status === "synced"
                && !!e.last_sync_at && e.last_sync_at < cutoff);
  for (const entry of doomed) {
    await db.run("DELETE FROM sync_queue WHERE local_id = ?", [entry.local_id]);
  }
  if (doomed.length) notify();
  return doomed.length;
}

// --- reading ---------------------------------------------------------------

/**
 * The signed-in user's entries, in send order.
 *
 * Ownership and status are filtered here rather than in the statement. The
 * queue holds a round, not a ledger — hundreds of rows at the very most — so
 * the saving from pushing it into SQL is nil, and keeping every WHERE clause
 * down to a single indexed equality is what lets the same repository run
 * against the browser's simpler backing without the two drifting apart.
 */
export async function listEntries(status?: SyncStatus): Promise<OfflineEntry[]> {
  const db = await database();
  const rows = await db.all("SELECT * FROM sync_queue ORDER BY priority, created_at");
  return rows
    .map(toEntry)
    .filter((e) => !e.user_id || e.user_id === currentUserId)
    .filter((e) => !status || e.sync_status === status);
}

export async function getEntry(localId: string): Promise<OfflineEntry | null> {
  const db = await database();
  const row = await db.first("SELECT * FROM sync_queue WHERE local_id = ?", [localId]);
  return row ? toEntry(row) : null;
}

/** The entry a placeholder refers to, so its server id can be substituted. */
export async function entryProducing(ref: string): Promise<OfflineEntry | null> {
  const db = await database();
  const row = await db.first("SELECT * FROM sync_queue WHERE produces_ref = ?", [ref]);
  return row ? toEntry(row) : null;
}

/**
 * What to send next, in the order it must go.
 *
 * Priority decides between unrelated entries; dependency overrides it. An
 * entry whose parent has not landed is skipped rather than sent, because the
 * server would reject a child pointing at an id that does not exist yet — and
 * that rejection would look like a bad payload rather than a sequencing
 * problem, and be given up on.
 */
export async function sendableEntries(now = new Date()): Promise<OfflineEntry[]> {
  const all = await listEntries();
  const landed = new Set(all.filter((e) => e.sync_status === "synced").map((e) => e.local_id));
  const iso = now.toISOString();
  return all
    // Only pending. A transient failure stays pending with a wait on it, so it
    // comes back by itself; "failed" means the ERP ruled against the entry, and
    // sending it again unasked would just fail again — or, worse, succeed on a
    // retry that a person never agreed to. Those wait for Try again.
    .filter((e) => e.sync_status === "pending")
    .filter((e) => !e.next_attempt_at || e.next_attempt_at <= iso)
    .filter((e) => !e.depends_on || landed.has(e.depends_on))
    .sort((a, b) => a.priority - b.priority
                 || a.created_at.localeCompare(b.created_at));
}

/** Everything the header chip and the Sync Center need, in one pass. */
export async function summarise(online: boolean, syncing: boolean): Promise<SyncSummary> {
  const all = await listEntries();
  const count = (s: SyncStatus) => all.filter((e) => e.sync_status === s).length;
  const byType = new Map<string, { type: string; label: string; count: number }>();
  for (const e of all) {
    if (e.sync_status === "synced") continue;
    const found = byType.get(e.transaction_type)
      ?? { type: e.transaction_type, label: e.transaction_label, count: 0 };
    found.count += 1;
    byType.set(e.transaction_type, found);
  }
  const lastSyncAt = all
    .map((e) => e.last_sync_at)
    .filter(Boolean)
    .sort()
    .pop() ?? null;
  return {
    online,
    syncing,
    pending: count("pending") + count("syncing"),
    failed: count("failed"),
    conflicts: count("conflict"),
    synced: count("synced"),
    byType: [...byType.values()].sort((a, b) => b.count - a.count),
    lastSyncAt,
  };
}
