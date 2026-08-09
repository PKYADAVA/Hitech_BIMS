import { Db } from "./dbTypes";

const DB_NAME = "bims_offline.db";

/**
 * The handset's real database.
 *
 * Kept in its own module so the web build never reaches it. Metro resolves
 * `./sqlite` to sqlite.web.ts when bundling for the browser, which is the only
 * reliable way to keep expo-sqlite out of that bundle — a dynamic import is
 * not enough, because Metro still follows it statically, and the package's web
 * worker then asks for a wasm binary that fails to resolve and takes the whole
 * bundle with it.
 */
export async function openSqlite(): Promise<Db> {
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
