import DateTimePicker from "@react-native-community/datetimepicker";
import React, { useMemo, useState } from "react";
import {
  FlatList,
  Modal,
  Platform,
  Pressable,
  Switch,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { FormField } from "@/config/forms";
import { usePickerOptions } from "@/query/usePickerOptions";
import { makeStyles, radius, spacing, type, useTheme } from "@/theme";
import { formatDate } from "@/utils/format";
import { AppIcon } from "./AppIcon";
import { SearchBar } from "./ui";

/** Label + control + inline error wrapper shared by all field types. */
function FieldShell({
  label,
  required,
  error,
  children,
}: {
  label: string;
  required?: boolean;
  error?: string;
  children: React.ReactNode;
}) {
  const { colors } = useTheme();
  const styles = useStyles();
  return (
    <View style={styles.field}>
      <Text style={styles.label}>
        {label}
        {required ? <Text style={{ color: colors.danger }}> *</Text> : null}
      </Text>
      {children}
      {error ? <Text style={styles.error}>{error}</Text> : null}
    </View>
  );
}

export function FormControl({
  field,
  value,
  fallbackLabel,
  error,
  onChange,
}: {
  field: FormField;
  value: string;
  fallbackLabel?: string;
  error?: string;
  onChange: (v: string) => void;
}) {
  const { colors } = useTheme();
  const styles = useStyles();
  // Computed/derived fields: show the value in a muted, non-editable box.
  if (field.readOnly) {
    return (
      <FieldShell label={field.label} error={error}>
        <View style={[styles.input, styles.readonly]}>
          <Text style={styles.readonlyText}>{value || "0"}</Text>
        </View>
      </FieldShell>
    );
  }

  if (field.type === "boolean") {
    return (
      <FieldShell label={field.label} required={field.required} error={error}>
        <View style={styles.switchRow}>
          <Text style={styles.switchText}>{value === "true" ? "Yes" : "No"}</Text>
          <Switch
            value={value === "true"}
            onValueChange={(v) => onChange(v ? "true" : "false")}
            trackColor={{ true: colors.primary }}
          />
        </View>
      </FieldShell>
    );
  }

  if (field.type === "date") {
    return (
      <FieldShell label={field.label} required={field.required} error={error}>
        <DateControl value={value} onChange={onChange} />
      </FieldShell>
    );
  }

  if (field.type === "select") {
    return (
      <FieldShell label={field.label} required={field.required} error={error}>
        <SelectControl field={field} value={value} fallbackLabel={fallbackLabel} onChange={onChange} />
      </FieldShell>
    );
  }

  const numeric = field.type === "number" || field.type === "decimal";
  return (
    <FieldShell label={field.label} required={field.required} error={error}>
      <TextInput
        value={value}
        onChangeText={onChange}
        placeholder={field.label}
        placeholderTextColor={colors.textFaint}
        keyboardType={numeric ? "numeric" : "default"}
        multiline={field.type === "textarea"}
        style={[styles.input, field.type === "textarea" && styles.textarea]}
      />
    </FieldShell>
  );
}

function DateControl({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const styles = useStyles();
  const [show, setShow] = useState(false);
  const current = value ? new Date(value) : new Date();

  return (
    <>
      <Pressable style={styles.input} onPress={() => setShow(true)}>
        <Text style={value ? styles.inputText : styles.placeholder}>
          {value ? formatDate(value) : "Select date"}
        </Text>
      </Pressable>
      {show ? (
        <DateTimePicker
          value={isNaN(current.getTime()) ? new Date() : current}
          mode="date"
          display={Platform.OS === "ios" ? "inline" : "default"}
          onChange={(_e, d) => {
            setShow(Platform.OS === "ios");
            if (d) onChange(toISODate(d));
          }}
        />
      ) : null}
    </>
  );
}

function SelectControl({
  field,
  value,
  fallbackLabel,
  onChange,
}: {
  field: FormField;
  value: string;
  fallbackLabel?: string;
  onChange: (v: string) => void;
}) {
  const { colors } = useTheme();
  const styles = useStyles();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const { options, loading } = usePickerOptions(field.optionsPath, field.optionLabelKeys);

  const selectedLabel =
    options.find((o) => o.value === value)?.label ||
    (value ? fallbackLabel || `#${value}` : "");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? options.filter((o) => o.label.toLowerCase().includes(q)) : options;
  }, [options, query]);

  return (
    <>
      <Pressable style={styles.input} onPress={() => setOpen(true)}>
        <Text style={selectedLabel ? styles.inputText : styles.placeholder} numberOfLines={1}>
          {selectedLabel || `Select ${field.label.toLowerCase()}`}
        </Text>
        <AppIcon name="chevron-down" size={20} color={colors.textFaint} />
      </Pressable>

      <Modal visible={open} animationType="slide" onRequestClose={() => setOpen(false)}>
        <SafeAreaView style={styles.modal} edges={["top", "bottom"]}>
          <View style={styles.modalHeader}>
            <Text style={styles.modalTitle}>{field.label}</Text>
            <Pressable onPress={() => setOpen(false)} hitSlop={12}>
              <Text style={styles.modalClose}>Close</Text>
            </Pressable>
          </View>
          <View style={{ padding: spacing.md }}>
            <SearchBar value={query} onChangeText={setQuery} placeholder={`Search ${field.label}`} />
          </View>
          <FlatList
            data={filtered}
            keyExtractor={(o) => o.value}
            keyboardShouldPersistTaps="handled"
            automaticallyAdjustKeyboardInsets
            ListHeaderComponent={
              !field.required ? (
                <Pressable
                  style={styles.option}
                  onPress={() => {
                    onChange("");
                    setOpen(false);
                  }}
                >
                  <Text style={styles.optionClear}>— None —</Text>
                </Pressable>
              ) : null
            }
            ListEmptyComponent={
              <Text style={styles.empty}>{loading ? "Loading…" : "No options."}</Text>
            }
            renderItem={({ item }) => (
              <Pressable
                style={styles.option}
                onPress={() => {
                  onChange(item.value);
                  setOpen(false);
                }}
              >
                <Text style={styles.optionText}>{item.label}</Text>
                {item.value === value ? <AppIcon name="check" size={18} color={colors.primary} /> : null}
              </Pressable>
            )}
          />
        </SafeAreaView>
      </Modal>
    </>
  );
}

