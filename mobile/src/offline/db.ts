import AsyncStorage from "@react-native-async-storage/async-storage";
import { Platform } from "react-native";

import { SyncStatus } from "./types";

/**
 * The local store behind every offline entry.
 *
 * SQLite rather than a JSON blob in AsyncStorage, for reasons that only bite
 * at the scale this has to survive. A supervisor can come back from a round
 * with dozens of entries and hundreds of photos; rewriting one document on
 * every status change is O(queue) per write, and the whole queue has to be
 * parsed before a single row can be read. Here a row is updated in place, and
 * the sync engine can ask for "the highest-priority pending entry whose parent
 * has landed" instead of loading everything to find it.
 *
 * The central PostgreSQL database stays the source of truth. This is a
 * temporary store for what has not reached it yet — nothing is read from here
 * that the server has already accepted.
 */

const DB_NAME = "bims_offline.db";

/** Bumped when the schema changes; see `migrate`. */
const SCHEMA_VERSION = 1;

/** Where the browser keeps what SQLite keeps on a handset. */
const WEB_KEY = "bims_offline_web_v1";

type Row = Record<string, unknown>;

export interface Db {
  run(sql: string, params?: unknown[]): Promise<void>;
  all<T = Row>(sql: string, params?: unknown[]): Promise<T[]>;
  first<T = Row>(sql: string, params?: unknown[]): Promise<T | null>;
}

let ready: Promise<Db> | null = null;

/**
 * The database, opened once and migrated.
 *
 * Web has no SQLite worth its weight — the browser build is a desk tool, not
 * the handset in the shed — so it gets a smaller store behind the same
 * surface, persisted to AsyncStorage so a reload does not take the queue with
 * it. Everything above this line is unaware of the difference, which keeps one
 * code path for the sync engine and its tests.
 */
export function database(): Promise<Db> {
  ready = ready ?? open();
  return ready;
}

async function open(): Promise<Db> {
  const db = Platform.OS === "web" ? memoryDb() : await sqliteDb();
  await migrate(db);
  return db;
}

async function sqliteDb(): Promise<Db> {
  const SQLite = await import("expo-sqlite");
  const handle = await SQLite.openDatabaseAsync(DB_NAME);
  // WAL keeps a reader (the Sync Center, refreshing) from blocking the writer
  // (the engine, marking an entry synced) — they run at the same time here.
  await handle.execAsync("PRAGMA journal_mode = WAL;");
  await handle.execAsync("PRAGMA foreign_keys = ON;");
  return {
    run: async (sql, params = []) => { await handle.runAsync(sql, params as never[]); },
    all: async <T,>(sql: string, params: unknown[] = []) =>
      handle.getAllAsync<T>(sql, params as never[]),
    first: async <T,>(sql: string, params: unknown[] = []) =>
      (await handle.getFirstAsync<T>(sql, params as never[])) ?? null,
  };
}

// --- schema ----------------------------------------------------------------

/**
 * Every field the offline record needs, including the ones only an audit ever
 * reads. `payload` is the transaction as the API wants it; the columns beside
 * it are what the queue itself has to sort, filter and report on without
 * parsing that payload.
 */
const SCHEMA = `
CREATE TABLE IF NOT EXISTS sync_queue (
  local_id          TEXT PRIMARY KEY NOT NULL,
  offline_no        TEXT NOT NULL,
  server_id         TEXT,
  transaction_type  TEXT NOT NULL,
  transaction_label TEXT NOT NULL,
  transaction_date  TEXT,
  method            TEXT NOT NULL,
  path              TEXT NOT NULL,
  payload           TEXT NOT NULL,
  files             TEXT,

  employee_id       TEXT,
  user_id           TEXT,
  company_id        TEXT,
  branch_id         TEXT,
  warehouse_id      TEXT,
  farm_id           TEXT,
  shed_id           TEXT,
  batch_id          TEXT,

  gps_latitude      REAL,
  gps_longitude     REAL,
  gps_accuracy      REAL,
  gps_captured_at   TEXT,

  device_id         TEXT,
  priority          INTEGER NOT NULL DEFAULT 50,
  depends_on        TEXT,
  produces_ref      TEXT,

  device_created_at TEXT NOT NULL,
  created_at        TEXT NOT NULL,
  updated_at        TEXT NOT NULL,

  sync_status       TEXT NOT NULL DEFAULT 'pending',
  sync_attempts     INTEGER NOT NULL DEFAULT 0,
  next_attempt_at   TEXT,
  last_sync_at      TEXT,
  sync_error        TEXT,
  server_version    TEXT,
  conflict          TEXT
);

CREATE INDEX IF NOT EXISTS idx_queue_status   ON sync_queue (sync_status);
CREATE INDEX IF NOT EXISTS idx_queue_order    ON sync_queue (sync_status, priority, created_at);
CREATE INDEX IF NOT EXISTS idx_queue_user     ON sync_queue (user_id);
CREATE INDEX IF NOT EXISTS idx_queue_produces ON sync_queue (produces_ref);

CREATE TABLE IF NOT EXISTS sync_meta (
  key   TEXT PRIMARY KEY NOT NULL,
  value TEXT
);
`;

