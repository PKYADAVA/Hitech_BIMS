import { NativeStackScreenProps } from "@react-navigation/native-stack";
import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Alert, Pressable, Text, View } from "react-native";

import { createResource, listResource } from "@/api/resources";
import { Row } from "@/api/types";
import { ApiError } from "@/api/types";
import { FormControl } from "@/components/form";
import { KeyboardAwareScrollView } from "@/components/KeyboardAwareScrollView";
import { Button } from "@/components/ui";
import { dailyEntryLookup, dailyEntryStock, FormField } from "@/config/forms";
import {
  addDays, adviseDailyEntry, DailyEntryLookup, farmFeedBalance, FeedRow, Hint, todayISO,
} from "@/domain/dailyEntry";
import { ModuleStackParams } from "@/navigation/types";
import { useQuery } from "@tanstack/react-query";

import { queryClient } from "@/query/queryClient";
import { makeStyles, radius, shadow, spacing, type } from "@/theme";

type Props = NativeStackScreenProps<ModuleStackParams, "DailyEntryGrid">;

const PATH = "/broiler/daily-entries/";

/**
 * Multi-farm Daily Entry — several farms, one save.
 *
 * The web equivalent (`daily_entry_form.html`) is a wide spreadsheet grid,
 * which is unusable on a phone. This keeps the capability that matters — a
 * supervisor recording a whole round of farms in one pass — as a stack of
 * per-farm cards, each carrying the same fields, the same server-derived
 * batch/age, and the same advisories as the single form.
 *
 * Dates are not typed. Each row is dated the day after that farm's last
 * recorded entry, exactly as the web grid derives it, and a second row on the
 * same farm takes the next day again. A day past today is refused rather than
 * clamped — clamping would repeat the day above and read as a duplicate.
 *
 * Rows post one at a time: the API is per-record (`register_model`), and there
 * is no bulk endpoint to mirror the web view's array POST. A partial failure
 * therefore leaves the successful rows saved, so the summary reports exactly
 * which farms did not go through rather than implying all-or-nothing.
 */

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
  /** Derived, never typed: the day this row records. */
  date: string;
}

let nextKey = 1;
const blankRow = (): GridRow => ({ key: `r${nextKey++}`, values: {}, lookup: null, date: "" });

const num = (s?: string): number => Number(s) || 0;

