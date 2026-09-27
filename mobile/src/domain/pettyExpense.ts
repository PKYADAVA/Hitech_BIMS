import { Platform } from "react-native";

import { IconName } from "@/components/AppIcon";
import { MEDIA_BASE_URL } from "@/config";

/**
 * The register's filter strip, and the two small decisions the screens that
 * draw it would otherwise each make for themselves.
 *
 * The questions, their order and what a pressed figure does to them are the
 * web register's, not this screen's: the same people fill both in, and a
 * phone that filtered by its own rules would give a different answer to the
 * same question. Keeping it here means the rules are tested once rather than
 * re-derived in a component.
 */

/** Which figure is pressed, if any. */
export type PettyTile = "" | "today" | "month" | "drafts" | `box:${number}`;

/**
 * Everything the strip can ask, in the order the ERP asks it.
 *
 * Empty strings rather than undefined, because this is what a set of form
 * controls holds, and a control is never "absent" -- it is blank.
 */
export interface PettyStrip {
  from: string;
  to: string;
  month: string;
  year: string;
  branch: string;
  farm: string;
  /** Sub category: a postable expense ledger, which is what a line carries. */
  account: string;
  status: string;
  centre: string;
  paid_from: string;
  mode: string;
  paid_to: string;
  min: string;
  max: string;
}

export const EMPTY_STRIP: PettyStrip = {
  from: "",
  to: "",
  month: "",
  year: "",
  branch: "",
  farm: "",
  account: "",
  status: "",
  centre: "",
  paid_from: "",
  mode: "",
  paid_to: "",
  min: "",
  max: "",
};

/** Local YYYY-MM-DD. toISOString() would shift the day either side of UTC. */
export function isoDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate()
  ).padStart(2, "0")}`;
}

/** The window the register opens on, today included: seven days in all. */
export function lastSevenDays(today = new Date()): Pick<PettyStrip, "from" | "to"> {
  const from = new Date(today);
  from.setDate(from.getDate() - 6);
  return { from: isoDate(from), to: isoDate(today) };
}

/** The strip as the register opens it. */
export function openingStrip(today = new Date()): PettyStrip {
  return { ...EMPTY_STRIP, ...lastSevenDays(today) };
}

/**
 * What pressing a figure does to the strip.
 *
 * The ERP's own rules: a figure clears the window, the month, the year, the
 * status and the box before setting its own, so what the strip shows is
 * always what is being asked. Pressing the same figure again puts the
 * register back to the window it opened on, which is what the press replaced.
 *
 * Drafts deliberately sets no dates: a draft can be any age, and narrowing to
 * a window would show fewer rows than the figure above the list.
 */
export function pettyTileStrip(
  strip: PettyStrip,
  tile: PettyTile,
  pressed: PettyTile,
  today = new Date()
): PettyStrip {
  const same = tile === pressed;
  const next: PettyStrip = {
    ...strip,
    from: "",
    to: "",
    month: "",
    year: "",
    status: "",
    paid_from: "",
  };
  if (same) return { ...next, ...lastSevenDays(today) };

  if (pressed === "today") {
    return { ...next, from: isoDate(today), to: isoDate(today), status: "Posted" };
  }
  if (pressed === "month") {
    return {
      ...next,
      from: isoDate(new Date(today.getFullYear(), today.getMonth(), 1)),
      to: isoDate(today),
      status: "Posted",
    };
  }
  if (pressed === "drafts") return { ...next, status: "Draft" };
  if (pressed.startsWith("box:")) return { ...next, paid_from: pressed.slice(4) };
  return next;
}

/** The strip as a query, with the blanks left out. */
export function pettyQuery(strip: PettyStrip, search = ""): Record<string, string> {
  const query: Record<string, string> = {};
  (Object.keys(strip) as (keyof PettyStrip)[]).forEach((key) => {
    const value = strip[key].trim();
    if (value) query[key] = value;
  });
  if (search.trim()) query.q = search.trim();
  return query;
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

/**
 * A stored bill's address.
 *
 * The API returns media as a server-relative path ("/media/..."), which a
 * phone cannot resolve at all, so native hangs it off the base the client
 * already talks to.
 *
 * The browser must not: on web the API goes through the dev server's
 * same-origin proxy, while `MEDIA_BASE_URL` is whatever absolute base the
 * config settled on -- in a web build with no Metro host to learn from, that
 * is the production server, where a bill photographed against a local
 * database does not exist. A same-origin path goes to the proxy, which
 * forwards /media with the rest.
 */
export function billUrl(url: string): string {
  if (/^https?:\/\//i.test(url)) return url;
  const path = url.startsWith("/") ? url : `/${url}`;
  return Platform.OS === "web" ? path : `${MEDIA_BASE_URL}${path}`;
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

/** The twelve months, as the strip's picker offers them. */
export const MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];