function toISODate(d: Date): string {
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
}

const useStyles = makeStyles((colors) => ({
  field: { marginBottom: spacing.lg },
  label: { ...type.label, color: colors.text, marginBottom: spacing.xs },
  error: { ...type.caption, color: colors.danger, marginTop: spacing.xs },
  input: {
    minHeight: 50,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    backgroundColor: colors.surface,
    color: colors.text,
    ...type.body,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  textarea: { minHeight: 90, textAlignVertical: "top", flexDirection: "column", alignItems: "stretch" },
  readonly: { backgroundColor: colors.surfaceAlt },
  readonlyText: { ...type.body, color: colors.textMuted, flex: 1 },
  inputText: { ...type.body, color: colors.text, flex: 1 },
  placeholder: { ...type.body, color: colors.textFaint, flex: 1 },
  caret: { color: colors.textMuted, fontSize: 14, marginLeft: spacing.sm },
  switchRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.md,
    height: 50,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
  },
  switchText: { ...type.body, color: colors.text },

  modal: { flex: 1, backgroundColor: colors.bg },
  modalHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    padding: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  modalTitle: { ...type.h3, color: colors.text },
  modalClose: { ...type.title, color: colors.primary },
  option: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.lg,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    backgroundColor: colors.surface,
  },
  optionText: { ...type.body, color: colors.text, flex: 1 },
  optionClear: { ...type.body, color: colors.textMuted },
  check: { color: colors.primary, ...type.title },
  empty: { ...type.body, color: colors.textMuted, textAlign: "center", padding: spacing.xl },
}));
