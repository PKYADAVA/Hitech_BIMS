import { saveOffline, SaveBody, SaveSpec } from "@/offline/save";
import { SyncMethod } from "@/offline/types";

/**
 * The write path the screens call.
 *
 * Kept as the app's own vocabulary over `offline/save`, which does the work.
 * The screens were written against this shape before the local database
 * existed, and changing every form to speak the new one would have been a lot
 * of churn for no behaviour — so the translation happens here, in one place,
 * where the defaults for an un-annotated caller are also decided.
 */

export type WriteBody = SaveBody;

export interface WriteSpec {
  /** What to call this on screen, e.g. "Daily Entry". */
  label: string;
  method: SyncMethod;
  path: string;
  body?: WriteBody | null;
  /** Ask for a placeholder standing in for the id this write will create. */
  producesId?: boolean;
  /** Machine name for grouping and sync priority; derived from the label if absent. */
  type?: string;
  /** The business date, when it differs from today. */
  date?: string | null;
  scope?: SaveSpec["scope"];
  gps?: SaveSpec["gps"];
  /** local_id of an entry that must reach the ERP first. */
  dependsOn?: string | null;
}

export type WriteResult =
  | { queued: false; data: unknown }
  | { queued: true; id: string; localId: string; offlineNo: string };

/** "Daily Entry" -> "daily_entry", so an un-annotated caller still groups. */
function typeFromLabel(label: string): string {
  return label.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
}

export async function writeThrough(spec: WriteSpec): Promise<WriteResult> {
  const result = await saveOffline({
    type: spec.type ?? typeFromLabel(spec.label),
    label: spec.label,
    method: spec.method,
    path: spec.path,
    body: spec.body,
    date: spec.date,
    scope: spec.scope,
    gps: spec.gps,
    producesId: spec.producesId,
    dependsOn: spec.dependsOn,
  });
  if (!result.queued) return result;
  return {
    queued: true,
    // `ref` is what a follow-up write puts where the id belongs; the engine
    // substitutes the real one once this entry lands.
    id: result.ref,
    localId: result.localId,
    offlineNo: result.offlineNo,
  };
}
