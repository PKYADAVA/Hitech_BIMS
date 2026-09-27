import { IconName } from "@/components/AppIcon";
import { PettyFilters } from "@/api/pettyExpenses";

/**
 * The register's two small decisions, kept out of the screens that draw it:
 * which window a pressed figure means, and which icon a spend wears.
 *
 * Both are read by people rather than by the server, so they are the parts
 * most worth pinning down in tests: a tile that narrows to the wrong window
 * is a figure that disagrees with its own list.
 */

/** Which figure is pressed, if any. */
export type PettyTile = "" | "today" | "month" | "drafts" | `box:${number}`;

/** Local YYYY-MM-DD. toISOString() would shift the day either side of UTC. */
export function isoDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate()
  ).padStart(2, "0")}`;
}

/**
 * What a pressed figure asks the register for.
 *
 * Drafts deliberately carries no dates: a draft can be any age, and a figure
 * counting every unposted expense that narrowed the list to this month would
 * show fewer rows than the number above it.
 */
export function pettyTileFilters(tile: PettyTile, today = new Date()): PettyFilters {
  if (tile === "today") return { from: isoDate(today), to: isoDate(today) };
  if (tile === "month") {
    return {
      from: isoDate(new Date(today.getFullYear(), today.getMonth(), 1)),
      to: isoDate(today),
    };
  }
  if (tile === "drafts") return { status: "Draft" };
  if (tile.startsWith("box:")) return { paid_from: tile.slice(4) };
  return {};
}

/** The window the filter strip asks for, before any figure narrows it. */
export function pettyRangeFilters(
  range: "all" | "today" | "week" | "month",
  today = new Date()
): PettyFilters {
  if (range === "today") return { from: isoDate(today), to: isoDate(today) };
  if (range === "week") {
    const from = new Date(today);
    from.setDate(from.getDate() - 6);
    return { from: isoDate(from), to: isoDate(today) };
  }
  if (range === "month") {
    return {
      from: isoDate(new Date(today.getFullYear(), today.getMonth(), 1)),
      to: isoDate(today),
    };
  }
  return {};
}

/**
 * A spend, as an icon — read off what it was for rather than off a code, so
 * a category added next week still lands somewhere sensible.
 */
export function pettyIcon(...parts: (string | undefined)[]): IconName {
  const text = parts.filter(Boolean).join(" ").toLowerCase();
  if (/fuel|diesel|petrol/.test(text)) return "fuel";
  if (/medicine|vaccin/.test(text)) return "pill";
  if (/transport|cartage|freight|vehicle/.test(text)) return "truck";
  if (/labour|wage|staff/.test(text)) return "account-group";
  if (/repair|maintenance|electric/.test(text)) return "wrench";
  if (/stationery|printing|office/.test(text)) return "file-document-outline";
  return "receipt";
}

/** Rupees, as the register writes them. */
export function pettyMoney(value: unknown): string {
  return `₹ ${Number(value || 0).toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

/** Qty × rate. An amount is computed, never typed. */
export function lineAmount(line: { quantity?: string; rate?: string }): number {
  return (Number(line.quantity) || 0) * (Number(line.rate) || 0);
}
