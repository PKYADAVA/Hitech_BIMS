/**
 * Whether a lifting still needs somewhere on the map.
 *
 * The sale form takes a fix when it submits, so a sale raised at the farm
 * arrives with one. A sale raised at the desk, from a weighbridge slip carried
 * back, never went through that — and the photographs screen is where somebody
 * standing at the farm finally attaches its pictures. That is the only chance
 * those records get.
 *
 * The answer has to be no for a sale that already carries a pin. Photographs
 * are often added later and somewhere else; re-stamping would move a lifting
 * to the office a week afterwards and turn a true record into a false one.
 *
 * Half a pin is not a pin: a row carrying one coordinate and not the other
 * cannot be put on a map, so it counts as missing.
 */
export interface HasPin {
  lift_latitude?: unknown;
  lift_longitude?: unknown;
  // The rest of whatever row this is. Named fields alone make a "weak type",
  // which TypeScript refuses to accept a Row for — it shares no *declared*
  // property with it, Row being an index signature.
  [key: string]: unknown;
}

const given = (v: unknown): boolean =>
  v !== null && v !== undefined && String(v).trim() !== "";

export function needsPin(row: HasPin): boolean {
  return !(given(row.lift_latitude) && given(row.lift_longitude));
}
