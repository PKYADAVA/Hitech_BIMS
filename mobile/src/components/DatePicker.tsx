import DateTimePicker from "@react-native-community/datetimepicker";
import React from "react";
import { Platform } from "react-native";

import { DatePickerProps, toISODate } from "./datePickerShared";

export { toISODate };
export type { DatePickerProps };

/**
 * A calendar, on whichever platform is asking.
 *
 * @react-native-community/datetimepicker ships android, ios and windows and no
 * web build at all, so on the browser build it renders nothing — silently. The
 * date simply cannot be chosen, and nothing says why. This is the native half;
 * DatePicker.web.tsx is the browser's, and Metro picks between them.
 */
export function DatePicker({ value, onPick, maximumDate }: DatePickerProps) {
  return (
    <DateTimePicker
      value={value ? new Date(`${value}T00:00:00`) : new Date()}
      mode="date"
      maximumDate={maximumDate}
      display={Platform.OS === "ios" ? "inline" : "default"}
      onChange={(_e, d) => onPick(d ? toISODate(d) : null)}
    />
  );
}
