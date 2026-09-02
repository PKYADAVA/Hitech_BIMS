import React from "react";

import { TimePickerProps } from "./timePickerShared";

export type { TimePickerProps };

/**
 * The browser's own time control — the web half of TimePicker, same
 * reasoning as DatePicker.web.tsx: react-dom is already here, so a plain
 * <input type="time"> is the whole implementation.
 *
 * Opened as soon as it mounts, so it behaves like the native sheet: the
 * caller renders it in response to a tap and expects a picker, not a field
 * to find.
 */
export function TimePicker({ value, onPick }: TimePickerProps) {
  const ref = React.useRef<HTMLInputElement | null>(null);

  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;
    try {
      (el as unknown as { showPicker?: () => void }).showPicker?.();
    } catch {
      el.focus();
    }
  }, []);

  return React.createElement("input", {
    ref,
    type: "time",
    value: value || "",
    onChange: (e: { target: { value: string } }) => onPick(e.target.value || null),
    style: {
      font: "inherit", padding: "10px 12px", width: "100%",
      border: "1px solid #cbd5e1", borderRadius: 8, background: "#fff",
    },
  });
}
