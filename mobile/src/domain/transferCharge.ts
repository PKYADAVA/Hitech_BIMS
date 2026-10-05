import { IconName } from "@/components/AppIcon";

/**
 * Transfer Charges — the register's filter strip, and the small state
 * machines the screens that draw it would otherwise each reinvent.
 *
 * The questions and their order are the web register's own (see
 * `TransferChargeAPI.get`'s query params), kept here once rather than
 * re-derived in a component. Nothing here decides an allocation split —
 * that is always asked of `previewAllocation` on the server, per the same
 * rule Petty Expense's domain module states.
 */

export interface TransferChargeStrip {
  from: string;
  to: string;
  status: string;
  chargeType: string;
  chargeScope: string;
  farm: string;
  branch: string;
  dcNo: string;
  vehicle: string;
}

export const EMPTY_STRIP: TransferChargeStrip = {
  from: "",
  to: "",
  status: "",
  chargeType: "",
  chargeScope: "",
  farm: "",
  branch: "",
  dcNo: "",
  vehicle: "",
};

/** Local YYYY-MM-DD. toISOString() would shift the day either side of UTC. */
export function isoDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate()
  ).padStart(2, "0")}`;
}

/** The window the register opens on, today included: thirty days in all —
 *  wider than Petty Expense's seven, because a Transfer Charge is raised
 *  against a trip that may be costed days after the stock actually moved. */
export function lastThirtyDays(today = new Date()): Pick<TransferChargeStrip, "from" | "to"> {
  const from = new Date(today);
  from.setDate(from.getDate() - 29);
  return { from: isoDate(from), to: isoDate(today) };
}

export function openingStrip(today = new Date()): TransferChargeStrip {
  return { ...EMPTY_STRIP, ...lastThirtyDays(today) };
}

/** Which summary figure is pressed, if any. */
export type TransferChargeTile = "" | "month" | "drafts" | "pending";

/**
 * What pressing a figure does to the strip: narrows to what it counts,
 * clearing the window/status it replaces. Pressing the same figure again
 * puts the register back to the window it opened on.
 */
export function transferChargeTileStrip(
  strip: TransferChargeStrip,
  tile: TransferChargeTile,
  pressed: TransferChargeTile,
  today = new Date()
): TransferChargeStrip {
  const same = tile === pressed;
  const next: TransferChargeStrip = { ...strip, from: "", to: "", status: "" };
  if (same) return { ...next, ...lastThirtyDays(today) };

  if (pressed === "month") {
    return {
      ...next,
      from: isoDate(new Date(today.getFullYear(), today.getMonth(), 1)),
      to: isoDate(today),
      status: "Posted",
    };
  }
  if (pressed === "drafts") return { ...next, status: "Draft" };
  if (pressed === "pending") return { ...next, status: "Pending Approval" };
  return next;
}

/** The strip as a query, with the blanks left out. */
export function transferChargeQuery(
  strip: TransferChargeStrip,
  search = ""
): Record<string, string> {
  const query: Record<string, string> = {};
  if (strip.from) query.from_date = strip.from;
  if (strip.to) query.to_date = strip.to;
  if (strip.status) query.status = strip.status;
  if (strip.chargeType) query.charge_type = strip.chargeType;
  if (strip.chargeScope) query.charge_scope = strip.chargeScope;
  if (strip.farm) query.farm = strip.farm;
  if (strip.branch) query.branch = strip.branch;
  if (strip.dcNo) query.dc_no = strip.dcNo;
  if (strip.vehicle) query.vehicle = strip.vehicle;
  if (search.trim()) query.dc_no = search.trim();
  return query;
}

/** A charge, as an icon — read off its charge types the way Petty Expense
 *  reads a spend off its category, so a type added in the master still
 *  lands somewhere sensible. */
export function chargeIcon(...chargeTypes: (string | undefined)[]): IconName {
  const text = chargeTypes.filter(Boolean).join(" ").toLowerCase();
  if (/transport|freight|vehicle|hire/.test(text)) return "truck";
  if (/unload|handling/.test(text)) return "dolly";
  if (/load/.test(text)) return "package-variant";
  if (/toll/.test(text)) return "road-variant";
  if (/weigh/.test(text)) return "scale-balance";
  return "receipt";
}

/** Rupees, exactly as Petty Expense's own register writes them. */
export { pettyMoney as transferChargeMoney } from "./pettyExpense";
/** A stored bill/receipt's address — no Transfer Charge-specific logic in
 *  this, so it is reused rather than duplicated. */
export { billUrl } from "./pettyExpense";

/** A line being typed, before it is worth sending to the server. */
export function lineIsBlank(line: { charge_type: string; total_amount?: string }): boolean {
  return !line.charge_type && !Number(line.total_amount || 0);
}
