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
  /** Which flock this is — shed it is housed in, breed, and bird type. All
   *  optional: an older server does not send them, and a batch need not have a
   *  shed or a breed on it. */
  shed_name?: string;
  breed_name?: string;
  bird_type?: string;
  /** Chicks placed, and the losses booked against them before this entry.
   *  Optional for the same reason — the summary is simply omitted without them. */
  opening_birds?: number;
  mortality_to_date?: number;
  culls_to_date?: number;
  sold_to_date?: number;
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
  /** Per feed type: what this phase needs for the flock, what has reached the
   *  farm, and what is left. Optional — an older server does not send it, and
   *  the panel simply omits the lines. */
  feed_plan?: FeedPlanRow[];
  /** What feed is actually on hand at the farm, whatever phase it belongs to. */
  farm_feed_stock?: { item: number; name: string; kg: string }[];
}

/** One feed type's position for this flock. `sent` is farm-level — a delivery
 *  is booked to the farm, not to a flock — which the wording reflects. */
export interface FeedPlanRow {
  item: number;
  name: string;
  cap_per_bird_kg: string;
  required_kg: string;
  sent_kg: string;
  fed_kg: string;
  balance_kg: string;
  remaining_kg: string;
  excess_kg: string | null;
}

/**
 * The kilos this row is about to feed, per item id.
 *
 * Both slots count, and they are summed rather than replacing one another: a
 * day that puts the same feed through Primary and Optional has fed the total
 * of the two, and taking only one of them understated what the flock ate.
 */
export function typedFeed(values: Record<string, string>): Record<string, number> {
  const out: Record<string, number> = {};
  for (const [slot, qty] of [["feed_1", "feed_1_qty"], ["feed_2", "feed_2_qty"]] as const) {
    const id = values[slot];
    const kg = num(values[qty]);
    if (!id || !kg) continue;
    out[id] = (out[id] ?? 0) + kg;
  }
  return out;
}

/** One feed's position, worked out for display. */
export interface FeedPlanLine {
  item: number;
  name: string;
  /** Phase cap times the flock this entry leaves behind. */
  required: number;
  sent: number;
  /** Fed to date plus what is being typed on this row. */
  fed: number;
  /** Sent less fed — what is in the farm's store. */
  balance: number;
  /** Required less fed — what is still owed to the phase. */
  remaining: number;
  /** The one thing worth saying about this row, worst first; "" when fine. */
  flag: string;
  warn: boolean;
}

/**
 * The feed plan as figures, ready to render.
 *
 * Kept here rather than in the screen so the arithmetic can be tested without
 * a rendering harness — it is the part that decides what a supervisor orders,
 * and it is recomputed on every keystroke.
 *
 * `typed` is the kilos being entered on this row, keyed by item id; `birds` is
 * the flock after this row's losses, because birds booked as dead do not eat.
 */
export function feedPlanLines(
  plan: FeedPlanRow[],
  typed: Record<string, number>,
  birds: number
): { lines: FeedPlanLine[]; total: Omit<FeedPlanLine, "item" | "name" | "flag" | "warn"> } {
  const total = { required: 0, sent: 0, fed: 0, balance: 0, remaining: 0 };
  const lines = plan.map((p) => {
    const fed = num(p.fed_kg) + (typed[String(p.item)] ?? 0);
    const required = num(p.cap_per_bird_kg) * birds;
    const sent = num(p.sent_kg);
    const balance = sent - fed;
    const remaining = required - fed;
    const over = sent - required;

    let flag = "";
    if (balance < 0) flag = `${Math.abs(balance).toFixed(0)} unreceived`;
    else if (remaining < 0) flag = `${Math.abs(remaining).toFixed(0)} over cap`;
    else if (over > 0) flag = `${over.toFixed(0)} extra sent`;

    total.required += required; total.sent += sent; total.fed += fed;
    total.balance += balance; total.remaining += remaining;
    return { item: p.item, name: p.name, required, sent, fed, balance, remaining,
             flag, warn: balance < 0 || remaining < 0 };
  });
  return { lines, total };
}

export type Tone = "ok" | "warn" | "bad" | "info";

export interface Hint {
  tone: Tone;
  text: string;
}

/** Overall state of the entry, mirroring the web's row status pill. */
export type EntryStatus = "ok" | "near" | "warn";

/** How far a capped feed item is through its kg/bird allowance — the web's
 *  "cumulative feed vs cap" bar. */
export interface CapProgress {
  name: string;
  /** Cumulative kg/bird of this item, including what is being typed. */
  cum: number;
  /** The phase's Max Feed Qty in kg/bird. */
  cap: number;
  pct: number;
  /** "cap reached — switch to X" / "nearing changeover", or blank. */
  note: string;
  tone: Tone;
}

