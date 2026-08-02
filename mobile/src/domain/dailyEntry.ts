/**
 * Daily Entry advisories — the checks the web form runs as you type.
 *
 * The web renders these in `daily_entry_single_form.html` / `daily_entry_form.html`
 * (`slotHint`, `renderInlineHints`, `rowNotification`). Everything they need is
 * computed server-side by `broiler.views.daily_entry_lookup_payload`, which the
 * app fetches from `/broiler/daily-entry-lookup`; this module is the same rules
 * applied to that payload, so a supervisor on a phone sees what the office sees.
 *
 * Pure and view-free on purpose: the single-entry form and the multi-row grid
 * both drive their hints from here, and the thresholds stay testable.
 *
 * None of it blocks a save. These are advisory — a farm genuinely can be off
 * standard, and a supervisor standing in the shed is the one who knows why.
 */

/** Allow 10% over the breed-standard daily feed before flagging (web FEED_TOLERANCE). */
const FEED_TOLERANCE = 1.1;
/** Below 50% of standard reads as under-feeding (web FEED_LOW). */
const FEED_LOW = 0.5;
/** Avg weight within ±10% of the breed standard counts as on-target. */
const WEIGHT_TOLERANCE_PCT = 10;
/** Warn once a phase is within 90% of its kg/bird cap — changeover is near. */
const CAP_NEAR = 0.9;

/** A feed item's place in the batch's feed program. */
export interface FeedPhaseItem {
  /** The feed item's description — also the key used by `consumed_by_item`. */
  name: string;
  /** [from_age, to_age] windows this item is used in; to_age null = open-ended. */
  ranges: [number, number | null][];
  /** Max Feed Qty in kg/bird for the phase — the changeover trigger. 0 = none. */
  max: number;
}

export interface FeedPhase {
  program: string;
  phase_name: string;
  phase_code: string;
  feed_item: number | null;
  max_feed_qty: string;
  /** The next phase to switch to, for the "switch to X" hint. */
  next_name: string;
  next_feed_item: number | null;
  phase_by_item: Record<string, FeedPhaseItem>;
}

/** `/broiler/daily-entry-lookup` — the advisory payload for a farm on a date. */
/** One batch still running on a farm, as offered by the lookup. */
export interface OpenBatch {
  id: number;
  name: string;
  placed_on: string | null;
}

export interface DailyEntryLookup {
  batch: number | null;
  batch_name: string;
  /** Every open batch on the farm. One means it is settled; more has to be
   *  asked, the same rule the web forms follow. Optional so an older server
   *  that does not send it still parses. */
  batches?: OpenBatch[];
  age_days: number;
  start_date: string | null;
  next_date: string;
  feed_phase: FeedPhase | null;
  /** Breed-standard feed for one bird on this day, in kg. */
  std_feed_kg: string | null;
  /** Breed-standard body weight at this age, in grams. */
  std_weight_g: string | null;
  /** Set when the breed standard can't answer (no curve, or age beyond it). */
  std_note: string | null;
  bs_curve: { a: number; w: number; cf: number }[];
  cum_feed_before_kg: string | null;
  consumed_by_item: { name: string; kg: string }[];
  consumed_total_kg: string | null;
  consumed_per_bird_actual_g: string | null;
  live_birds: number;
}

export type Tone = "ok" | "warn" | "bad" | "info";

export interface Hint {
  tone: Tone;
  text: string;
}

/** Overall state of the entry, mirroring the web's row status pill. */
export type EntryStatus = "ok" | "near" | "warn";

export interface Advice {
  /** Per-field hints, keyed by form field name (feed_1, feed_2, avg_weight_gms…). */
  fieldHints: Record<string, Hint>;
  /** Standalone lines shown under the form (totals, weight, feed to date). */
  notes: Hint[];
  /** Human-readable problems, for the confirm-before-save prompt. */
  issues: string[];
  status: EntryStatus;
  statusLabel: string;
}

const num = (s?: string | null): number => Number(s) || 0;

/** The feed program entry for a selected item id, or null if it isn't in one. */
export const phaseOf = (lookup: DailyEntryLookup | null, itemId: string): FeedPhaseItem | null =>
  (itemId && lookup?.feed_phase?.phase_by_item?.[itemId]) || null;

/** Does `age` fall in any of the item's [from, to] windows? (web `ageInRanges`) */
export const ageInRanges = (age: number, ranges: [number, number | null][]): boolean =>
  (ranges || []).some(([from, to]) => age >= from && (to === null || age <= to));

/**
 * Cumulative kg/bird of one feed item: everything eaten before today plus what
 * this entry adds. Null when the bird count is unknown, since the per-bird
 * figure would be meaningless. (web `cumPerBirdForItem`)
 */