export function DailyEntryGridScreen({ navigation }: Props) {
  const styles = useStyles();
  const [supervisor, setSupervisor] = useState<string>("");
  const [rows, setRows] = useState<GridRow[]>([blankRow()]);
  // Read inside async callbacks, which would otherwise close over a stale list.
  const rowsRef = useRef<GridRow[]>(rows);
  rowsRef.current = rows;
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  useLayoutEffect(() => {
    navigation.setOptions({ title: "Daily Entry — Multiple Farms" });
  }, [navigation]);

  /**
   * Date and advise one row from its own farm.
   *
   * Two passes, as the web does: the first asks what day this farm is due,
   * the second re-reads age, phase and live birds *as of* that day, because
   * every one of those is date-specific.
   */
  const loadLookup = useCallback(async (key: string, farm: string) => {
    if (!farm) {
      setRows((cur) =>
        cur.map((r) => (r.key === key ? { ...r, lookup: null, date: "" } : r))
      );
      return;
    }
    try {
      const base = await dailyEntryLookup(farm);
      // Earlier rows on the same farm each push this one a day further on.
      const earlier = rowsRef.current.filter(
        (r) => r.key !== key && r.values.farm === farm
      ).length;
      const target = earlier ? addDays(base.next_date, earlier) : base.next_date;
      if (target > todayISO()) {
        Alert.alert(
          "Nothing left to record",
          "This flock is already recorded up to today. Choose another farm for this row."
        );
        setRows((cur) =>
          cur.map((r) =>
            r.key === key
              ? { ...r, lookup: null, date: "", values: { ...r.values, farm: "" } }
              : r
          )
        );
        return;
      }
      const lookup = await dailyEntryLookup(farm, target);
      const open = lookup.batches ?? [];
      setRows((cur) =>
        cur.map((r) =>
          r.key === key
            ? {
                ...r,
                lookup,
                date: target,
                values: {
                  ...r.values,
                  // Settle it only when there is nothing to decide; two open
                  // flocks are the user's call, exactly as on the web.
                  batch: open.length === 1 ? String(open[0].id) : r.values.batch ?? "",
                },
              }
            : r
        )
      );
    } catch {
      // Advisory only — a failed lookup must not stop the round being recorded.
      setRows((cur) =>
        cur.map((r) => (r.key === key ? { ...r, lookup: null, date: "" } : r))
      );
    }
  }, []);

  const onSupervisorChange = (val: string) => {
    setSupervisor(val);
    // The farms on screen belong to the previous supervisor; clearing them is
    // what the web does rather than leaving a farm the new one does not run.
    setRows((cur) =>
      cur.map((r) => ({ ...r, values: { ...r.values, farm: "", batch: "" }, lookup: null, date: "" }))
    );
  };

  const setRowValue = (key: string, name: string) => (val: string) => {
    setRows((cur) =>
      cur.map((r) => (r.key === key ? { ...r, values: { ...r.values, [name]: val } } : r))
    );
    if (name === "farm") loadLookup(key, val);
  };

  /** A Batch picker, shown only when the farm has more than one open batch. */
  const batchField = (r: GridRow): FormField | null => {
    const open = r.lookup?.batches ?? [];
    if (open.length < 2) return null;
    return {
      name: "batch",
      label: "Batch",
      type: "select",
      required: true,
      options: open.map((b) => ({ value: String(b.id), label: b.name })),
    };
  };

  /** A new row starts on the row above's farm — a round is normally several
   *  days of the same flock, and re-picking it every time is the exception. */
  const addRow = () =>
    setRows((cur) => {
      const prev = [...cur].reverse().find((r) => r.values.farm);
      const fresh = blankRow();
      if (prev) {
        fresh.values.farm = prev.values.farm;
        setTimeout(() => loadLookup(fresh.key, prev.values.farm), 0);
      }
      return [...cur, fresh];
    });

  const removeRow = (key: string) =>
    setRows((cur) => (cur.length === 1 ? [blankRow()] : cur.filter((r) => r.key !== key)));

  const farmsQuery = useQuery({
    queryKey: ["picker", "/broiler/farms/", "with-supervisor"],
    staleTime: 5 * 60 * 1000,
    queryFn: () => listResource<Row>("/broiler/farms/", { page_size: 200 }),
  });

  /** Only this supervisor's farms, matching the web's cascade. Before one is
   *  chosen the list stays empty, so a farm cannot be picked out of order. */
  const farmField = useMemo((): FormField => {
    const all = farmsQuery.data?.items ?? [];
    const mine = supervisor
      ? all.filter((f) => String(f.supervisor ?? "") === String(supervisor))
      : [];
    return {
      ...F_FARM,
      options: mine.map((f) => ({
        value: String(f.id),
        label: String(f.farm_name ?? f.farm_code ?? `#${f.id}`),
      })),
    };
  }, [farmsQuery.data, supervisor]);

  /**
   * Opening feed stock per farm+item+date, as the web's running-stock preview
   * seeds itself. Cached by the three things that identify it, so switching
   * between rows on the same farm does not re-ask.
   */
  const [opening, setOpening] = useState<Record<string, number>>({});
  const stockKey = (farm: string, item: string, on: string) => `${farm}:${item}:${on}`;

  const needStock = useMemo(() => {
    const wanted: string[] = [];
    for (const r of rows) {
      if (!r.values.farm || !r.date) continue;
      for (const slot of ["feed_1", "feed_2"] as const) {
        const item = r.values[slot];
        if (item) wanted.push(stockKey(r.values.farm, item, r.date));
      }
    }
    return wanted;
  }, [rows]);

  useEffect(() => {
    const missing = needStock.filter((k) => !(k in opening));
    if (!missing.length) return;
    let live = true;
    (async () => {
      const found: Record<string, number> = {};
      for (const key of new Set(missing)) {
        const [farm, item, on] = key.split(":");
        try {
          found[key] = Number(await dailyEntryStock(farm, item, on)) || 0;
        } catch {
          // Advisory, like the rest of this screen: a stock read that fails
          // must not stop the round being recorded.
        }
      }
      if (live && Object.keys(found).length) setOpening((cur) => ({ ...cur, ...found }));
    })();
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [needStock.join("|")]);

  /**
   * Balance left on the farm for a row's feed slot: what was there before the
   * row's date, less every earlier row on the same farm and item, less this
   * row's own kgs. The web subtracts down the grid the same way, so two rows
   * feeding the same store do not each claim the whole opening balance.
   */
  const balanceFor = (row: GridRow, slot: "feed_1" | "feed_2"): number | null => {
    const item = row.values[slot];
    if (!item || !row.values.farm || !row.date) return null;
    const key = stockKey(row.values.farm, item, row.date);
    if (!(key in opening)) return null;
    const above: FeedRow[] = [];
    for (const r of rows) {
      if (r.key === row.key) break;                    // rows above only
      if (r.values.farm === row.values.farm) above.push(r.values as unknown as FeedRow);
    }
    return farmFeedBalance(opening[key], item, above, num(row.values[`${slot}_qty`]));
  };

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
    if (!supervisor) {
      setFormError("Supervisor is required.");
      return;
    }
    const undecided = filled.filter(
      (r) => (r.lookup?.batches?.length ?? 0) > 1 && !r.values.batch
    );
    if (undecided.length) {
      setFormError("Choose a Batch for every farm running more than one flock.");
      return;
    }
    const undated = filled.filter((r) => !r.date);
    if (undated.length) {
      setFormError("Still working out the date for every farm — try again in a moment.");
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
        const body: Record<string, unknown> = { date: r.date, supervisor };
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
        <FormControl field={F_SUPERVISOR} value={supervisor} onChange={onSupervisorChange} />
        <Text style={styles.headerNote}>
          Applied to every farm below. Each row is dated the day after that
          farm&apos;s last entry.
        </Text>
      </View>

      {rows.map((r, i) => {
        const a = advice.get(r.key);
        // A farm's rows are consecutive days of one flock, so they are headed
        // once and the days sit under it — the web grid's per-farm grouping.
        const firstOfFarm =
          !!r.values.farm &&
          rows.findIndex((x) => x.values.farm === r.values.farm) === i;
        const dayOfFarm =
          rows.filter((x, j) => j <= i && x.values.farm === r.values.farm).length;
        return (
          <View key={r.key}>
            {firstOfFarm ? (
              <Text style={styles.groupHead}>
                {r.lookup?.batch_name
                  ? `${r.lookup.batch_name}`
                  : `Farm ${r.values.farm}`}
              </Text>
            ) : null}
          <View style={styles.card}>
            <View style={styles.rowHead}>
              <Text style={styles.rowTitle}>
                {r.values.farm ? `Day ${dayOfFarm}` : `Farm ${i + 1}`}
                {r.date ? `  ·  ${r.date}` : ""}
              </Text>
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

            {[farmField, ...(batchField(r) ? [batchField(r)!] : []),
              F_MORTALITY, F_CULLS, F_FEED_1, F_FEED_1_QTY, F_FEED_2, F_FEED_2_QTY,
              F_AVG_WT, F_REMARKS].map((f) => {
              const slot =
                f.name === "feed_1_qty" ? "feed_1" : f.name === "feed_2_qty" ? "feed_2" : null;
              const balance = slot ? balanceFor(r, slot) : null;
              return (
                <View key={f.name}>
                  <FormControl
                    field={f}
                    value={r.values[f.name] ?? ""}
                    values={r.values}
                    onChange={setRowValue(r.key, f.name)}
                  />
                  {balance !== null ? (
                    <Text style={[styles.stock, balance < 0 ? styles.stockShort : null]}>
                      {balance < 0
                        ? `Short by ${Math.abs(balance).toFixed(2)} kg on the farm`
                        : `Farm balance after this: ${balance.toFixed(2)} kg`}
                    </Text>
                  ) : null}
                  {a?.fieldHints[f.name] ? <HintLine hint={a.fieldHints[f.name]} /> : null}
                </View>
              );
            })}

            {a?.notes.length ? (
              <View style={styles.notes}>
                {a.notes.map((n, k) => (
                  <HintLine key={k} hint={n} />
                ))}
              </View>
            ) : null}
          </View>
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
  groupHead: {
    ...type.label,
    color: colors.textMuted,
    marginTop: spacing.sm,
    marginBottom: spacing.xs,
    textTransform: "uppercase",
  },
  stock: {
    ...type.label,
    color: colors.textMuted,
    marginTop: -spacing.xs,
    marginBottom: spacing.sm,
  },
  stockShort: { color: colors.danger },
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
