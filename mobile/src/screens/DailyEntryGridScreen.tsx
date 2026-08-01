import { NativeStackScreenProps } from "@react-navigation/native-stack";
import React, { useCallback, useEffect, useLayoutEffect, useMemo, useState } from "react";
import { Alert, Pressable, Text, View } from "react-native";

import { createResource } from "@/api/resources";
import { ApiError } from "@/api/types";
import { FormControl } from "@/components/form";
import { KeyboardAwareScrollView } from "@/components/KeyboardAwareScrollView";
import { Button } from "@/components/ui";
import { dailyEntryLookup, FormField } from "@/config/forms";
import { adviseDailyEntry, DailyEntryLookup, Hint } from "@/domain/dailyEntry";
import { ModuleStackParams } from "@/navigation/types";
import { queryClient } from "@/query/queryClient";
import { makeStyles, radius, shadow, spacing, type } from "@/theme";

type Props = NativeStackScreenProps<ModuleStackParams, "DailyEntryGrid">;

const PATH = "/broiler/daily-entries/";

/**
 * Multi-farm Daily Entry — one date, several farms, one save.
 *
 * The web equivalent (`daily_entry_form.html`) is a wide spreadsheet grid,
 * which is unusable on a phone. This keeps the capability that matters — a
 * supervisor recording a whole round of farms in one pass — as a stack of
 * per-farm cards, each carrying the same fields, the same server-derived
 * batch/age, and the same advisories as the single form.
 *
 * Rows post one at a time: the API is per-record (`register_model`), and there
 * is no bulk endpoint to mirror the web view's array POST. A partial failure
 * therefore leaves the successful rows saved, so the summary reports exactly
 * which farms did not go through rather than implying all-or-nothing.
 */

const F_DATE: FormField = { name: "date", label: "Date", type: "date", required: true };
const F_SUPERVISOR: FormField = {
  name: "supervisor", label: "Supervisor", type: "select",
  optionsPath: "/broiler/supervisors/", optionLabelKeys: ["name"], required: true,
};
const F_FARM: FormField = {
  name: "farm", label: "Farm", type: "select",
  optionsPath: "/broiler/farms/", optionLabelKeys: ["farm_name", "farm_code"], required: true,
};
const F_MORTALITY: FormField = { name: "mortality", label: "Mortality", type: "number" };
const F_CULLS: FormField = { name: "culls", label: "Culls", type: "number" };
const F_FEED_1: FormField = {
  name: "feed_1", label: "Feed 1", type: "select",
  optionsPath: "/items/", optionLabelKeys: ["description", "item_code"],
};
const F_FEED_1_QTY: FormField = { name: "feed_1_qty", label: "Feed 1 Qty (kg)", type: "decimal" };
const F_FEED_2: FormField = {
  name: "feed_2", label: "Feed 2", type: "select",
  optionsPath: "/items/", optionLabelKeys: ["description", "item_code"],
};
const F_FEED_2_QTY: FormField = { name: "feed_2_qty", label: "Feed 2 Qty (kg)", type: "decimal" };
const F_AVG_WT: FormField = { name: "avg_weight_gms", label: "Avg Weight (g)", type: "decimal" };
const F_REMARKS: FormField = { name: "remarks", label: "Remarks", type: "text" };

/** One farm's row: its own values, its own server context, its own advice. */
interface GridRow {
  key: string;
  values: Record<string, string>;
  lookup: DailyEntryLookup | null;
}

let nextKey = 1;
const blankRow = (): GridRow => ({ key: `r${nextKey++}`, values: {}, lookup: null });

const num = (s?: string): number => Number(s) || 0;

