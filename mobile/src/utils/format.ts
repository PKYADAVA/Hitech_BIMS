import { Row } from "@/api/types";

/** True for null/undefined/"" — used to skip blank fields in the UI. */
export function isEmpty(v: unknown): boolean {
  return v === null || v === undefined || v === "";
}

/** "entry_no" → "Entry No", "avg_weight_gms" → "Avg Weight Gms". */
export function humanizeKey(key: string): string {
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .replace(/\bNo\b/, "No.")
    .replace(/\bId\b/, "ID")
    .replace(/\bDc\b/, "DC")
    .replace(/\bTcs\b/, "TCS")
    .trim();
}

/** Parse a YYYY-MM-DD (or ISO) into a friendly "12 Jul 2026". */
export function formatDate(value: unknown): string {
  if (isEmpty(value)) return "";
  const d = new Date(String(value));
  if (isNaN(d.getTime())) return String(value);
  return d.toLocaleDateString(undefined, {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

export function formatDateTime(value: unknown): string {
  if (isEmpty(value)) return "";
  const d = new Date(String(value));
  if (isNaN(d.getTime())) return String(value);
  return `${formatDate(value)} · ${d.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  })}`;
}

/** Group-separated number; trims trailing decimal zeros. */
export function formatNumber(value: unknown): string {
  if (isEmpty(value)) return "";
  const n = Number(value);
  if (isNaN(n)) return String(value);
  const rounded = Math.round(n * 100) / 100;
  return rounded.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

/** ₹ money for amount/rate fields. */
export function formatMoney(value: unknown): string {
  if (isEmpty(value)) return "";
  const n = Number(value);
  if (isNaN(n)) return String(value);
  return `₹${n.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

const DATE_KEY = /(^|_)(date|_date|received_date|created_at|updated_at|hatch_date|setting_date)$/;
const TIME_KEY = /(_time|created_at|updated_at)$/;
const MONEY_KEY = /(amount|rate|total|freight|price|profit|final_amount|avg_amount)$/;

/** Best-effort display of an arbitrary field value based on its key + type. */
export function formatValue(key: string, value: unknown): string {
  if (isEmpty(value)) return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (TIME_KEY.test(key)) return formatDateTime(value);
  if (key === "date" || key.endsWith("_date") || DATE_KEY.test(key)) return formatDate(value);
  if (MONEY_KEY.test(key) && !isNaN(Number(value))) return formatMoney(value);
  if (typeof value === "number") return formatNumber(value);
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** First present, non-empty candidate value as a display string, else fallback. */
export function pick(row: Row, keys: string[], fallback = ""): string {
  for (const key of keys) {
    const value = row[key];
    if (!isEmpty(value)) return String(value);
  }
  return fallback;
}

/** Join non-empty parts with a middot separator. */
export function joinParts(parts: (string | undefined | null)[], sep = "  ·  "): string {
  return parts.filter((p) => p && p.length > 0).join(sep);
}
