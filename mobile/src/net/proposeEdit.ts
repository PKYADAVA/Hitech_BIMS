import { createChangeRequest } from "@/api/changeRequests";
import { Row } from "@/api/types";
import { editRequestModule } from "@/config/changeRequestModules";
import { notify } from "@/ui/confirm";

/**
 * Submit a correction as a proposal instead of writing it.
 *
 * A user without the edit right on a module can still say what a record
 * should say — the phone's half of the web's "Request modification", which
 * opens the same form and queues the result for someone who holds the right.
 * The payload is the same body the form would have written, because that is
 * exactly what the module's own save replays when the request is approved
 * (hatchery/change_requests.py, ChangeRequestReviewAPI). Sending anything
 * else here would mean an approved request writing something the requester
 * never saw.
 *
 * Deliberately not routed through writeThrough: a proposal is not the record,
 * so it must not be queued offline under the record's identity, stand in for
 * an id, or be replayed as a write if the phone syncs later. It either
 * reaches the queue now or it is reported as not sent.
 */
export async function submitEditProposal(
  resourceKey: string,
  row: Row,
  payload: Record<string, unknown>,
): Promise<boolean> {
  const module = editRequestModule(resourceKey);
  if (!module) {
    await notify("Cannot request this",
      "This register does not take edit requests. Ask someone with edit "
      + "rights to make the correction.");
    return false;
  }
  try {
    await createChangeRequest(module, row.id as number, "edit", payload);
    await notify("Sent for approval",
      "Your changes are queued. The record keeps its current values until "
      + "someone with edit rights approves them.");
    return true;
  } catch (e) {
    await notify("Could not send", (e as Error)?.message ?? "Please try again.");
    return false;
  }
}