export function DailyEntryGridScreen({ navigation }: Props) {
  const styles = useStyles();
  const [date, setDate] = useState<string>("");
  const [supervisor, setSupervisor] = useState<string>("");
  const [rows, setRows] = useState<GridRow[]>([blankRow()]);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  useLayoutEffect(() => {
    navigation.setOptions({ title: "Daily Entry — Multiple Farms" });
  }, [navigation]);

  /** Reload a row's advisory context whenever its farm, or the shared date, changes. */
  const loadLookup = useCallback(async (key: string, farm: string, on: string) => {
    if (!farm) {
      setRows((cur) => cur.map((r) => (r.key === key ? { ...r, lookup: null } : r)));
      return;
    }
    try {
      const lookup = await dailyEntryLookup(farm, on || undefined);
      setRows((cur) => cur.map((r) => (r.key === key ? { ...r, lookup } : r)));
      // The first farm picked seeds the shared date, matching the single form's
      // "continue the day after the last entry" behaviour.
      setDate((d) => d || lookup.next_date);
    } catch {
      // Advisory only — a failed lookup must not stop the round being recorded.
      setRows((cur) => cur.map((r) => (r.key === key ? { ...r, lookup: null } : r)));
    }
  }, []);

  // Changing the shared date re-advises every row that has a farm.
  useEffect(() => {
    if (!date) return;
    for (const r of rows) {
      if (r.values.farm) loadLookup(r.key, r.values.farm, date);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [date]);

  const setRowValue = (key: string, name: string) => (val: string) => {
    setRows((cur) =>
      cur.map((r) => (r.key === key ? { ...r, values: { ...r.values, [name]: val } } : r))
    );
    if (name === "farm") loadLookup(key, val, date);
  };

  const addRow = () => setRows((cur) => [...cur, blankRow()]);

  const removeRow = (key: string) =>
    setRows((cur) => (cur.length === 1 ? [blankRow()] : cur.filter((r) => r.key !== key)));

  /** Rows the user has actually filled in — a farm is the minimum to save one. */
  const filled = useMemo(() => rows.filter((r) => r.values.farm), [rows]);

  const advice = useMemo(
    () => new Map(rows.map((r) => [r.key, adviseDailyEntry(r.lookup, r.values)] as const)),
    [rows]
  );

  // The web grid's footer strip.
  const summary = useMemo(() => {
    let feed = 0, mortality = 0, culls = 0, latestWeight = 0;
    for (const r of filled) {
      feed += num(r.values.feed_1_qty) + num(r.values.feed_2_qty);
      mortality += num(r.values.mortality);
      culls += num(r.values.culls);
      if (num(r.values.avg_weight_gms)) latestWeight = num(r.values.avg_weight_gms);
    }
    return { rows: filled.length, feed, mortality, culls, latestWeight };
  }, [filled]);

  const onSave = async () => {
    setFormError(null);
    if (!filled.length) {
      setFormError("Add at least one farm before saving.");
      return;
    }
    if (!date || !supervisor) {
      setFormError("Date and Supervisor are required.");
      return;
    }

    const issues = filled.flatMap((r) => {
      const a = advice.get(r.key);
      return (a?.issues ?? []).map((i) => `${farmLabel(r)}: ${i}`);
    });
    if (issues.length) {
      const proceed = await new Promise<boolean>((resolve) =>
        Alert.alert(
          "Check before saving",
          `${issues.map((i) => `• ${i}`).join("\n")}\n\nSave anyway?`,
          [
            { text: "Go back", style: "cancel", onPress: () => resolve(false) },
            { text: "Save anyway", onPress: () => resolve(true) },
          ],
          { cancelable: false }
        )
      );
      if (!proceed) return;
    }

    setSaving(true);
    // Keyed by row, not by label: two farms can share a batch name, and a row
    // whose lookup failed has no name at all — matching on text would drop the
    // wrong rows from the retry list.
    const failures = new Map<string, string>();
    let saved = 0;
    for (const r of filled) {
      try {
        const body: Record<string, unknown> = { date, supervisor };
        for (const [k, v] of Object.entries(r.values)) {
          if (v !== "" && v != null) body[k] = v;
        }
        await createResource(PATH, body);
        saved += 1;
      } catch (e) {
        const msg =
          e instanceof ApiError
            ? e.message || Object.values(e.fields || {}).flat().join(" ")
            : (e as Error)?.message ?? "Failed";
        failures.set(r.key, `${farmLabel(r)}: ${msg}`);
      }
    }
    setSaving(false);
    queryClient.invalidateQueries({ queryKey: ["list", PATH] });

    if (!failures.size) {
      navigation.goBack();
      return;
    }
    // Saved rows stay saved — say so plainly rather than implying a rollback,
    // and keep only the failed rows on screen so a retry can't double-post one.
    setFormError(
      `Saved ${saved} of ${filled.length}. These were not saved:\n${[...failures.values()].join("\n")}`
    );
    setRows((cur) => cur.filter((r) => failures.has(r.key)));
  };

  return (
    <KeyboardAwareScrollView style={styles.screen} contentContainerStyle={styles.content}>
      {formError ? <Text style={styles.formError}>{formError}</Text> : null}

      <View style={styles.card}>
        <FormControl field={F_DATE} value={date} onChange={setDate} />
        <FormControl field={F_SUPERVISOR} value={supervisor} onChange={setSupervisor} />
        <Text style={styles.headerNote}>Applied to every farm below.</Text>
      </View>

      {rows.map((r, i) => {
        const a = advice.get(r.key);
        return (
          <View key={r.key} style={styles.card}>
            <View style={styles.rowHead}>
              <Text style={styles.rowTitle}>Farm {i + 1}</Text>
              <View style={styles.rowHeadRight}>
                {r.lookup?.batch_name ? (
                  <Text style={styles.rowMeta}>
                    {r.lookup.batch_name} · Age {r.lookup.age_days}
                    {r.lookup.live_birds ? ` · ${r.lookup.live_birds} birds` : ""}
                  </Text>
                ) : null}
                <Pressable onPress={() => removeRow(r.key)} hitSlop={8}>
                  <Text style={styles.remove}>Remove</Text>
                </Pressable>
              </View>
            </View>

            {a?.statusLabel && r.values.farm ? (
              <Text style={[styles.statusPill, styles[`pill_${a.status}`]]}>{a.statusLabel}</Text>
            ) : null}

            {[F_FARM, F_MORTALITY, F_CULLS, F_FEED_1, F_FEED_1_QTY, F_FEED_2, F_FEED_2_QTY,
              F_AVG_WT, F_REMARKS].map((f) => (
              <View key={f.name}>
                <FormControl
                  field={f}
                  value={r.values[f.name] ?? ""}
                  values={r.values}
                  onChange={setRowValue(r.key, f.name)}
                />
                {a?.fieldHints[f.name] ? <HintLine hint={a.fieldHints[f.name]} /> : null}
              </View>
            ))}

            {a?.notes.length ? (
              <View style={styles.notes}>
                {a.notes.map((n, k) => (
                  <HintLine key={k} hint={n} />
                ))}
              </View>
            ) : null}
          </View>
        );
      })}

      <Button title="Add another farm" variant="ghost" onPress={addRow} />

      <View style={styles.summary}>
        <Summary label="Rows" value={String(summary.rows)} />
        <Summary label="Total Feed" value={`${summary.feed.toFixed(2)} kg`} />
        <Summary label="Mortality" value={String(summary.mortality)} />
        <Summary label="Culls" value={String(summary.culls)} />
        <Summary label="Latest Wt" value={`${summary.latestWeight} g`} />
      </View>

      <Button
        title={`Save ${filled.length || ""} ${filled.length === 1 ? "entry" : "entries"}`.trim()}
        onPress={onSave}
        loading={saving}
      />
      <View style={{ height: spacing.xxl }} />
    </KeyboardAwareScrollView>
  );
}

const farmLabel = (r: GridRow): string => r.lookup?.batch_name || `Farm ${r.values.farm}`;

function HintLine({ hint }: { hint: Hint }) {
  const styles = useStyles();
  return <Text style={[styles.hint, styles[`hint_${hint.tone}`]]}>{hint.text}</Text>;
}

function Summary({ label, value }: { label: string; value: string }) {
  const styles = useStyles();
  return (
    <View style={styles.summaryCell}>
      <Text style={styles.summaryLabel}>{label}</Text>
      <Text style={styles.summaryValue}>{value}</Text>
    </View>
  );
}

const useStyles = makeStyles((colors) => ({
  screen: { flex: 1, backgroundColor: colors.bg },
  content: { padding: spacing.md, gap: spacing.md },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.md,
    ...shadow(1),
  },
  headerNote: { ...type.caption, color: colors.textMuted },
  rowHead: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: spacing.sm,
  },
  rowHeadRight: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  rowTitle: { ...type.h3, color: colors.text },
  rowMeta: { ...type.caption, color: colors.textMuted },
  remove: { ...type.label, color: colors.danger },
  hint: { ...type.label, marginTop: -spacing.xs, marginBottom: spacing.sm },
  hint_ok: { color: colors.success },
  hint_warn: { color: colors.warning },
  hint_bad: { color: colors.danger },
  hint_info: { color: colors.textMuted },
  notes: {
    borderTopWidth: 1,
    borderTopColor: colors.border,
    paddingTop: spacing.sm,
    gap: spacing.xs,
  },
  statusPill: {
    ...type.label,
    alignSelf: "flex-start",
    overflow: "hidden",
    borderRadius: 999,
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    marginBottom: spacing.sm,
  },
  pill_ok: { backgroundColor: colors.successLight, color: colors.success },
  pill_near: { backgroundColor: colors.warningLight, color: colors.warning },
  pill_warn: { backgroundColor: colors.dangerLight, color: colors.danger },
  summary: {
    flexDirection: "row",
    flexWrap: "wrap",
    backgroundColor: colors.surfaceAlt,
    borderRadius: radius.lg,
    padding: spacing.md,
    gap: spacing.md,
  },
  summaryCell: { minWidth: 80 },
  summaryLabel: { ...type.caption, color: colors.textMuted },
  summaryValue: { ...type.h3, color: colors.text },
  formError: {
    ...type.label,
    color: colors.danger,
    backgroundColor: colors.dangerLight,
    padding: spacing.md,
    borderRadius: radius.md,
  },
}));
