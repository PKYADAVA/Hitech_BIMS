import React from "react";

import { DatePickerProps, toISODate } from "./datePickerShared";

export { toISODate };
export type { DatePickerProps };

/**
 * The browser's own date control.
 *
 * RN Web renders through react-dom, so a plain <input> is legitimate here and
 * is the whole implementation — the browser already has a calendar, a keyboard
 * entry path and a locale, and every one of those would have to be rebuilt to
 * avoid it.
 *
 * Opened as soon as it mounts, so it behaves like the native sheet: the caller
 * renders it in response to a tap and expects a picker, not a field to find.
 */
export function DatePicker({ value, onPick, maximumDate }: DatePickerProps) {
  const ref = React.useRef<HTMLInputElement | null>(null);

  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;
    // showPicker() is the only way to open it without the user hunting for the
    // icon; not every browser has it, and there the input is still usable.
    try {
      (el as unknown as { showPicker?: () => void }).showPicker?.();
    } catch {
      el.focus();
    }
  }, []);

  return React.createElement("input", {
    ref,
    type: "date",
    value: value || "",
    max: maximumDate ? toISODate(maximumDate) : undefined,
    onChange: (e: { target: { value: string } }) => onPick(e.target.value || null),
    style: {
      font: "inherit", padding: "10px 12px", width: "100%",
      border: "1px solid #cbd5e1", borderRadius: 8, background: "#fff",
    },
  });
}
