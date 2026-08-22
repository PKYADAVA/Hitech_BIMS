import { http } from "./client";
import { Envelope } from "./types";

export interface ReviewResult {
  status: string;
  id: number;
}

export interface CreateResult {
  id: number;
  message: string;
}

/**
 * Propose a change to a record on a module registered in the web's
 * CHANGE_REQUEST_HANDLERS (hatchery/change_requests.py) — the phone's way
 * into the same workflow the web's own /change_request_api/ offers, kept as
 * its own JWT-authenticated endpoint rather than the session+CSRF one.
 */
export async function createChangeRequest(
  module: string,
  objectId: number,
  action: "edit" | "delete",
  payload?: Record<string, unknown>,
  note?: string
): Promise<CreateResult> {
  const resp = await http.post<Envelope<CreateResult>>(
    "/hatchery/change-requests/create",
    { module, object_id: objectId, action, payload, note: note ?? "" }
  );
  return resp.data.data;
}

/** Approve or reject a pending change request (applies the payload on approve). */
export async function reviewChangeRequest(
  id: number,
  decision: "approve" | "reject",
  note?: string
): Promise<ReviewResult> {
  const resp = await http.post<Envelope<ReviewResult>>(
    `/hatchery/change-requests/${id}/${decision}`,
    note ? { review_note: note } : {}
  );
  return resp.data.data;
}
