import AsyncStorage from "@react-native-async-storage/async-storage";
import { Platform } from "react-native";

import { http } from "@/api/client";
import { discardOutboxFile } from "./outboxFiles";
import { OutboxEntry, OutboxState } from "./outboxTypes";

/**
 * Writes made with no signal, held until there is one.
 *
 * The read cache already lets a supervisor open a register on a farm with no
 * bars. Saving was the half that still needed the network: the day's entry
 * failed, and the only record of the round was on paper — or nowhere.
 *
 * The queue is on disk, so it survives the app being killed on the walk back.
 * It is strictly in order and stops at the first entry that will not go: a
 * day's photos must not be posted before the entry they hang off, and a
 * correction must not overtake the row it corrects.
 *
 * Every entry carries an Idempotency-Key generated once and reused on every
 * retry, so an attempt that reached the server and lost its answer on the way
 * back is not performed twice (see api/middleware.py).
 */

const STORAGE_KEY = "bims_outbox_v1";
/** Given up on after this many tries — kept and shown, not silently dropped. */
const MAX_ATTEMPTS = 8;

let queue: OutboxEntry[] = [];
let loaded = false;
let sending = false;
let currentUserId: string | null = null;
const listeners = new Set<(state: OutboxState) => void>();

/**
 * Whose writes the queue is currently working on.
 *
 * Set when a session starts and cleared when it ends. Entries belonging to
 * anyone else stay on disk untouched — they are that person's unsent round,
 * not this session's, and sending them under this token would file them
 * against the wrong user.
 */
export function setOutboxUser(userId: string | null): void {
  currentUserId = userId;
  announce();
}

/** The entries this session may send or count. */
function mine(): OutboxEntry[] {
  return queue.filter((e) => !e.userId || e.userId === currentUserId);
}

// --- storage ---------------------------------------------------------------

async function load(): Promise<void> {
  if (loaded) return;
  try {
    const raw = await AsyncStorage.getItem(STORAGE_KEY);
    queue = raw ? (JSON.parse(raw) as OutboxEntry[]) : [];
  } catch {
    // A corrupt queue is worse than an empty one: it would block every write
    // behind an entry that can never be parsed, let alone sent.
    queue = [];
  }
  loaded = true;
}

async function save(): Promise<void> {
  try {
    await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(queue));
  } catch {
    // Out of storage. The entry is still in memory and will be sent this
    // session; losing it on a restart beats losing the user's whole save.
  }
}

// --- state for the UI ------------------------------------------------------

export function outboxState(): OutboxState {
  const ours = mine();
  return {
    pending: ours.filter((e) => !e.rejected).length,
    rejected: ours.filter((e) => e.rejected).length,
    sending,
  };
}

function announce(): void {
  const state = outboxState();
  listeners.forEach((fn) => fn(state));
}

export function subscribeToOutbox(fn: (state: OutboxState) => void): () => void {
  listeners.add(fn);
  void load().then(announce);
  return () => listeners.delete(fn);
}

/** The queue as it stands, for a screen that lists what is waiting. */
export async function pendingWrites(): Promise<OutboxEntry[]> {
  await load();
  return mine();
}

// --- adding ----------------------------------------------------------------

