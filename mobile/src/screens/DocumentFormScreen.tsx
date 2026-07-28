import { NativeStackScreenProps } from "@react-navigation/native-stack";
import React, { useLayoutEffect, useState } from "react";
import { Alert, Pressable, StyleSheet, Text, View } from "react-native";

import { saveDocument } from "@/api/documents";
import { ApiError } from "@/api/types";
import { FormControl } from "@/components/form";
import { KeyboardAwareScrollView } from "@/components/KeyboardAwareScrollView";
import { Button, Card } from "@/components/ui";
import { RESOURCES } from "@/config/catalog";
import {
  BATCH_OPTIONS_PATH,
  DOCUMENTS,
  DocField,
  FARM_OPTIONS_PATH,
  WAREHOUSE_OPTIONS_PATH,
} from "@/config/documents";
import { FormField } from "@/config/forms";
import { ModuleStackParams } from "@/navigation/types";
import { queryClient } from "@/query/queryClient";
import { colors, radius, spacing, type } from "@/theme";
import { isEmpty } from "@/utils/format";

type Props = NativeStackScreenProps<ModuleStackParams, "DocumentForm">;
type Dict = Record<string, string>;

/** Map a plain DocField (text/date/number/decimal/select) to a FormField. */
const asFormField = (f: DocField): FormField => ({
  name: f.name,
  label: f.label,
  type: f.type as FormField["type"],
  required: f.required,
  optionsPath: f.optionsPath,
  optionLabelKeys: f.optionLabelKeys,
});

/** Warehouse/Farm segmented toggle + location picker (+ batch when a farm). */
function LocationControl({
  field,
  values,
  set,
}: {
  field: DocField;
  values: Dict;
  set: (key: string, val: string) => void;
}) {
  const type = values[`${field.name}_type`] || "warehouse";
  const idKey = `${field.name}_id`;
  const batchKey = `${field.name}_batch`;
  const onFarm = type === "farm";

  return (
    <View style={styles.locBlock}>
      <Text style={styles.locLabel}>
        {field.label}
        {field.required ? <Text style={{ color: colors.danger }}> *</Text> : null}
      </Text>
      {field.allowFarm ? (
        <View style={styles.toggleRow}>
          {(["warehouse", "farm"] as const).map((t) => {
            const on = type === t;
            return (
              <Pressable
                key={t}
                onPress={() => {
                  set(`${field.name}_type`, t);
                  set(idKey, "");
                  set(batchKey, "");
                }}
                style={[styles.toggle, on && styles.toggleOn]}
              >
                <Text style={[styles.toggleText, on && styles.toggleTextOn]}>
                  {t === "warehouse" ? "Warehouse" : "Farm"}
                </Text>
              </Pressable>
            );
          })}
        </View>
      ) : null}
      <FormControl
        field={{
          name: idKey,
          label: onFarm ? "Farm" : "Warehouse",
          type: "select",
          optionsPath: onFarm ? FARM_OPTIONS_PATH : WAREHOUSE_OPTIONS_PATH,
          optionLabelKeys: onFarm ? ["farm_name", "farm_code"] : ["name", "code"],
          required: field.required,
        }}
        value={values[idKey] ?? ""}
        onChange={(v) => set(idKey, v)}
      />
      {field.withBatch && onFarm ? (
        <FormControl
          field={{
            name: batchKey,
            label: "Batch",
            type: "select",
            optionsPath: BATCH_OPTIONS_PATH,
            optionLabelKeys: ["batch_name", "lot_no"],
          }}
          value={values[batchKey] ?? ""}
          onChange={(v) => set(batchKey, v)}
        />
      ) : null}
    </View>
  );
}