export interface Advice {
  /** Per-field hints, keyed by form field name (feed_1, feed_2, avg_weight_gms…). */
  fieldHints: Record<string, Hint>;
  /** Standalone lines shown under the form (totals, weight, feed to date). */
  notes: Hint[];
  /** Human-readable problems, for the confirm-before-save prompt. */
  issues: string[];
  /** The changeover gauge, when a capped item is selected. */
  cap: CapProgress | null;
  status: EntryStatus;
  statusLabel: string;
}

/**
 * Feed typed on earlier rows of the same farm+batch but not yet saved.
 *
 * The web grid counts it (`priorListFeed`) so a row for age 7 sees the kilos
 * just typed for age 6 on top of the saved history. Without it every row of a
 * round would be advised as though it were the first.
 */
export interface PriorFeed {
  total: number;
  byItem: Record<string, number>;
}

export function priorListFeed(
  lookup: DailyEntryLookup | null,
  rowsAbove: FeedRow[]
): PriorFeed {
  const byItem: Record<string, number> = {};
  let total = 0;
  for (const r of rowsAbove) {
    for (const slot of ["feed_1", "feed_2"] as const) {
      const kg = num(r[`${slot}_qty`]);
      if (kg <= 0) continue;
      total += kg;
      const name = phaseOf(lookup, r[slot] ?? "")?.name ?? "Feed";
      byItem[name] = (byItem[name] ?? 0) + kg;
    }
  }
  return { total, byItem };
}

/**
 * Read one breed-standard column off the curve against another — weight at a
 * given cumulative feed, or the feed a bird should have eaten to reach a given
 * weight. Linear between the two rows that bracket the target, and clamped to
 * the ends rather than extrapolated past a curve that stops. (web `interpCurve`)
 */
export function interpCurve(
  curve: { a: number; w: number; cf: number }[],
  key: "w" | "cf",
  target: number | null,
  out: "w" | "cf"
): number | null {
  if (!curve.length || target == null) return null;
  if (target <= curve[0][key]) return curve[0][out];
  for (let i = 1; i < curve.length; i++) {
    if (target <= curve[i][key]) {
      const a = curve[i - 1], b = curve[i];
      const span = b[key] - a[key];
      const frac = span ? (target - a[key]) / span : 0;
      return a[out] + frac * (b[out] - a[out]);
    }
  }
  return curve[curve.length - 1][out];
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
  todayKg: number,
  /** Kilos of this item on earlier unsaved rows of the same farm+batch. */
  priorKg = 0
): number | null => {
  const birds = lookup?.live_birds ?? 0;
  if (!birds || !itemName) return null;
  let kg = todayKg + priorKg;
  for (const it of lookup?.consumed_by_item ?? []) {
    if (it.name === itemName) kg += num(it.kg);
  }
  return kg / birds;
};

