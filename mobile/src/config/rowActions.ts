import { Row } from "@/api/types";
import { RecordAction } from "@/components/RecordCard";

/**
 * Extra actions a particular resource offers on its register card, beyond the
 * View / Edit / Delete every resource gets.
 *
 * Kept out of ResourceListScreen so the generic list does not accumulate
 * knowledge of individual modules, and out of the catalog so these can reach
 * navigation without dragging it into a config file.
 */

/**
 * Pushes one of the screens these actions use. Narrow on purpose: a `string`
 * here would need a cast at every call site and would let a typo through.
 */
export type RowActionNavigate = (
  screen: "SupervisorTripForm" | "FarmCaptureFill" | "BirdSalePhotos",
  params: { row: Row; ending?: boolean },
) => void;

/** What the asker may do here, so each action gates itself the way the ERP
 *  register gates its own button rather than all of them sharing one check. */
export interface RowActionPerms {
  add: boolean;
  edit: boolean;
  delete: boolean;
}

/**
 * Ending a trip opens the trip, rather than closing it where you stand.
 *
 * Ending is not a status flip — it is the moment the closing evidence is
 * recorded: the end photograph with its GPS stamp, and the end odometer that
 * the whole reimbursement is calculated from. Settling the trip straight off
 * the row would close it with neither, and the reading can only be read while
 * standing at the vehicle.
 *
 * Greyed out once settled rather than removed, so the row still shows the
 * action exists and the buttons do not shuffle about between an open trip and
 * a closed one.
 */
function endTripAction(row: Row, navigate: RowActionNavigate): RecordAction {
  const settled = row.status === "Completed";
  return {
    key: "end-trip",
    label: settled ? "Ended" : "End Trip",
    icon: "flag-checkered",
    danger: !settled,
    disabled: settled,
    onPress: () => navigate("SupervisorTripForm", { row, ending: true }),
  };
}

/**
 * Fill in what a capture is still missing — the register's "+".
 *
 * A visit is often recorded in pieces: the pin and the photographs on the
 * farm, the cheque scan when it turns up a week later. Editing the whole
 * capture to add one missing file invites overwriting what is already there,
 * so this only offers the blanks. Gated on *add* rather than edit, as the ERP
 * gates it: filling a blank is adding, not amending.
 */
function fillCaptureAction(row: Row, navigate: RowActionNavigate): RecordAction {
  return {
    key: "fill",
    label: "Fill",
    icon: "plus",
    onPress: () => navigate("FarmCaptureFill", { row }),
  };
}

/**
 * Drop the pin, keeping the visit.
 *
 * A wrong GPS reading is the thing that needs undoing; the pictures taken on
 * that visit are still good. Greyed when there is no location to clear, so the
 * row keeps its shape and the button says why it is idle.
 */
function clearLocationAction(row: Row, onClear: () => void): RecordAction {
  const pinned = row.latitude != null && row.longitude != null;
  return {
    key: "clear-location",
    label: pinned ? "Clear Pin" : "No Pin",
    icon: "eraser-variant",
    disabled: !pinned,
    onPress: onClear,
  };
}

/**
 * Attach the photographs a lifting was raised without.
 *
 * The evidence is often later than the sale: the weighbridge slip is handed
 * over after the truck has gone, and a sale raised at the desk from a slip
 * brought back has no pictures at all. Editing the sale to add one means
 * re-submitting a record that is already right — and re-submitting a lifting
 * is how a quantity gets changed by accident — so the upload stands on its own
 * and only ever adds.
 */
function uploadPhotosAction(row: Row, navigate: RowActionNavigate): RecordAction {
  return {
    key: "upload",
    label: "Upload",
    icon: "cloud-upload-outline",
    onPress: () => navigate("BirdSalePhotos", { row }),
  };
}

export function extraRowActions(
  resourceKey: string,
  row: Row,
  navigate: RowActionNavigate,
  perms: RowActionPerms,
  handlers?: { clearLocation?: (row: Row) => void },
): RecordAction[] {
  if (resourceKey === "hr-supervisor-trips") {
    return perms.edit ? [endTripAction(row, navigate)] : [];
  }
  if (resourceKey === "broiler-bird-sales") {
    // Gated on edit, as amending the sale is: this adds to a filed record.
    return perms.edit ? [uploadPhotosAction(row, navigate)] : [];
  }
  if (resourceKey === "broiler-farm-location-capture") {
    const out: RecordAction[] = [];
    if (perms.add) out.push(fillCaptureAction(row, navigate));
    if (perms.edit && handlers?.clearLocation) {
      out.push(clearLocationAction(row, () => handlers.clearLocation!(row)));
    }
    return out;
  }
  return [];
}
