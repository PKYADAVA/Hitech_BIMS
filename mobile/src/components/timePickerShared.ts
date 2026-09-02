/**
 * The parts both time pickers need — mirrors datePickerShared.ts exactly, for
 * the same reason: a `.web` file cannot import from its own base name.
 */
export interface TimePickerProps {
  /** HH:MM (24-hour), or "" for none. */
  value: string;
  /** Called with HH:MM, or null when the user backed out. */
  onPick: (time: string | null) => void;
}

/** A Date's local time as HH:MM. */
export function toHHMM(d: Date): string {
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${hh}:${mm}`;
}

/** Parse "HH:MM" against today's date, or now() when blank/invalid. */
export function fromHHMM(value: string): Date {
  const m = /^(\d{1,2}):(\d{2})$/.exec(value || "");
  if (!m) return new Date();
  const h = Number(m[1]);
  const mm = Number(m[2]);
  if (h > 23 || mm > 59) return new Date();
  const d = new Date();
  d.setHours(h, mm, 0, 0);
  return d;
}
