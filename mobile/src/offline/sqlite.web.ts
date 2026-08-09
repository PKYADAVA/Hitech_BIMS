import { Db } from "./dbTypes";

/**
 * There is no SQLite in the browser build, by choice.
 *
 * The web build is a desk tool; the queue there is kept in AsyncStorage behind
 * the same interface (see db.ts). This file exists so Metro has something to
 * resolve `./sqlite` to on web that does not drag expo-sqlite — and its wasm
 * worker — into a bundle that would never call it.
 *
 * Throws rather than returning a stub: db.ts branches on platform before it
 * gets here, so reaching this is a bug, and a silent empty database would hide
 * it until somebody's round went missing.
 */
export async function openSqlite(): Promise<Db> {
  throw new Error("offline/sqlite: no SQLite on web — db.ts should have used the browser store");
}
