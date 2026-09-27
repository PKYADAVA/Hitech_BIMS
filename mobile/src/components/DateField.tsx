import React, { useState } from "react";
import { Pressable, Text, View } from "react-native";

import { makeStyles, radius, spacing, type } from "@/theme";
import { useTheme } from "@/theme/ThemeProvider";
import { formatDate } from "@/utils/format";

import { AppIcon } from "./AppIcon";
import { DatePicker } from "./DatePicker";

/**
 * A date, shown as a field and picked in the platform's own calendar.
 *
 * `DatePicker` is the calendar itself and opens the moment it mounts, so it
 * is rendered only while it is wanted and unmounted the instant a date comes
 * back. Left mounted, Android reopens it on every render and iOS leaves a raw
 * inline control under the field showing the same date twice.
 */
export function DateField({
  value,
  onChange,
  placeholder = "Any date",
  maximumDate,
  clearable,
}: {
  /** YYYY-MM-DD, or "" for none. */
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  maximumDate?: Date;
  /** Offer an X to empty it — for a filter, where blank means "all". */
  clearable?: boolean;
}) {
  const styles = useStyles();
  const { colors } = useTheme();
  const [open, setOpen] = useState(false);

  return (
    <View style={styles.wrap}>
      <Pressable style={styles.field} onPress={() => setOpen(true)}>
        <Text style={value ? styles.text : styles.blank} numberOfLines={1}>
          {value ? formatDate(value) : placeholder}
        </Text>
        {clearable && value ? (
          <Pressable
            hitSlop={10}
            onPress={() => onChange("")}
            accessibilityLabel="Clear the date"
          >
            <AppIcon name="close-circle" size={15} color={colors.textFaint} />
          </Pressable>
        ) : (
          <AppIcon name="calendar" size={15} color={colors.textFaint} />
        )}
      </Pressable>
      {open ? (
        <DatePicker
          value={value}
          maximumDate={maximumDate}
          onPick={(picked) => {
            setOpen(false);
            // null means the picker was backed out of, which is not an answer.
            if (picked) onChange(picked);
          }}
        />
      ) : null}
    </View>
  );
}

const useStyles = makeStyles((colors) => ({
  wrap: { flex: 1, minWidth: 0 },
  field: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: spacing.xs,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: 9,
    backgroundColor: colors.surface,
    minHeight: 38,
  },
  text: { ...type.caption, color: colors.text, flex: 1 },
  blank: { ...type.caption, color: colors.textFaint, flex: 1 },
}));
