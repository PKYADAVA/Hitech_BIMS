import DateTimePicker from "@react-native-community/datetimepicker";
import React from "react";
import { Platform } from "react-native";

import { fromHHMM, TimePickerProps, toHHMM } from "./timePickerShared";

export { toHHMM };
export type { TimePickerProps };

/**
 * A clock, on whichever platform is asking — the time-side twin of
 * DatePicker.tsx. @react-native-community/datetimepicker ships no web build,
 * so this is the native half; TimePicker.web.tsx is the browser's.
 */
export function TimePicker({ value, onPick }: TimePickerProps) {
  return (
    <DateTimePicker
      value={fromHHMM(value)}
      mode="time"
      is24Hour
      display={Platform.OS === "ios" ? "spinner" : "default"}
      onChange={(_e, d) => onPick(d ? toHHMM(d) : null)}
    />
  );
}
