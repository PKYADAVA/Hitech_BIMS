import { onlineManager } from "@tanstack/react-query";
import { Platform } from "react-native";

import { http } from "@/api/client";
import { persistForOffline } from "./files";
import { currentDeviceId, newLocalId, nextOfflineNumber } from "./identity";
import { currentQueueUser, insertEntry } from "./queue";
import { OfflineEntry, PRIORITY, SyncMethod } from "./types";

/**
 * One way through for every write: send it, or keep it until it can be sent.
 *
 * Screens call this instead of the http client so that "what happens with no
 * signal" is decided once, here, rather than differently in each form.
 */

export interface SaveBody {
  fields: Record<string, unknown>;
  /** Local uris of just-captured files, by the field they belong to. */
  files?: { field: string; uri: string }[];
}

export interface SaveSpec {
  /** Machine name for grouping and priority, e.g. "mortality". */
  type: string;
  /** What to call it on screen, e.g. "Mortality". */
  label: string;
  method: SyncMethod;
  path: string;
  body?: SaveBody | null;
  /** The business date, when the transaction has one distinct from today. */
  date?: string | null;
  /** Organisational keys, for the Sync Center and the admin monitor. */
  scope?: {
    employee_id?: string | number | null;
    company_id?: string | number | null;
    branch_id?: string | number | null;
    warehouse_id?: string | number | null;
    farm_id?: string | number | null;
    shed_id?: string | number | null;
    batch_id?: string | number | null;
  };
  gps?: { latitude: number; longitude: number; accuracy?: number | null } | null;
  /** Ask for a placeholder standing in for the id this write will create. */
  producesId?: boolean;
  /** local_id of an entry that must reach the ERP before this one. */
  dependsOn?: string | null;
}

export type SaveResult =
  /** It went. `data` is the ERP's row. */
  | { queued: false; data: unknown }
  /** It is on the phone. `ref` stands in for the row's id until it lands. */
  | { queued: true; localId: string; offlineNo: string; ref: string };

/**
 * Which entries go first.
 *
 * Named by transaction type rather than guessed from the path, so the decision
 * is reviewable by someone who knows the business and not only the code.
 * Anything unlisted sits in the middle: a new transaction type should be
 * neither privileged nor starved by having been forgotten here.
 */
const PRIORITY_BY_TYPE: Record<string, number> = {
  chicks_placement: PRIORITY.high,
  mortality: PRIORITY.high,
  feed_issue: PRIORITY.high,
  medicine_issue: PRIORITY.high,
  vaccination: PRIORITY.high,
  bird_dispatch: PRIORITY.high,
  stock_transfer: PRIORITY.high,
  feed_transfer: PRIORITY.high,
  purchase_receipt: PRIORITY.high,
  attendance: PRIORITY.high,

  daily_weight: PRIORITY.medium,
  feed_consumption: PRIORITY.medium,
  farm_visit: PRIORITY.medium,
  shed_inspection: PRIORITY.medium,
  egg_collection: PRIORITY.medium,
  production_entry: PRIORITY.medium,

  note: PRIORITY.low,
  photo: PRIORITY.low,
};

export function priorityFor(type: string): number {
  return PRIORITY_BY_TYPE[type] ?? PRIORITY.medium;
}

/** True when nothing came back, rather than the ERP ruling on the write. */
function isUnreachable(error: unknown): boolean {
  const status = (error as { status?: number })?.status;
  return status === undefined || status === null;
}

/**
 * Save it.
 *
 * With a signal the write goes straight out and the ERP's row comes back, as
 * it always did. Without one — or when the signal dies mid-request, which is
 * the same thing discovered later — it is written to the local database and
 * the user is told it is saved offline.
 *
 * A payload the ERP *rejects* is thrown to the caller either way. The user is
 * still looking at the form; filing an invalid entry for later would tell them
 * it worked and surface the failure hours afterwards, out of context.
 */
export async function saveOffline(spec: SaveSpec): Promise<SaveResult> {
  const localId = await newLocalId();
  const ref = `tmp:${localId}`;

  if (onlineManager.isOnline()) {
    try {
      return { queued: false, data: await sendNow(spec, localId) };
    } catch (error) {
      if (!isUnreachable(error)) throw error;
    }
  }

  // Photos are copied out of the camera's cache first: Android reclaims that
  // directory whenever it wants storage, and a queued entry would be left
  // pointing at nothing.
  const files = await Promise.all(
    (spec.body?.files ?? []).map((f) => persistForOffline(f.field, f.uri)));

  const now = new Date().toISOString();
  const offlineNo = await nextOfflineNumber();
  const scope = spec.scope ?? {};
  const str = (v: unknown) => (v == null || v === "" ? null : String(v));

  const entry: OfflineEntry = {
    local_id: localId,
    offline_no: offlineNo,
    server_id: null,
    transaction_type: spec.type,
    transaction_label: spec.label,
    transaction_date: spec.date ?? null,
    method: spec.method,
    path: spec.path,
    payload: spec.body?.fields ?? {},
    files,
    employee_id: str(scope.employee_id),
    user_id: currentQueueUser(),
    company_id: str(scope.company_id),
    branch_id: str(scope.branch_id),
    warehouse_id: str(scope.warehouse_id),
    farm_id: str(scope.farm_id),
    shed_id: str(scope.shed_id),
    batch_id: str(scope.batch_id),
    gps_latitude: spec.gps?.latitude ?? null,
    gps_longitude: spec.gps?.longitude ?? null,
    gps_accuracy: spec.gps?.accuracy ?? null,
    gps_captured_at: spec.gps ? now : null,
    device_id: await currentDeviceId(),
    priority: priorityFor(spec.type),
    depends_on: spec.dependsOn ?? null,
    produces_ref: spec.producesId ? ref : null,
    // The moment the user filed it. Never replaced by the sync time — the
    // difference between those two is the whole record of a round walked out
    // of range, and an entry stamped 11:47 when it was taken at 09:12 is a lie
    // about where somebody was.
    device_created_at: now,
    created_at: now,
    updated_at: now,
    sync_status: "pending",
    sync_attempts: 0,
    next_attempt_at: null,
    last_sync_at: null,
    sync_error: null,
    server_version: null,
    conflict: null,
  };
  await insertEntry(entry);
  return { queued: true, localId, offlineNo, ref };
}

async function sendNow(spec: SaveSpec, localId: string): Promise<unknown> {
  const headers: Record<string, string | undefined> = {
    "Idempotency-Key": localId,
    "X-Offline-Created-At": new Date().toISOString(),
  };
  if (spec.method === "DELETE") {
    return (await http.delete(spec.path, { headers })).data?.data;
  }
  const hasFiles = !!spec.body?.files?.length;
  let body: unknown = spec.body?.fields ?? {};
  if (hasFiles) {
    const form = new FormData();
    for (const [field, value] of Object.entries(spec.body!.fields)) {
      if (value === undefined || value === null) continue;
      form.append(field, String(value));
    }
    for (const { field, uri } of spec.body!.files!) {
      const name = uri.split("/").pop()?.split("?")[0] || `${field}.jpg`;
      if (Platform.OS === "web") {
        form.append(field, await (await fetch(uri)).blob(), name);
      } else {
        const { mimeFromName } = await import("@/capture");
        form.append(field, { uri, name, type: mimeFromName(name) } as unknown as Blob);
      }
    }
    body = form;
    headers["Content-Type"] = Platform.OS === "web" ? undefined : "multipart/form-data";
  }
  const method = spec.method.toLowerCase() as "post" | "put" | "patch";
  return (await http[method](spec.path, body, { headers })).data?.data;
}