export const cumPerBirdForItem = (
  lookup: DailyEntryLookup | null,
  itemName: string,
  todayKg: number
): number | null => {
  const birds = lookup?.live_birds ?? 0;
  if (!birds || !itemName) return null;
  let kg = todayKg;
  for (const it of lookup?.consumed_by_item ?? []) {
    if (it.name === itemName) kg += num(it.kg);
  }
  return kg / birds;
};

/** Hint for one feed slot: right feed for the age, and how near its cap it is. */
const slotHint = (
  lookup: DailyEntryLookup | null,
  itemId: string,
  qty: number,
  age: number
): { hint: Hint | null; issue: string | null; capReached: boolean } => {
  if (!itemId) return { hint: null, issue: null, capReached: false };

  const phase = phaseOf(lookup, itemId);
  if (!phase) {
    return { hint: { tone: "info", text: "Not in program" }, issue: null, capReached: false };
  }

  if (!ageInRanges(age, phase.ranges)) {
    const expected = lookup?.feed_phase?.phase_name ?? "";
    return {
      hint: { tone: "bad", text: `⚠ not for age ${age}` },
      issue: `"${phase.name}" isn't right for age ${age}${expected ? ` — use ${expected}` : ""}`,
      capReached: false,
    };
  }

  const cap = phase.max || 0;
  const cum = cap ? cumPerBirdForItem(lookup, phase.name, qty) : null;

  if (cap && cum != null && cum >= cap) {
    const next = lookup?.feed_phase?.next_name;
    return {
      hint: {
        tone: "warn",
        text: `⚠ ${cum.toFixed(3)}/${cap.toFixed(3)} kg/bird${next ? ` — switch to ${next}` : ""}`,
      },
      issue: `${phase.name} has reached its ${cap.toFixed(3)} kg/bird cap${
        next ? ` — switch to ${next}` : ""
      }`,
      capReached: true,
    };
  }

  if (cap && cum != null && cum >= cap * CAP_NEAR) {
    return {
      hint: { tone: "info", text: `${phase.name} ${cum.toFixed(3)}/${cap.toFixed(3)} kg/bird` },
      issue: null,
      capReached: false,
    };
  }

  return { hint: { tone: "ok", text: `✓ ${phase.name}` }, issue: null, capReached: false };
};

/**
 * Every advisory for one entry, from the lookup payload and the current values.
 *
 * `values` are the raw form strings (feed_1, feed_1_qty, feed_2, feed_2_qty,
 * avg_weight_gms), so both the single form and a grid row can call this with
 * whatever they hold.
 */
