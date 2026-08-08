/**
 * What a write waiting to be sent looks like on disk.
 *
 * Kept apart from outbox.ts so the storage shape can be read without pulling
 * in AsyncStorage, the file system and the http client — the screens and the
 * tests both want the types, and neither wants the machinery.
 */

/** A file part of a multipart write, already copied somewhere durable. */
export interface OutboxFile {
  field: string;
  /** A path under the outbox directory — NOT the camera's cache uri. */
  uri: string;
  name: string;
  type: string;
}

export type OutboxMethod = "POST" | "PUT" | "PATCH" | "DELETE";

export interface OutboxEntry {
  /** Also the Idempotency-Key. Generated once and kept across every retry. */
  id: string;
  /** What to tell the user is waiting, e.g. "Daily Entry". */
  label: string;
  /**
   * Who queued it.
   *
   * Signing out does not throw the queue away — a day's entry filed with no
   * signal exists nowhere else, and discarding it because the shift ended
   * would lose the round. But it must not be sent under the next person's
   * token either, so each write remembers whose it is and only goes when that
   * user is signed in.
   */
  userId?: string;
  method: OutboxMethod;
  path: string;
  /** A JSON body, or the text fields of a multipart body when `files` is set. */
  body?: Record<string, unknown> | null;
  files?: OutboxFile[];
  /**
   * The placeholder this write's created id answers, e.g. "tmp:a1b2".
   *
   * A day's photos cannot be posted until the entry they hang off exists, and
   * offline it does not yet. The entry declares a placeholder here; the photo
   * writes reference it, and the real id is substituted when this one lands.
   */
  produces?: string;
  createdAt: number;
  attempts: number;
  lastError?: string;
  /** Set once the server has refused it for good — kept, but no longer sent. */
  rejected?: boolean;
}

/** What the UI needs to know, without reading the queue itself. */
export interface OutboxState {
  pending: number;
  rejected: number;
  sending: boolean;
}
