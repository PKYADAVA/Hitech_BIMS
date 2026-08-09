/**
 * The parts both date pickers need.
 *
 * Separate because a `.web` file cannot import from its own base name: on web
 * `./DatePicker` resolves to DatePicker.web itself, and the import is a
 * self-reference that recurses until the stack gives out — a blank app and
 * "Maximum call stack size exceeded", with nothing pointing at the cause.
 */
export interface DatePickerProps {
  /** YYYY-MM-DD, or "" for none. */
  value: string;
  /** Called with YYYY-MM-DD, or null when the user backed out. */
  onPick: (date: string | null) => void;
  maximumDate?: Date;
}

/** Local YYYY-MM-DD — toISOString() would shift the day either side of UTC. */
export function toISODate(d: Date): string {
  return new Date(d.getTime() - d.getTimezoneOffset() * 60_000)
    .toISOString()
    .slice(0, 10);
}