export function adviseDailyEntry(
  lookup: DailyEntryLookup | null,
  values: Record<string, string>,
  /**
   * Opening feed stock per slot ("feed_1"/"feed_2") from
   * `/broiler/daily-entry-stock`. Optional: without it the closing-stock lines
   * are simply omitted, which is what the grid does rather than firing two
   * extra requests per row.
   */
  opening?: Record<string, string>
): Advice {
  const fieldHints: Record<string, Hint> = {};
  const notes: Hint[] = [];
  const issues: string[] = [];

  if (!lookup || !lookup.batch) {
    return { fieldHints, notes, issues, status: "ok", statusLabel: "" };
  }

  const age = lookup.age_days;
  const qty1 = num(values.feed_1_qty);
  const qty2 = num(values.feed_2_qty);
  const total = qty1 + qty2;
  const birds = lookup.live_birds;
  const std = num(lookup.std_feed_kg);

  let capReached = false;
  for (const [slot, qty] of [
    ["feed_1", qty1],
    ["feed_2", qty2],
  ] as const) {
    const r = slotHint(lookup, values[slot] ?? "", qty, age);
    if (r.hint) fieldHints[slot] = r.hint;
    if (r.issue) issues.push(r.issue);
    if (r.capReached) capReached = true;
  }

  // Total feed against the breed standard for today's bird count.
  if (!std || !birds) {
    if (lookup.std_note) {
      notes.push({ tone: "warn", text: `⚠ ${lookup.std_note}` });
      issues.push(lookup.std_note);
    }
  } else {
    const expected = std * birds;
    const pct = expected ? Math.round((total / expected) * 100) : 0;
    if (!total) {
      notes.push({
        tone: "info",
        text: `Std ~${expected.toFixed(1)} kg/day (${birds} birds)`,
      });
    } else if (total > expected * FEED_TOLERANCE) {
      const text = `⚠ Total ${total.toFixed(1)} kg exceeds Std ${expected.toFixed(
        1
      )} kg/day (${pct}% of std)`;
      notes.push({ tone: "bad", text });
      issues.push(`Total feed ${total.toFixed(1)} kg is over the standard ${expected.toFixed(1)} kg/day`);
      fieldHints.feed_1_qty = { tone: "bad", text: `${pct}% of std` };
    } else if (total < expected * FEED_LOW) {
      const text = `⚠ Total ${total.toFixed(1)} kg is under half the Std ${expected.toFixed(
        1
      )} kg/day (${pct}% of std)`;
      notes.push({ tone: "bad", text });
      issues.push(`Total feed ${total.toFixed(1)} kg is well under the standard ${expected.toFixed(1)} kg/day`);
      fieldHints.feed_1_qty = { tone: "bad", text: `${pct}% of std` };
    } else if (total > expected) {
      notes.push({
        tone: "warn",
        text: `Total ${total.toFixed(1)} / ${expected.toFixed(1)} kg/day (${pct}% of std)`,
      });
    } else {
      notes.push({
        tone: "ok",
        text: `✓ Total ${total.toFixed(1)} / ${expected.toFixed(1)} kg/day (${pct}% of std)`,
      });
    }
  }

  // Average weight against the breed standard at this age.
  const stdW = num(lookup.std_weight_g);
  const actW = num(values.avg_weight_gms);
  if (stdW && !actW) {
    fieldHints.avg_weight_gms = { tone: "info", text: `Std ${stdW.toFixed(0)} g` };
  } else if (stdW && actW) {
    const diff = ((actW - stdW) / stdW) * 100;
    if (Math.abs(diff) <= WEIGHT_TOLERANCE_PCT) {
      fieldHints.avg_weight_gms = {
        tone: "ok",
        text: `✓ ${actW.toFixed(0)}/${stdW.toFixed(0)} g`,
      };
    } else {
      const sign = diff > 0 ? "+" : "";
      fieldHints.avg_weight_gms = {
        tone: "bad",
        text: `⚠ ${sign}${diff.toFixed(0)}% vs std ${stdW.toFixed(0)} g`,
      };
      issues.push(
        `Avg weight ${actW.toFixed(0)} g is ${sign}${diff.toFixed(0)}% against the standard ${stdW.toFixed(0)} g`
      );
    }
  }

  // Running feed stock, the web grid's Stock column: the opening balance the
  // server reports for this farm+item, less what this entry consumes. Shown per
  // slot because the two feeds carry independent balances.
  if (opening) {
    for (const [slot, qty] of [
      ["feed_1", qty1],
      ["feed_2", qty2],
    ] as const) {
      const itemId = values[slot];
      if (!itemId || opening[slot] == null) continue;
      const closing = num(opening[slot]) - qty;
      const name = phaseOf(lookup, itemId)?.name ?? "Feed";
      notes.push({
        tone: closing < 0 ? "bad" : "info",
        text: `${name} stock after this entry: ${closing.toFixed(2)} kg`,
      });
      if (closing < 0) {
        issues.push(`${name} stock goes negative (${closing.toFixed(2)} kg) — check the quantity`);
      }
    }
  }

  // Feed eaten so far — context for the caps above.
  if (lookup.consumed_total_kg && num(lookup.consumed_total_kg) > 0) {
    const perBird = lookup.consumed_per_bird_actual_g;
    notes.push({
      tone: "info",
      text:
        `Fed to date ${lookup.consumed_total_kg} kg` +
        (perBird ? ` (${perBird} g/bird)` : ""),
    });
  }

  const status: EntryStatus = issues.length ? "warn" : capReached ? "near" : "ok";
  const statusLabel =
    status === "warn" ? "Needs Review" : status === "near" ? "Near Limit" : "Within Standard";

  return { fieldHints, notes, issues, status, statusLabel };
}


/**
 * The day after `iso`, as an ISO date. Dates here are plain calendar days —
 * parsing them as timestamps drags the device's timezone in and can shift the
 * day, so the arithmetic is done on the parts.
 */
export function addDays(iso: string, days: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  const at = new Date(Date.UTC(y, m - 1, d + days));
  return at.toISOString().slice(0, 10);
}

/** Today as an ISO date in the device's own timezone, not UTC. */
export function todayISO(): string {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 10);
}


/** One row's feed slots, as the grid holds them. */
export interface FeedRow {
  farm: string;
  feed_1?: string;
  feed_1_qty?: string;
  feed_2?: string;
  feed_2_qty?: string;
}

/**
 * Feed left on the farm after a row is applied.
 *
 * `opening` is the farm's balance for that item before the row's date. Rows
 * above on the same farm and item are subtracted first, then the row's own
 * kgs — otherwise two rows feeding the same store would each claim the whole
 * opening balance, which is the web grid's running-stock behaviour.
 *
 * Both slots of every earlier row are counted: the same item can be picked in
 * Feed 1 on one row and Feed 2 on another and it is still one store.
 */
export function farmFeedBalance(
  opening: number,
  item: string,
  rowsAbove: FeedRow[],
  ownQty: number
): number {
  let balance = opening;
  for (const r of rowsAbove) {
    if (r.feed_1 === item) balance -= Number(r.feed_1_qty) || 0;
    if (r.feed_2 === item) balance -= Number(r.feed_2_qty) || 0;
  }
  return balance - ownQty;
}
