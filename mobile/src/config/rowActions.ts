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
  screen: "SupervisorTripForm",
  params: { row: Row; ending: boolean },
) => void;

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

export function extraRowActions(
  resourceKey: string,
  row: Row,
  navigate: RowActionNavigate,
): RecordAction[] {
  if (resourceKey === "hr-supervisor-trips") {
    return [endTripAction(row, navigate)];
  }
  return [];
}