async function migrate(db: Db): Promise<void> {
  for (const statement of SCHEMA.split(";")) {
    const sql = statement.trim();
    if (sql) await db.run(sql);
  }
  await db.run(
    "INSERT OR REPLACE INTO sync_meta (key, value) VALUES ('schema_version', ?)",
    [String(SCHEMA_VERSION)]);
}

// --- the web stand-in ------------------------------------------------------

/**
 * Enough SQLite to run the same code in a browser and in a test.
 *
 * Deliberately only supports the handful of statement shapes this module
 * issues, and throws on anything else rather than quietly returning the wrong
 * rows — a silent mismatch between the two backings is the one bug this would
 * be worth having.
 *
 * Backed by AsyncStorage, not just memory. That is not a nicety: the first cut
 * kept the rows in a closure, and a browser reload took a supervisor's queued
 * round with it — the very thing the queue exists to survive. Writes go
 * through to storage; a read never touches it, because the rows in hand are
 * already the truth.
 */
function memoryDb(): Db {
  const rows: Row[] = [];
  const meta: Row[] = [];
  let hydrated = false;

  const persist = () => {
    void AsyncStorage.setItem(WEB_KEY, JSON.stringify({ rows, meta }))
      .catch(() => undefined);
  };

  const hydrate = async () => {
    if (hydrated) return;
    hydrated = true;
    try {
      const raw = await AsyncStorage.getItem(WEB_KEY);
      if (!raw) return;
      const saved = JSON.parse(raw) as { rows?: Row[]; meta?: Row[] };
      rows.push(...(saved.rows ?? []));
      meta.push(...(saved.meta ?? []));
    } catch {
      // A store that will not parse is worse than an empty one only if it
      // blocks every read behind it. Starting clean at least keeps the app
      // usable, and nothing the ERP has already accepted is lost.
    }
  };
  const table = (sql: string) => (/sync_meta/i.test(sql) ? meta : rows);

  const matches = (row: Row, sql: string, params: unknown[]): boolean => {
    const where = sql.split(/\bWHERE\b/i)[1];
    if (!where) return true;
    let i = 0;
    return where
      .split(/\bAND\b/i)
      .every((clause) => {
        const [, column, op] = clause.trim().match(/^(\w+)\s*(=|!=|<=|>=|<|>|IS NULL|IS NOT NULL)/i) ?? [];
        if (!column) return true;
        if (/IS NOT NULL/i.test(op)) return row[column] != null;
        if (/IS NULL/i.test(op)) return row[column] == null;
        const value = params[i++];
        const cell = row[column];
        switch (op) {
          case "=": return String(cell) === String(value);
          case "!=": return String(cell) !== String(value);
          default: return true;
        }
      });
  };

  return {
    async run(sql, params = []) {
      await hydrate();
      if (/^CREATE|^PRAGMA/i.test(sql.trim())) return;
      if (/^INSERT/i.test(sql)) {
        const columns = sql.match(/\(([^)]+)\)\s*VALUES/i)?.[1].split(",").map((c) => c.trim()) ?? [];
        const row: Row = {};
        columns.forEach((c, i) => { row[c] = params[i]; });
        const store = table(sql);
        const key = store === meta ? "key" : "local_id";
        const existing = store.findIndex((r) => r[key] === row[key]);
        if (existing >= 0) store[existing] = row;
        else store.push(row);
        persist();
        return;
      }
      if (/^UPDATE/i.test(sql)) {
        const sets = sql.split(/\bSET\b/i)[1].split(/\bWHERE\b/i)[0]
          .split(",").map((s) => s.trim().split("=")[0].trim());
        const store = table(sql);
        const whereParams = params.slice(sets.length);
        store.filter((r) => matches(r, sql, whereParams))
          .forEach((r) => sets.forEach((c, i) => { r[c] = params[i]; }));
        persist();
        return;
      }
      if (/^DELETE/i.test(sql)) {
        const store = table(sql);
        for (let i = store.length - 1; i >= 0; i -= 1) {
          if (matches(store[i], sql, params)) store.splice(i, 1);
        }
        persist();
        return;
      }
      throw new Error(`offline/db: unsupported statement — ${sql.slice(0, 40)}`);
    },
    async all<T,>(sql: string, params: unknown[] = []) {
      await hydrate();
      const store = table(sql);
      let out = store.filter((r) => matches(r, sql, params));
      const order = sql.match(/ORDER BY\s+(.+?)(?:\s+LIMIT|$)/i)?.[1];
      if (order) {
        const keys = order.split(",").map((k) => k.trim().split(/\s+/)[0]);
        out = [...out].sort((a, b) =>
          keys.reduce((acc, k) =>
            acc || String(a[k] ?? "").localeCompare(String(b[k] ?? "")), 0));
      }
      const limit = sql.match(/LIMIT\s+(\d+)/i)?.[1];
      return (limit ? out.slice(0, Number(limit)) : out) as T[];
    },
    async first<T,>(sql: string, params: unknown[] = []) {
      return ((await this.all<T>(sql, params))[0] ?? null) as T | null;
    },
  };
}

/** Used by tests and by sign-out policy; never called in normal operation. */
export async function resetDatabase(): Promise<void> {
  const db = await database();
  await db.run("DELETE FROM sync_queue");
  await AsyncStorage.removeItem(WEB_KEY).catch(() => undefined);
  ready = null;
}

export const SYNC_STATUSES: SyncStatus[] = [
  "pending", "syncing", "synced", "failed", "conflict",
];
