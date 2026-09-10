/**
 * Which of a row's values the form filled in, and what a fresh lookup may
 * change.
 *
 * A stock transfer's rate is the Item Price Master entry effective on the
 * row's date, so moving the date has to move the rate with it — but not over a
 * figure someone typed deliberately. "Is the box empty" cannot tell those
 * apart: once a lookup fills it, every later lookup sees a full box and backs
 * off, which is how a backdated row went on showing the price for the date it
 * used to have.
 *
 * So the row remembers. `AUTO_KEYS` holds the names of the fields whose value
 * came from a lookup; setting one by hand drops it from the list, and from
 * then on lookups leave it alone. It is internal to the form — every
 * `build()` names the fields it sends, so this never reaches a payload.
 */
type Dict = Record<string, string>;

export const AUTO_KEYS = "_auto";

export const autoSet = (row: Dict): Set<string> =>
  new Set((row[AUTO_KEYS] || "").split(",").filter(Boolean));

/** The auto list with the fields just set by hand removed. */
export const forgetTyped = (row: Dict, keys: string[]): string => {
  const auto = autoSet(row);
  for (const key of keys) auto.delete(key);
  return [...auto].join(",");
};

/**
 * Merge a lookup's answer into a row.
 *
 * A value lands in a box that is empty, or in one this filled in before. A
 * value that comes back empty — no price on this date — clears the box it
 * owns and releases it, so the next lookup can fill it again. Returns null
 * when nothing would change, so the caller can skip the state update.
 */
export const applyDerived = (row: Dict, found: Dict): Dict | null => {
  const auto = autoSet(row);
  const applied: Dict = {};
  for (const [key, value] of Object.entries(found)) {
    if (row[key] && !auto.has(key)) continue;        // theirs, not ours
    applied[key] = value;
    if (value) auto.add(key);
    else auto.delete(key);
  }
  if (!Object.keys(applied).length) return null;
  return { ...row, ...applied, [AUTO_KEYS]: [...auto].join(",") };
};
