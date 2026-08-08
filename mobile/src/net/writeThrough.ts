import { onlineManager } from "@tanstack/react-query";
import { Platform } from "react-native";

import { http } from "@/api/client";
import { enqueue, newWriteKey, placeholderFor } from "./outbox";
import { persistForOutbox } from "./outboxFiles";
import { OutboxMethod } from "./outboxTypes";

/**
 * One way through for every write, whether or not there is a signal.
 *
 * The body is described rather than pre-built: a FormData cannot be written to
 * disk and read back, so a write carrying a photo could never be queued if the
 * screens handed one over ready-made. Fields and files are kept apart until
 * the moment of sending, and the same description serves both paths.
 */
export interface WriteBody {
  fields: Record<string, unknown>;
  /** Local uris of just-captured files, by the field they belong to. */
  files?: { field: string; uri: string }[];
}

export interface WriteSpec {
  /** What to call this in the "waiting to send" list, e.g. "Daily Entry". */
  label: string;
  method: OutboxMethod;
  path: string;
  body?: WriteBody | null;
  /**
   * Ask for a placeholder standing in for the id this write will create.
   *
   * A day's photos cannot be posted before the entry they hang off exists.
   * Offline it does not, so the entry is queued with a placeholder and the
   * photos reference that; the real id is substituted when the entry lands.
   */
  producesId?: boolean;
}

export type WriteResult =
  /** It went. `data` is the server's row. */
  | { queued: false; data: unknown }
  /** It is on disk waiting for a signal. `id` stands in for the row's own. */
  | { queued: true; id: string };

/** Build the multipart body a described write needs, at the point of sending. */
export async function toFormData(body: WriteBody): Promise<FormData> {
  const form = new FormData();
  for (const [field, value] of Object.entries(body.fields)) {
    if (value === undefined || value === null) continue;
    form.append(field, String(value));
  }
  for (const { field, uri } of body.files ?? []) {
    const name = uri.split("/").pop()?.split("?")[0] || `${field}.jpg`;
    if (Platform.OS === "web") {
      form.append(field, await (await fetch(uri)).blob(), name);
    } else {
      const { mimeFromName } = await import("@/capture");
      form.append(field, { uri, name, type: mimeFromName(name) } as unknown as Blob);
    }
  }
  return form;
}

/** True when nothing came back, rather than the server ruling on the write. */
function isUnreachable(error: unknown): boolean {
  const status = (error as { status?: number })?.status;
  return status === undefined || status === null;
}

/**
 * Send it, or keep it until it can be sent.
 *
 * The key is generated here and travels with the write on every attempt, so a
 * request that reached the server and lost its answer on the way back is not
 * performed twice when the queue retries it.
 *
 * A write is only queued when the network is the problem. A rejected payload
 * is thrown to the caller as it always was: the user is still looking at the
 * form, and silently filing an invalid save for later would tell them it
 * worked and surface the failure hours afterwards, out of context.
 */
export async function writeThrough(spec: WriteSpec): Promise<WriteResult> {
  const key = newWriteKey();
  const produces = spec.producesId ? placeholderFor(key) : undefined;

  if (onlineManager.isOnline()) {
    try {
      return { queued: false, data: await sendNow(spec, key) };
    } catch (error) {
      if (!isUnreachable(error)) throw error;
    }
  }

  // Copy any photos somewhere that outlives the camera's cache before the
  // queue starts pointing at them.
  const files = await Promise.all(
    (spec.body?.files ?? []).map((f) => persistForOutbox(f.field, f.uri))
  );
  await enqueue({
    id: key,
    label: spec.label,
    method: spec.method,
    path: spec.path,
    body: (spec.body?.fields ?? null) as Record<string, unknown> | null,
    files: files.length ? files : undefined,
    produces,
  });
  return { queued: true, id: produces ?? key };
}

async function sendNow(spec: WriteSpec, key: string): Promise<unknown> {
  const headers: Record<string, string | undefined> = { "Idempotency-Key": key };

  if (spec.method === "DELETE") {
    return (await http.delete(spec.path, { headers })).data?.data;
  }

  const hasFiles = !!spec.body?.files?.length;
  const body = spec.body
    ? hasFiles
      ? await toFormData(spec.body)
      : spec.body.fields
    : {};
  if (hasFiles) {
    // The boundary comes from the runtime on native and from the browser on
    // web; a hand-set multipart header with no boundary is rejected.
    headers["Content-Type"] = Platform.OS === "web" ? undefined : "multipart/form-data";
  }
  const method = spec.method.toLowerCase() as "post" | "put" | "patch";
  return (await http[method](spec.path, body, { headers })).data?.data;
}
