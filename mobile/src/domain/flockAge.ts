/**
 * A flock's age on a given date.
 *
 * Mirrors the web forms' rule exactly (`recomputeAge` in the Medicine and
 * Daily Entry templates, and `_apply_daily_entry_row` on the server): the
 * placement day is Age 0, and age is the whole days from placement to the
 * entry date. It follows the *entry date*, not today — a record back-dated on
 * the phone has to carry the age the flock actually was, or the phone and the
 * register disagree about the same row.
 */
export function ageAt(placedOn: string, date: string): string {
  if (!placedOn || !date) return "";
  const days = Math.round((Date.parse(date) - Date.parse(placedOn)) / 86400000);
  return String(Math.max(days, 0));
}