/** Hint for one feed slot: right feed for the age, and how near its cap it is. */
const slotHint = (
  lookup: DailyEntryLookup | null,
  itemId: string,
  age: number,
  /** Cumulative kg/bird of a named item, counting both slots and earlier rows. */
  cumOf: (name: string) => number | null
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
  const cum = cap ? cumOf(phase.name) : null;

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
  opening?: Record<string, string>,
  /** Feed already typed on earlier rows of the same farm+batch (web `priorListFeed`). */
  prior?: PriorFeed
): Advice {
  const fieldHints: Record<string, Hint> = {};
  const notes: Hint[] = [];
  const issues: string[] = [];

  if (!lookup || !lookup.batch) {
    return { fieldHints, notes, issues, cap: null, status: "ok", statusLabel: "" };
  }

  const age = lookup.age_days;
  const qty1 = num(values.feed_1_qty);
  const qty2 = num(values.feed_2_qty);
  const total = qty1 + qty2;
  const birds = lookup.live_birds;
  const std = num(lookup.std_feed_kg);
  const priorTotal = prior?.total ?? 0;
  const priorByItem = prior?.byItem ?? {};

  /** Today's kilos of a named item, counting both slots — the same feed can be
   *  picked in Feed 1 and Feed 2, and it is still one item against one cap. */
  const todayKgOf = (name: string): number => {
    let kg = 0;
    for (const slot of ["feed_1", "feed_2"] as const) {
      if (phaseOf(lookup, values[slot] ?? "")?.name === name) kg += num(values[`${slot}_qty`]);
    }
    return kg;
  };
  const cumOf = (name: string): number | null =>
    cumPerBirdForItem(lookup, name, todayKgOf(name), priorByItem[name] ?? 0);

  let capReached = false;
  for (const slot of ["feed_1", "feed_2"] as const) {
    const r = slotHint(lookup, values[slot] ?? "", age, cumOf);
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

  // Cross-references off the breed curve, as the Live Flock report reads it:
  // what a bird at this weight should have eaten, and what a bird that has
  // eaten this much should weigh. Two ways of asking whether the flock is
  // getting value for the feed, and neither is answerable from today alone.
  const curve = lookup.bs_curve ?? [];
  const cumBeforeKg = num(lookup.cum_feed_before_kg) + priorTotal;
  if (curve.length && birds) {
    const cumPerBirdG = ((cumBeforeKg + total) / birds) * 1000;
    const bits: string[] = [];
    if (actW) {
      const stdFeedG = interpCurve(curve, "w", actW, "cf");
      if (stdFeedG != null) {
        bits.push(
          `Std feed @ this wt: ${stdFeedG.toFixed(0)} g/bird · ` +
            `${((stdFeedG * birds) / 1000).toFixed(1)} kg total`
        );
      }
    }
    if (cumPerBirdG > 0) {
      const stdWtG = interpCurve(curve, "cf", cumPerBirdG, "w");
      if (stdWtG != null) bits.push(`Std wt @ this feed: ${stdWtG.toFixed(0)} g`);
    }
    if (bits.length) notes.push({ tone: "info", text: bits.join("   ·   ") });
  }

  // The running total this entry rolls into: everything eaten before, what is
  // being typed, and where that leaves the flock. Split by item, because the
  // caps above are per item.
  const baseConsumed = num(lookup.consumed_total_kg) + priorTotal;
  if (baseConsumed > 0 || total > 0) {
    const merged: Record<string, number> = {};
    for (const it of lookup.consumed_by_item ?? []) {
      merged[it.name] = (merged[it.name] ?? 0) + num(it.kg);
    }
    for (const [k, v] of Object.entries(priorByItem)) merged[k] = (merged[k] ?? 0) + v;
    const items = Object.entries(merged)
      .sort((a, b) => b[1] - a[1])
      .map(([k, v]) => `${k} ${v.toFixed(1)}`)
      .join(" · ");
    const pb = (kg: number) => (birds ? ` · ${((kg / birds) * 1000).toFixed(1)} g/bird` : "");
    let text = `Consumed to date: ${baseConsumed.toFixed(1)} kg${pb(baseConsumed)}`;
    if (items) text += ` (${items})`;
    if (total > 0) {
      const newTotal = baseConsumed + total;
      text +=
        `  + this entry ${total.toFixed(1)} kg${pb(total)}` +
        ` → New total ${newTotal.toFixed(1)} kg${pb(newTotal)}`;
    }
    notes.push({ tone: "info", text });
  }

  // Feed per bird that actually survived. Divides each day's feed among the
  // birds alive that day, so it excludes the share eaten by birds since dead —
  // which total ÷ current-live silently credits to the survivors.
  if (lookup.consumed_per_bird_actual_g != null && birds) {
    const saved = num(lookup.consumed_per_bird_actual_g);
    const base = saved + (priorTotal / birds) * 1000;
    const next = saved + ((priorTotal + total) / birds) * 1000;
    notes.push({
      tone: "info",
      text:
        `Actual eaten / live bird: ${base.toFixed(1)} g` +
        (total > 0 ? ` → ${next.toFixed(1)} g with this entry` : "") +
        " (bird-day weighted, excludes dead-bird feed)",
    });
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

  // The feed plan is drawn as a grid by the screen (FeedPlanTable), not said
  // as sentences here: five numbers about three feeds ran past the height of
  // the phone as prose. The figures it needs travel on the lookup itself.

  // The changeover gauge: the first selected item that carries a kg/bird cap,
  // and how far through it the flock is. Returned rather than written as text
  // so the screen can draw the bar the web draws.
  let cap: CapProgress | null = null;
  for (const slot of ["feed_1", "feed_2"] as const) {
    const phase = phaseOf(lookup, values[slot] ?? "");
    if (!phase || !(phase.max > 0)) continue;
    const cum = cumOf(phase.name);
    if (cum == null) continue;
    const pct = (cum / phase.max) * 100;
    const next = lookup.feed_phase?.next_name;
    cap = {
      name: phase.name,
      cum,
      cap: phase.max,
      pct,
      note:
        pct >= 100
          ? `cap reached — switch${next ? ` to ${next}` : ""}`
          : pct >= CAP_NEAR * 100
          ? "nearing changeover"
          : "",
      tone: pct >= 100 ? "bad" : pct >= CAP_NEAR * 100 ? "warn" : "ok",
    };
    break;
  }

  // Hard problems read as Needs Review; a cap reached, or feed over standard
  // but inside tolerance, as Near Limit. Matches the web's row pill exactly —
  // the same entry must not be amber in the office and green in the shed.
  let status: EntryStatus = "ok";
  if (issues.length) status = "warn";
  else if (capReached) status = "near";
  else if (std && birds && total && total > std * birds) status = "near";
  const statusLabel =
    status === "warn" ? "Needs Review" : status === "near" ? "Near Limit" : "Within Standard";

  return { fieldHints, notes, issues, cap, status, statusLabel };
}


/**
 * Where the flock stands once this entry is applied: losses to date plus what
 * is being typed now, each as a share of the birds placed.
 *
 * Cumulative on purpose. The figure a supervisor is judging is the flock's
 * total mortality, not one day's, and it has to move as the day's number is
 * typed — a summary that only counted saved days would read 0 while a loss of
 * 200 sits on screen above it.
 *
 * Null when the server did not send an opening count (an older build, or a
 * batch with no placement recorded): a percentage of an unknown base would be
 * an invented number.
 */
export interface FlockSummary {
  opening: number;
  mortality: number;
  culls: number;
  live: number;
  /** Each as a percentage of `opening`. */
  mortalityPct: number;
  cullsPct: number;
  livePct: number;
}

export function flockSummary(
  lookup: DailyEntryLookup | null,
  values: Record<string, string>
): FlockSummary | null {
  const opening = lookup?.opening_birds ?? 0;
  if (!lookup || !opening) return null;
  const mortality = (lookup.mortality_to_date ?? 0) + num(values.mortality);
  const culls = (lookup.culls_to_date ?? 0) + num(values.culls);
  const sold = lookup.sold_to_date ?? 0;
  const live = Math.max(opening - mortality - culls - sold, 0);
  const pct = (n: number) => (n / opening) * 100;
  return {
    opening,
    mortality,
    culls,
    live,
    mortalityPct: pct(mortality),
    cullsPct: pct(culls),
    livePct: pct(live),
  };
}

/**
 * Today's feed against the breed standard, as the form's progress bar reads it.
 *
 * Everything is per *live* birds, not birds placed: the standard is a per-bird
 * figure and the birds that are gone are not eating. Null whenever either half
 * is unknown, so the bar is hidden rather than drawn against a zero standard.
 */
export interface FeedStandard {
  /** Kilos entered across both slots. */
  totalKg: number;
  /** Breed-standard kilos for the whole flock today. */
  stdKg: number;
  /** Grams per bird — entered, and the standard. */
  perBirdG: number;
  stdPerBirdG: number;
  /** Entered as a percentage of standard, for the bar. */
  pct: number;
}

export function feedStandard(
  lookup: DailyEntryLookup | null,
  values: Record<string, string>
): FeedStandard | null {
  const birds = lookup?.live_birds ?? 0;
  const stdPerBirdKg = num(lookup?.std_feed_kg);
  if (!birds || !stdPerBirdKg) return null;
  const totalKg = num(values.feed_1_qty) + num(values.feed_2_qty);
  const stdKg = stdPerBirdKg * birds;
  return {
    totalKg,
    stdKg,
    perBirdG: (totalKg / birds) * 1000,
    stdPerBirdG: stdPerBirdKg * 1000,
    pct: (totalKg / stdKg) * 100,
  };
}

/** Grams of feed per live bird for one slot — the per-slot figure beside each
 *  quantity. Null while the bird count is unknown. */
export function feedPerBirdG(qtyKg: number, birds: number): number | null {
  if (!birds) return null;
  return (qtyKg / birds) * 1000;
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

/**
 * Age of a flock on a given day, counting placement day as Age 0 — the same
 * count the server does, so the batch picker's "(Day 3)" and the age in the
 * flock panel cannot disagree. Null when the placement is unknown.
 */
export function ageOnDate(placedOn: string | null | undefined, on: string): number | null {
  if (!placedOn || !on) return null;
  const at = (iso: string) => {
    const [y, m, d] = iso.split("-").map(Number);
    return Date.UTC(y, m - 1, d);
  };
  return Math.max(Math.round((at(on) - at(placedOn)) / 86400000), 0);
}

/**
 * Tone for the feed bar, off the same thresholds the written advisories use —
 * the bar turning red while the line under it reads "within standard" would be
 * two answers to one question.
 */
export function feedTone(pct: number): Tone {
  if (!pct) return "info";
  if (pct > FEED_TOLERANCE * 100 || pct < FEED_LOW * 100) return "bad";
  if (pct > 100) return "warn";
  return "ok";
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
