/**
 * The shape of an offline entry, and the vocabulary the whole system uses.
 *
 * Kept free of SQLite, the http client and the file system so a screen or a
 * test can talk about a queued entry without pulling any of that in.
 */

export type SyncStatus = "pending" | "syncing" | "synced" | "failed" | "conflict";

export type SyncMethod = "POST" | "PUT" | "PATCH" | "DELETE";

/**
 * Which entries go first.
 *
 * Ordering is a business decision, not a technical one. A placement that other
 * entries hang off, and anything that moves stock or has a veterinary record
 * behind it, reaches the ERP before a note does — so that a partial sync on a
 * dying link leaves the *important* half filed rather than an arbitrary half.
 *
 * Lower sorts first. Dependencies still override this: a child never goes
 * before its parent however urgent it looks (see the sync engine).
 */
export const PRIORITY = {
  high: 10,
  medium: 50,
  low: 90,
} as const;

/** A file part, already copied somewhere that outlives the camera's cache. */
export interface OfflineFile {
  field: string;
  uri: string;
  name: string;
  type: string;
}

/** What the queue knows about one transaction waiting to reach the ERP. */
export interface OfflineEntry {
  /** UUID. Also the idempotency key the server dedupes on. */
  local_id: string;
  /** OFF-YYYYMMDD-NNNNNN — what a person quotes when asking about an entry. */
  offline_no: string;
  /** The id the ERP issued, once it has. Both are kept, for audit. */
  server_id: string | null;

  /** A stable machine name, e.g. "mortality" — used for grouping and priority. */
  transaction_type: string;
  /** What to call it on screen, e.g. "Mortality". */
  transaction_label: string;
  /** The business date of the entry, not when it was typed. */
  transaction_date: string | null;

  method: SyncMethod;
  path: string;
  payload: Record<string, unknown>;
  files: OfflineFile[];

  employee_id: string | null;
  user_id: string | null;
  company_id: string | null;
  branch_id: string | null;
  warehouse_id: string | null;
  farm_id: string | null;
  shed_id: string | null;
  batch_id: string | null;

  gps_latitude: number | null;
  gps_longitude: number | null;
  gps_accuracy: number | null;
  gps_captured_at: string | null;

  device_id: string | null;
  priority: number;
  /** local_id of an entry that must land first. */
  depends_on: string | null;
  /** The placeholder later entries use for this one's server id. */
  produces_ref: string | null;

  /** When the user actually filed it — never overwritten by the sync time. */
  device_created_at: string;
  created_at: string;
  updated_at: string;

  sync_status: SyncStatus;
  sync_attempts: number;
  /** Backoff: nothing is sent before this. */
  next_attempt_at: string | null;
  last_sync_at: string | null;
  sync_error: string | null;
  server_version: string | null;
  conflict: SyncConflict | null;
}

/** What the server said when it refused to overwrite what it already had. */
export interface SyncConflict {
  message: string;
  /** Field-by-field, what is on the server against what this phone holds. */
  fields: { field: string; label: string; server: string; local: string }[];
  /** The ERP row the conflict is with, when it names one. */
  server_id?: string | number;
}

/** The counters the header chip and the Sync Center both read. */
export interface SyncSummary {
  online: boolean;
  syncing: boolean;
  pending: number;
  failed: number;
  conflicts: number;
  synced: number;
  /** Pending broken down by transaction type, most numerous first. */
  byType: { type: string; label: string; count: number }[];
  lastSyncAt: string | null;
}