/** A key that is unique per write and stable across every retry of it. */
export function newWriteKey(): string {
  return `w-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/** A placeholder standing in for an id the server has not issued yet. */
export function placeholderFor(key: string): string {
  return `tmp:${key}`;
}

export async function enqueue(
  entry: Omit<OutboxEntry, "createdAt" | "attempts">
): Promise<OutboxEntry> {
  await load();
  const queued: OutboxEntry = {
    userId: currentUserId ?? undefined,
    ...entry,
    createdAt: Date.now(),
    attempts: 0,
  };
  queue.push(queued);
  await save();
  announce();
  return queued;
}

/** Forget an entry the server will never accept, at the user's say-so. */
export async function discardWrite(id: string): Promise<void> {
  await load();
  const entry = queue.find((e) => e.id === id);
  await Promise.all((entry?.files ?? []).map(discardOutboxFile));
  queue = queue.filter((e) => e.id !== id);
  await save();
  announce();
}

/** Let a given-up entry be tried again — the fix was at the other end. */
export async function retryWrite(id: string): Promise<void> {
  await load();
  const entry = queue.find((e) => e.id === id);
  if (entry) {
    entry.rejected = false;
    entry.attempts = 0;
    delete entry.lastError;
    await save();
    announce();
  }
}

/**
 * Empty it completely.
 *
 * Deliberately NOT called on sign-out: a day's entry filed with no signal
 * exists nowhere else, and throwing it away because the shift ended would lose
 * the round. Sign-out changes whose queue is active (see setOutboxUser); this
 * is for a user who has chosen to abandon what is waiting.
 */
export async function clearOutbox(): Promise<void> {
  await load();
  const dropping = mine();
  await Promise.all(dropping.flatMap((e) => (e.files ?? []).map(discardOutboxFile)));
  const keep = new Set(dropping.map((e) => e.id));
  queue = queue.filter((e) => !keep.has(e.id));
  await save();
  announce();
}

// --- sending ---------------------------------------------------------------

/**
 * Substitute the ids the server has issued into a write that was queued
 * before they existed.
 *
 * A photo queued offline points at "tmp:w-xyz" where the entry's id belongs.
 * Once that entry lands, its real id is known and every later reference to the
 * placeholder is rewritten. Values are compared as strings because the queue
 * has been through JSON and a form field is a string either way.
 */
export function resolvePlaceholders<T>(value: T, ids: Map<string, string>): T {
  if (typeof value === "string") {
    return (ids.get(value) ?? value) as unknown as T;
  }
  if (Array.isArray(value)) {
    return value.map((v) => resolvePlaceholders(v, ids)) as unknown as T;
  }
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      out[k] = resolvePlaceholders(v, ids);
    }
    return out as unknown as T;
  }
  return value;
}

/** True when the failure was the network rather than a verdict on the write. */
function isNetworkFailure(error: unknown): boolean {
  const status = (error as { status?: number })?.status;
  const code = (error as { code?: string })?.code;
  // No status at all means nothing came back. A 409 here is the server saying
  // an identical request is still in flight, and a 5xx is a server that may
  // recover — both are worth coming back to.
  if (status === undefined || status === null) return true;
  if (status === 409 && code === "idempotency_in_progress") return true;
  return status >= 500;
}

async function sendOne(entry: OutboxEntry, ids: Map<string, string>): Promise<unknown> {
  const path = resolvePlaceholders(entry.path, ids);
  const headers = { "Idempotency-Key": entry.id };

  if (entry.method === "DELETE") {
    return (await http.delete(path, { headers })).data?.data;
  }

  let body: unknown;
  let config: { headers: Record<string, string | undefined> } = { headers };
  if (entry.files?.length) {
    const form = new FormData();
    for (const [field, value] of Object.entries(resolvePlaceholders(entry.body ?? {}, ids))) {
      form.append(field, String(value));
    }
    for (const file of entry.files) {
      if (Platform.OS === "web") {
        form.append(file.field, await (await fetch(file.uri)).blob(), file.name);
      } else {
        form.append(file.field, {
          uri: file.uri, name: file.name, type: file.type,
        } as unknown as Blob);
      }
    }
    body = form;
    // The boundary has to come from the runtime on native and from the browser
    // on web; a hand-set multipart header with no boundary is rejected.
    config = {
      headers: {
        ...headers,
        "Content-Type": Platform.OS === "web" ? undefined : "multipart/form-data",
      },
    };
  } else {
    body = resolvePlaceholders(entry.body ?? {}, ids);
  }

  const method = entry.method.toLowerCase() as "post" | "put" | "patch";
  return (await http[method](path, body, config)).data?.data;
}

/**
 * Send everything waiting, oldest first, stopping at the first that will not go.
 *
 * Order is not an optimisation here. The photos of a day's entry reference the
 * entry by a placeholder, and skipping past a failed entry to send them would
 * post them against an id that does not exist. So a network failure ends the
 * flush and the rest keeps its place; only a write the server has *refused* is
 * stepped over, marked so the user can see it and decide.
 */
export async function flushOutbox(): Promise<{ sent: number; failed: number }> {
  await load();
  if (sending) return { sent: 0, failed: 0 };
  sending = true;
  announce();

  const ids = new Map<string, string>();
  let sent = 0;
  let failed = 0;

  try {
    for (const entry of mine()) {
      if (entry.rejected) continue;
      try {
        const result = await sendOne(entry, ids);
        if (entry.produces) {
          const created = (result as { id?: number | string } | undefined)?.id;
          if (created != null) ids.set(entry.produces, String(created));
        }
        await Promise.all((entry.files ?? []).map(discardOutboxFile));
        queue = queue.filter((e) => e.id !== entry.id);
        sent += 1;
        await save();
        announce();
      } catch (error) {
        entry.attempts += 1;
        entry.lastError = (error as { message?: string })?.message ?? "Could not send";
        if (isNetworkFailure(error) && entry.attempts < MAX_ATTEMPTS) {
          // Still worth coming back to, and nothing behind it may overtake it.
          await save();
          announce();
          break;
        }
        // The server has ruled on it, or it has been tried long enough. Keep
        // it — a rejected save the user never hears about is a lost record —
        // but let the rest of the queue past.
        entry.rejected = true;
        failed += 1;
        await save();
        announce();
      }
    }
  } finally {
    sending = false;
    announce();
  }
  return { sent, failed };
}
