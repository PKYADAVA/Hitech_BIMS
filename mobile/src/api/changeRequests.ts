import { http } from "./client";
import { Envelope } from "./types";

export interface ReviewResult {
  status: string;
  id: number;
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