/** Add/Less style segmented toggle for a plain-choice field. */
function ToggleControl({
  field,
  value,
  onChange,
}: {
  field: DocField;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <View style={{ marginBottom: spacing.lg }}>
      <Text style={styles.locLabel}>
        {field.label}
        {field.required ? <Text style={{ color: colors.danger }}> *</Text> : null}
      </Text>
      <View style={styles.chipRow}>
        {(field.options ?? []).map((o) => {
          const on = value === o.value;
          return (
            <Pressable
              key={o.value}
              onPress={() => onChange(o.value)}
              style={[styles.chip, on && styles.chipOn]}
            >
              <Text style={[styles.chipText, on && styles.chipTextOn]}>{o.label}</Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

/** Renders any DocField by type (delegating plain types to FormControl). */
function DocFieldControl({
  field,
  values,
  set,
  error,
}: {
  field: DocField;
  values: Dict;
  set: (key: string, val: string) => void;
  error?: string;
}) {
  if (field.type === "location") return <LocationControl field={field} values={values} set={set} />;
  if (field.type === "toggle")
    return <ToggleControl field={field} value={values[field.name] ?? ""} onChange={(v) => set(field.name, v)} />;
  return (
    <FormControl
      field={asFormField(field)}
      value={values[field.name] ?? ""}
      error={error}
      onChange={(v) => set(field.name, v)}
    />
  );
}

/** Seed a values dict for a field set: toggle defaults + warehouse location type. */
const initValues = (fields: DocField[], extra: Dict = {}): Dict => {
  const v: Dict = { ...extra };
  for (const f of fields) {
    if (f.type === "toggle" && f.options?.length) v[f.name] = f.options[0].value;
    if (f.type === "location") v[`${f.name}_type`] = "warehouse";
  }
  return v;
};

export function DocumentFormScreen({ route, navigation }: Props) {
  const { resourceKey } = route.params;
  const doc = DOCUMENTS[resourceKey];
  const config = RESOURCES[resourceKey];

  const [header, setHeader] = useState<Dict>(() =>
    initValues(doc.header, { date: new Date().toISOString().slice(0, 10) })
  );
  const [items, setItems] = useState<Dict[]>(() => [initValues(doc.itemFields)]);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useLayoutEffect(() => {
    navigation.setOptions({ title: `New ${doc.title}` });
  }, [navigation, doc.title]);

  const setHeaderKey = (key: string, val: string) => setHeader((p) => ({ ...p, [key]: val }));
  const setItemKey = (idx: number, key: string, val: string) =>
    setItems((prev) => prev.map((it, i) => (i === idx ? { ...it, [key]: val } : it)));
  const addItem = () => setItems((prev) => [...prev, initValues(doc.itemFields)]);
  const removeItem = (idx: number) => setItems((prev) => prev.filter((_, i) => i !== idx));

  const onSave = async () => {
    setFormError(null);
    // Header required checks.
    for (const f of doc.header) {
      if (!f.required) continue;
      const missing =
        f.type === "location" ? isEmpty(header[`${f.name}_id`]) : isEmpty(header[f.name]);
      if (missing) {
        setFormError(`${f.label} is required.`);
        return;
      }
    }
    const payload = doc.build(header, items);
    // Guard: at least one usable line.
    const lineKey = Object.keys(payload).find((k) => Array.isArray((payload as never)[k]));
    const lines = lineKey ? ((payload as Record<string, unknown[]>)[lineKey] as unknown[]) : [];
    if (!lines || lines.length === 0) {
      setFormError("Add at least one complete line.");
      return;
    }

    setSaving(true);
    try {
      await saveDocument(doc.savePath, payload);
      queryClient.invalidateQueries({ queryKey: ["list", config.path] });
      navigation.navigate("List", { resourceKey });
    } catch (e) {
      if (e instanceof ApiError) setFormError(e.message || "Could not save.");
      else setFormError((e as Error)?.message ?? "Something went wrong.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <KeyboardAwareScrollView style={styles.screen} contentContainerStyle={styles.content}>
      {formError ? <Text style={styles.formError}>{formError}</Text> : null}

      {/* Header */}
      <Card style={styles.section}>
        {doc.header.map((f) => (
          <DocFieldControl key={f.name} field={f} values={header} set={setHeaderKey} />
        ))}
      </Card>

      {/* Line items */}
      <View style={styles.itemsHeader}>
        <Text style={styles.itemsTitle}>{doc.itemTitle}</Text>
        <Pressable hitSlop={8} onPress={addItem}>
          <Text style={styles.addLink}>＋ Add line</Text>
        </Pressable>
      </View>

      {items.map((it, idx) => (
        <Card key={idx} style={styles.itemCard}>
          <View style={styles.itemCardHead}>
            <Text style={styles.itemCardTitle}>Line {idx + 1}</Text>
            {items.length > 1 ? (
              <Pressable hitSlop={8} onPress={() => removeItem(idx)}>
                <Text style={styles.removeLink}>Remove</Text>
              </Pressable>
            ) : null}
          </View>
          {doc.itemFields.map((f) => (
            <DocFieldControl
              key={f.name}
              field={f}
              values={it}
              set={(key, val) => setItemKey(idx, key, val)}
            />
          ))}
        </Card>
      ))}

      <Button title="Create" onPress={onSave} loading={saving} />
      <View style={{ height: spacing.xxl }} />
    </KeyboardAwareScrollView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.bg },
  content: { padding: spacing.md },
  section: { marginBottom: spacing.md },
  formError: {
    ...type.label,
    color: colors.danger,
    backgroundColor: colors.dangerLight,
    padding: spacing.md,
    borderRadius: 12,
    marginBottom: spacing.md,
  },
  itemsHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: spacing.sm,
  },
  itemsTitle: { ...type.h3, color: colors.text },
  addLink: { ...type.title, color: colors.primary },
  itemCard: { marginBottom: spacing.md },
  itemCardHead: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: spacing.sm,
  },
  itemCardTitle: { ...type.label, color: colors.textMuted, textTransform: "uppercase", letterSpacing: 0.5 },
  removeLink: { ...type.label, color: colors.danger },

  locBlock: { marginBottom: spacing.lg },
  locLabel: { ...type.label, color: colors.text, marginBottom: spacing.xs },
  toggleRow: {
    flexDirection: "row",
    gap: spacing.sm,
    backgroundColor: colors.surfaceAlt,
    padding: 4,
    borderRadius: radius.md,
    marginBottom: spacing.sm,
  },
  toggle: { flex: 1, paddingVertical: spacing.sm, borderRadius: radius.sm, alignItems: "center" },
  toggleOn: { backgroundColor: colors.surface },
  toggleText: { ...type.label, color: colors.textMuted },
  toggleTextOn: { color: colors.primary, fontWeight: "800" },

  // Wrapping chip group (for choice fields with several options, e.g. pay mode).
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, marginBottom: spacing.sm },
  chip: {
    paddingVertical: spacing.xs,
    paddingHorizontal: spacing.md,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  chipOn: { backgroundColor: colors.primaryLight, borderColor: colors.primary },
  chipText: { ...type.label, color: colors.textMuted },
  chipTextOn: { color: colors.primaryDark, fontWeight: "800" },
});
