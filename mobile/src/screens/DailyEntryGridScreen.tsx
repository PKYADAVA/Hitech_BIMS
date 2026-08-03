import { NativeStackScreenProps } from "@react-navigation/native-stack";
import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Alert, Pressable, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { createResource, listResource } from "@/api/resources";
import { Row } from "@/api/types";
import { ApiError } from "@/api/types";
import { appendImage, CapturedPoint, captureLocation, isLocalCapture } from "@/capture";
import { AppIcon, IconName } from "@/components/AppIcon";
import { FormControl } from "@/components/form";
import { KeyboardAwareScrollView } from "@/components/KeyboardAwareScrollView";
import { Button } from "@/components/ui";
import { dailyEntryLookup, dailyEntryStock, FormField } from "@/config/forms";
import {
  addDays, Advice, adviseDailyEntry, ageOnDate, CapProgress, DailyEntryLookup, farmFeedBalance,
  feedPerBirdG, feedStandard, feedTone, FeedRow, flockSummary, Hint, priorListFeed, PriorFeed,
  todayISO, Tone,
} from "@/domain/dailyEntry";
import { ModuleStackParams } from "@/navigation/types";
import { useQuery } from "@tanstack/react-query";

import { queryClient } from "@/query/queryClient";
import { makeStyles, radius, shadow, spacing, type, useTheme } from "@/theme";
import { formatDate } from "@/utils/format";

type Props = NativeStackScreenProps<ModuleStackParams, "DailyEntryGrid">;

const PATH = "/broiler/daily-entries/";

/**
 * Daily Entry — a supervisor's round of farms, recorded one farm at a time.
 *
 * The web equivalent (`daily_entry_form.html`) is a wide spreadsheet grid,
 * which is unusable on a phone. This keeps the capability that matters — a
 * supervisor recording a whole round in one pass — as a stack of per-farm
 * cards, each laid out as a full day record: who the flock is, where its
 * mortality stands, the day's numbers with photo evidence, a GPS stamp, and
 * the advisories the web form runs as you type.
 *
 * Pickers cascade Branch → Supervisor → Farm → Batch, so a farm can only be
 * reached through the branch and supervisor that actually run it.
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

/** The three photo columns, in the order the model names them. */
const PHOTO_FIELDS = ["mort_image", "cull_image", "feed_image"] as const;

const F_BRANCH: FormField = {
  name: "branch", label: "Branch", type: "select", required: true,
};
const F_SUPERVISOR: FormField = {
  name: "supervisor", label: "Supervisor", type: "select", required: true,
};
const F_FARM: FormField = { name: "farm", label: "Farm", type: "select", required: true };
const F_MORTALITY: FormField = { name: "mortality", label: "Mortality (Nos)", type: "number" };
const F_CULLS: FormField = { name: "culls", label: "Culls (Nos)", type: "number" };
const F_MORT_PHOTO: FormField = {
  name: "mort_image", label: "Photo (Mortality)", type: "photo", compact: true,
};
const F_CULL_PHOTO: FormField = {
  name: "cull_image", label: "Photo (Culls)", type: "photo", compact: true,
};
const F_FEED_PHOTO: FormField = {
  name: "feed_image", label: "Photo (Feed)", type: "photo", compact: true,
};
const F_FEED_1: FormField = {
  name: "feed_1", label: "Item", type: "select",
  optionsPath: "/items/", optionLabelKeys: ["description", "item_code"],
};
const F_FEED_1_QTY: FormField = { name: "feed_1_qty", label: "Qty (kg)", type: "decimal" };
const F_FEED_2: FormField = {
  name: "feed_2", label: "Item", type: "select",
  optionsPath: "/items/", optionLabelKeys: ["description", "item_code"],
};
const F_FEED_2_QTY: FormField = { name: "feed_2_qty", label: "Qty (kg)", type: "decimal" };
const F_AVG_WT: FormField = { name: "avg_weight_gms", label: "Avg. Weight (g)", type: "decimal" };
const F_REMARKS: FormField = { name: "remarks", label: "Remarks", type: "textarea" };

/** One farm's row: its own values, its own server context, its own advice. */
interface GridRow {
  key: string;
  values: Record<string, string>;
  lookup: DailyEntryLookup | null;
  /** Derived, never typed: the day this row records. */
  date: string;
  /** When the GPS fix on this row was taken — shown beside the coordinates. */
  locatedAt: Date | null;
  /** A capture is in flight; the button says so rather than looking dead. */
  locating: boolean;
  /** The last capture came back empty — permission off, or no fix. */
  locateFailed: boolean;
}

let nextKey = 1;
const blankRow = (): GridRow => ({
  key: `r${nextKey++}`,
  // Mortality and culls start at zero, not blank: a day with no losses is the
  // normal case, and leaving them empty makes "nothing happened" and "not yet
  // filled in" look identical on a card the supervisor is scanning.
  values: { mortality: "0", culls: "0" },
  lookup: null,
  date: "",
  locatedAt: null,
  locating: false,
  locateFailed: false,
});

const num = (s?: string): number => Number(s) || 0;

const hasFix = (r: GridRow): boolean => !!r.values.entry_latitude && !!r.values.entry_longitude;

export function DailyEntryGridScreen({ navigation }: Props) {
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const [branch, setBranch] = useState<string>("");
  const [supervisor, setSupervisor] = useState<string>("");
  const [rows, setRows] = useState<GridRow[]>([blankRow()]);
  // Read inside async callbacks, which would otherwise close over a stale list.
  const rowsRef = useRef<GridRow[]>(rows);
  rowsRef.current = rows;
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  useLayoutEffect(() => {
    navigation.setOptions({
      title: "Add Day Record",
      // Back to the register of saved entries — the screen this was opened from.
      headerRight: () => (
        <Pressable hitSlop={12} onPress={() => navigation.goBack()}>
          <View style={styles.headerBtn}>
            <AppIcon name="format-list-bulleted" size={16} color={colors.onDark} />
            <Text style={styles.headerBtnText}>Register</Text>
          </View>
        </Pressable>
      ),
    });
  }, [navigation, styles, colors]);

  const patchRow = useCallback((key: string, patch: Partial<GridRow>) => {
    setRows((cur) => cur.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  }, []);

  /**
   * Take a GPS fix for one row.
   *
   * Location is per row, not per screen: the rows are different farms in
   * different places, and the model stamps each entry with where it was
   * recorded. Called when a farm is picked so the fix is already in hand by
   * the time the card is filled in, and again from Retake / on submit.
   */
  const takeLocation = useCallback(
    async (key: string): Promise<CapturedPoint | null> => {
      patchRow(key, { locating: true, locateFailed: false });
      const point = await captureLocation();
      setRows((cur) =>
        cur.map((r) =>
          r.key === key
            ? {
                ...r,
                locating: false,
                locateFailed: !point,
                locatedAt: point ? new Date() : r.locatedAt,
                values: point
                  ? { ...r.values, entry_latitude: point.latitude, entry_longitude: point.longitude }
                  : r.values,
              }
            : r
        )
      );
      // Returned as well as stored: `onSave` needs the coordinates *now*, and
      // the state it just wrote will not have re-rendered by the next line.
      return point;
    },
    [patchRow]
  );

  /**
   * Date and advise one row from its own farm.
   *
   * Two passes, as the web does: the first asks what day this farm is due,
   * the second re-reads age, phase and live birds *as of* that day, because
   * every one of those is date-specific.
   */
  const loadLookup = useCallback(
    async (key: string, farm: string, batch?: string) => {
      if (!farm) {
        setRows((cur) => cur.map((r) => (r.key === key ? { ...r, lookup: null, date: "" } : r)));
        return;
      }
      try {
        const base = await dailyEntryLookup(farm, undefined, batch);
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
        const lookup = await dailyEntryLookup(farm, target, batch);
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
                    batch: batch ?? (open.length === 1 ? String(open[0].id) : r.values.batch ?? ""),
                  },
                }
              : r
          )
        );
      } catch {
        // Advisory only — a failed lookup must not stop the round being recorded.
        setRows((cur) => cur.map((r) => (r.key === key ? { ...r, lookup: null, date: "" } : r)));
      }
    },
    []
  );

  /** Clearing everything under a picker that changed: the rows below belong to
   *  the branch/supervisor that was chosen before, not the new one. */
  const resetRows = () =>
    setRows((cur) =>
      cur.map((r) => ({
        ...r,
        values: { ...r.values, farm: "", batch: "" },
        lookup: null,
        date: "",
      }))
    );

  const onBranchChange = (val: string) => {
    setBranch(val);
    setSupervisor("");
    resetRows();
  };

  const onSupervisorChange = (val: string) => {
    setSupervisor(val);
    resetRows();
  };

  const setRowValue = (key: string, name: string) => (val: string) => {
    setRows((cur) =>
      cur.map((r) => (r.key === key ? { ...r, values: { ...r.values, [name]: val } } : r))
    );
    if (name === "farm") {
      loadLookup(key, val);
      // Start the fix now rather than at save time: a rural fix can take a
      // while, and the card takes a while to fill in — run them together.
      if (val) takeLocation(key);
    }
    // A different flock has a different age, phase and standard, so the whole
    // advisory context is re-read for the batch the user actually chose.
    if (name === "batch") {
      const row = rowsRef.current.find((r) => r.key === key);
      if (row?.values.farm && val) loadLookup(key, row.values.farm, val);
    }
  };

  /** A new row starts on the row above's farm — a round is normally several
   *  days of the same flock, and re-picking it every time is the exception. */
  const addRow = () =>
    setRows((cur) => {
      const prev = [...cur].reverse().find((r) => r.values.farm);
      const fresh = blankRow();
      if (prev) {
        fresh.values.farm = prev.values.farm;
        setTimeout(() => {
          loadLookup(fresh.key, prev.values.farm);
          takeLocation(fresh.key);
        }, 0);
      }
      return [...cur, fresh];
    });

  const removeRow = (key: string) =>
    setRows((cur) => (cur.length === 1 ? [blankRow()] : cur.filter((r) => r.key !== key)));

  const branchesQuery = useQuery({
    queryKey: ["picker", "/broiler/branches/"],
    staleTime: 5 * 60 * 1000,
    queryFn: () => listResource<Row>("/broiler/branches/", { page_size: 200 }),
  });
  const supervisorsQuery = useQuery({
    queryKey: ["picker", "/broiler/supervisors/", "with-branch"],
    staleTime: 5 * 60 * 1000,
    queryFn: () => listResource<Row>("/broiler/supervisors/", { page_size: 500 }),
  });
  const farmsQuery = useQuery({
    queryKey: ["picker", "/broiler/farms/", "with-supervisor"],
    staleTime: 5 * 60 * 1000,
    queryFn: () => listResource<Row>("/broiler/farms/", { page_size: 200 }),
  });

  const branchField = useMemo(
    (): FormField => ({
      ...F_BRANCH,
      options: (branchesQuery.data?.items ?? []).map((b) => ({
        value: String(b.id),
        label: String(b.branch_name ?? b.code ?? `#${b.id}`),
      })),
    }),
    [branchesQuery.data]
  );

  /** Only this branch's supervisors. Before a branch is chosen the list stays
   *  empty, so the cascade cannot be entered halfway. */
  const supervisorField = useMemo((): FormField => {
    const all = supervisorsQuery.data?.items ?? [];
    const mine = branch ? all.filter((s) => String(s.branch ?? "") === String(branch)) : [];
    return {
      ...F_SUPERVISOR,
      options: mine.map((s) => ({ value: String(s.id), label: String(s.name ?? `#${s.id}`) })),
    };
  }, [supervisorsQuery.data, branch]);

  /** Only this supervisor's farms, matching the web's cascade. */
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

  /** The farm's open flocks, headed by the day each one would be recording. */
  const batchField = (r: GridRow): FormField => {
    const open = r.lookup?.batches ?? [];
    return {
      name: "batch",
      label: "Batch / Day",
      type: "select",
      required: true,
      options: open.map((b) => {
        const age = r.date ? ageOnDate(b.placed_on, r.date) : null;
        return { value: String(b.id), label: age == null ? b.name : `${b.name} (Day ${age})` };
      }),
    };
  };

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

  /**
   * Feed typed on earlier rows of the same farm and batch. The web grid counts
   * it so a row for age 7 is advised on top of the kilos just typed for age 6;
   * without it every row of a round is advised as if it were the flock's first.
   */
  const priorFor = useCallback(
    (row: GridRow): PriorFeed => {
      const above: FeedRow[] = [];
      for (const r of rowsRef.current) {
        if (r.key === row.key) break;
        if (r.values.farm === row.values.farm && r.values.batch === row.values.batch) {
          above.push(r.values as unknown as FeedRow);
        }
      }
      return priorListFeed(row.lookup, above);
    },
    []
  );

  const advice = useMemo(
    () =>
      new Map(
        rows.map((r) => [r.key, adviseDailyEntry(r.lookup, r.values, undefined, priorFor(r))] as const)
      ),
    [rows, priorFor]
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

  /**
   * The record's body. JSON normally; multipart the moment a photo was taken,
   * since a file cannot travel in JSON. The photo fields are dropped from the
   * text part — their value is a local file URI, and sending it as a string
   * would store the path instead of the picture.
   */
  const buildBody = async (
    r: GridRow,
    /** A fix taken during this save, which the row's own state does not carry yet. */
    fix?: CapturedPoint
  ): Promise<Record<string, unknown> | FormData> => {
    const values = fix
      ? { ...r.values, entry_latitude: fix.latitude, entry_longitude: fix.longitude }
      : r.values;
    const plain: Record<string, unknown> = { date: r.date, supervisor };
    for (const [k, v] of Object.entries(values)) {
      if (v !== "" && v != null) plain[k] = v;
    }
    const shots = PHOTO_FIELDS.filter((f) => isLocalCapture(values[f] ?? ""));
    if (!shots.length) return plain;

    const form = new FormData();
    for (const [k, v] of Object.entries(plain)) {
      if (!PHOTO_FIELDS.includes(k as (typeof PHOTO_FIELDS)[number])) form.append(k, String(v));
    }
    for (const f of shots) await appendImage(form, f, values[f]);
    return form;
  };

  const onSave = async () => {
    setFormError(null);
    if (!filled.length) {
      setFormError("Add at least one farm before saving.");
      return;
    }
    if (!branch || !supervisor) {
      setFormError("Branch and Supervisor are required.");
      return;
    }
    // Only where there is actually a choice on offer. A farm the server
    // reports no open batch for has nothing to pick, and refusing the save
    // over an empty picker would leave no way forward.
    const undecided = filled.filter(
      (r) => (r.lookup?.batches?.length ?? 0) > 0 && !r.values.batch
    );
    if (undecided.length) {
      setFormError("Choose a Batch for every farm.");
      return;
    }
    const undated = filled.filter((r) => !r.date);
    if (undated.length) {
      setFormError("Still working out the date for every farm — try again in a moment.");
      return;
    }

    // GPS is mandatory. Rows that never got a fix are given one more attempt
    // here rather than simply refused — the usual reason is that the capture
    // on farm-pick ran before the user granted permission or before the device
    // had a fix, and by now both are usually settled.
    setSaving(true);
    // Kept here rather than read back off the rows: `takeLocation` writes to
    // state, and state written inside this function has not re-rendered by the
    // time the POST is built — reading it back would post without coordinates.
    const fixes = new Map<string, CapturedPoint>();
    const stillMissing: GridRow[] = [];
    for (const r of filled) {
      if (hasFix(r)) continue;
      const point = await takeLocation(r.key);
      if (point) fixes.set(r.key, point);
      else stillMissing.push(r);
    }
    if (stillMissing.length) {
      setSaving(false);
      setFormError(
        `GPS location is mandatory. No location for ${stillMissing
          .map(farmLabel)
          .join(", ")} — turn location on, stand outside if you can, then use Retake Location.`
      );
      return;
    }

    const issues = filled.flatMap((r) => {
      const a = adviseDailyEntry(r.lookup, r.values, undefined, priorFor(r));
      return a.issues.map((i) => `${farmLabel(r)}: ${i}`);
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
      if (!proceed) {
        setSaving(false);
        return;
      }
    }

    // Keyed by row, not by label: two farms can share a batch name, and a row
    // whose lookup failed has no name at all — matching on text would drop the
    // wrong rows from the retry list.
    const failures = new Map<string, string>();
    let saved = 0;
    for (const r of filled) {
      try {
        await createResource(PATH, await buildBody(r, fixes.get(r.key)));
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

  const farmNameOf = (r: GridRow): string =>
    String(farmField.options?.find((o) => o.value === r.values.farm)?.label ?? "");

  return (
    <View style={styles.screen}>
      <KeyboardAwareScrollView
        style={styles.screen}
        contentContainerStyle={[styles.content, { paddingBottom: spacing.xxl * 3 }]}
      >
        {formError ? <Text style={styles.formError}>{formError}</Text> : null}

        <View style={styles.card}>
          <View style={styles.pairRow}>
            <View style={styles.pairCell}>
              <FormControl field={branchField} value={branch} onChange={onBranchChange} />
            </View>
            <View style={styles.pairCell}>
              <FormControl field={supervisorField} value={supervisor} onChange={onSupervisorChange} />
            </View>
          </View>
          <Text style={styles.headerNote}>
            Applied to every farm below. Each row is dated the day after that
            farm&apos;s last entry.
          </Text>
        </View>

        {rows.map((r, i) => {
          const a = advice.get(r.key);
          const flock = flockSummary(r.lookup, r.values);
          const feed = feedStandard(r.lookup, r.values);
          const birds = r.lookup?.live_birds ?? 0;
          return (
            <View key={r.key} style={styles.card}>
              <View style={styles.rowHead}>
                <Text style={styles.rowTitle}>
                  {farmNameOf(r) || `Farm ${i + 1}`}
                  {r.date ? `  ·  ${formatDate(r.date)}` : ""}
                </Text>
                <View style={styles.rowHeadRight}>
                  {/* The web grid's row pill — the one-word verdict on the row. */}
                  {a?.statusLabel && r.values.farm ? (
                    <Text style={[styles.statusPill, styles[`pill_${a.status}`]]}>
                      {a.statusLabel}
                    </Text>
                  ) : null}
                  <Pressable onPress={() => removeRow(r.key)} hitSlop={8}>
                    <Text style={styles.remove}>Remove</Text>
                  </Pressable>
                </View>
              </View>

              <View style={styles.pairRow}>
                <View style={styles.pairCell}>
                  <FormControl
                    field={farmField}
                    value={r.values.farm ?? ""}
                    onChange={setRowValue(r.key, "farm")}
                  />
                </View>
                <View style={styles.pairCell}>
                  <FormControl
                    field={batchField(r)}
                    value={r.values.batch ?? ""}
                    onChange={setRowValue(r.key, "batch")}
                  />
                </View>
              </View>

              {r.lookup?.batch ? (
                <FlockPanel row={r} farmName={farmNameOf(r)} />
              ) : null}

              {flock ? <MortalityPanel flock={flock} /> : null}

              <SectionHead n={1} title="Mortality, Culls & Weight" icon="scale-balance" />
              <View style={styles.pairRow}>
                <View style={styles.pairCell}>
                  <FormControl
                    field={F_MORTALITY}
                    value={r.values.mortality ?? ""}
                    onChange={setRowValue(r.key, "mortality")}
                  />
                </View>
                <View style={styles.pairCell}>
                  <FormControl
                    field={F_CULLS}
                    value={r.values.culls ?? ""}
                    onChange={setRowValue(r.key, "culls")}
                  />
                </View>
              </View>
              <FormControl
                field={F_AVG_WT}
                value={r.values.avg_weight_gms ?? ""}
                onChange={setRowValue(r.key, "avg_weight_gms")}
              />
              {a?.fieldHints.avg_weight_gms ? (
                <HintLine hint={a.fieldHints.avg_weight_gms} />
              ) : null}
              <View style={styles.pairRow}>
                <View style={styles.pairCell}>
                  <FormControl
                    field={F_MORT_PHOTO}
                    value={r.values.mort_image ?? ""}
                    onChange={setRowValue(r.key, "mort_image")}
                  />
                </View>
                <View style={styles.pairCell}>
                  <FormControl
                    field={F_CULL_PHOTO}
                    value={r.values.cull_image ?? ""}
                    onChange={setRowValue(r.key, "cull_image")}
                  />
                </View>
              </View>

              <SectionHead n={2} title="Feed Consumption" icon="sack" />
              <Text style={styles.slotHead}>Primary Feed</Text>
              <FormControl
                field={F_FEED_1}
                value={r.values.feed_1 ?? ""}
                values={r.values}
                onChange={setRowValue(r.key, "feed_1")}
              />
              {a?.fieldHints.feed_1 ? <HintLine hint={a.fieldHints.feed_1} /> : null}
              <View style={styles.pairRow}>
                <View style={styles.pairCell}>
                  <StockCell label="Stock-1 (kg)" value={balanceFor(r, "feed_1")} />
                </View>
                <View style={styles.pairCell}>
                  <FormControl
                    field={F_FEED_1_QTY}
                    value={r.values.feed_1_qty ?? ""}
                    onChange={setRowValue(r.key, "feed_1_qty")}
                  />
                </View>
                <View style={styles.pairCell}>
                  <FormControl
                    field={F_FEED_PHOTO}
                    value={r.values.feed_image ?? ""}
                    onChange={setRowValue(r.key, "feed_image")}
                  />
                </View>
              </View>
              <PerBirdLine qty={num(r.values.feed_1_qty)} birds={birds} />
              {a?.fieldHints.feed_1_qty ? <HintLine hint={a.fieldHints.feed_1_qty} /> : null}

              <Text style={styles.slotHead}>Optional Feed</Text>
              <FormControl
                field={F_FEED_2}
                value={r.values.feed_2 ?? ""}
                values={r.values}
                onChange={setRowValue(r.key, "feed_2")}
              />
              {a?.fieldHints.feed_2 ? <HintLine hint={a.fieldHints.feed_2} /> : null}
              <View style={styles.pairRow}>
                <View style={styles.pairCell}>
                  <StockCell label="Stock-2 (kg)" value={balanceFor(r, "feed_2")} />
                </View>
                <View style={styles.pairCell}>
                  <FormControl
                    field={F_FEED_2_QTY}
                    value={r.values.feed_2_qty ?? ""}
                    onChange={setRowValue(r.key, "feed_2_qty")}
                  />
                </View>
              </View>
              <PerBirdLine qty={num(r.values.feed_2_qty)} birds={birds} />

              {feed ? <FeedBar feed={feed} /> : null}

              {a?.issues.length ? (
                <ValidationSummary issues={a.issues} notes={a.notes} label={farmLabel(r)} />
              ) : null}

              <SectionHead n={3} title="Location (GPS)" icon="map-marker-outline" required />
              <LocationPanel row={r} onRetake={() => takeLocation(r.key)} />

              <SectionHead n={4} title="Remarks" icon="message-text-outline" />
              <FormControl
                field={F_REMARKS}
                value={r.values.remarks ?? ""}
                onChange={setRowValue(r.key, "remarks")}
              />

              {a ? <FeedCheck advice={a} /> : null}
            </View>
          );
        })}

        <Button title="Add another farm" variant="ghost" onPress={addRow} />
      </KeyboardAwareScrollView>

      {/* Sticky footer: the round's running totals, and the two ways out. */}
      <View style={[styles.footer, { paddingBottom: spacing.md + insets.bottom }]}>
        <Text style={styles.footerSummary} numberOfLines={1}>
          <Text style={styles.footerStrong}>{summary.rows}</Text>
          {summary.rows === 1 ? " farm" : " farms"}
          {"  ·  Feed "}
          <Text style={styles.footerStrong}>{summary.feed.toFixed(1)} kg</Text>
          {"  ·  Mort "}
          <Text style={styles.footerStrong}>{summary.mortality}</Text>
          {"  ·  Culls "}
          <Text style={styles.footerStrong}>{summary.culls}</Text>
          {summary.latestWeight ? `  ·  Wt ${summary.latestWeight} g` : ""}
        </Text>
        <View style={styles.footerActions}>
          <View style={styles.footerCancel}>
            <Button title="Cancel" variant="ghost" onPress={() => navigation.goBack()} />
          </View>
          <View style={styles.footerSubmit}>
            <Button
              title={saving ? "Submitting…" : "Submit Day Record"}
              onPress={onSave}
              loading={saving}
            />
          </View>
        </View>
      </View>
    </View>
  );
}

const farmLabel = (r: GridRow): string => r.lookup?.batch_name || `Farm ${r.values.farm}`;

/** Who this flock is — the facts the supervisor checks before typing anything. */
function FlockPanel({ row, farmName }: { row: GridRow; farmName: string }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const l = row.lookup!;
  return (
    <View style={styles.panel}>
      <View style={styles.panelHead}>
        <AppIcon name="home-outline" size={18} color={colors.broiler} />
        <Text style={styles.panelTitle}>{farmName || l.batch_name}</Text>
      </View>
      <View style={styles.factGrid}>
        <Fact icon="home-outline" label="Batch" value={l.batch_name} />
        <Fact icon="account-group-outline" label="Opening Birds" value={fmtInt(l.opening_birds)} />
        <Fact icon="warehouse" label="Shed No." value={l.shed_name || "—"} />
        <Fact icon="calendar-clock" label="Age" value={`Day ${l.age_days}`} />
        <Fact icon="dna" label="Breed" value={l.breed_name || "—"} />
        <Fact icon="chart-line" label="Phase" value={l.feed_phase?.phase_name || "—"} />
        <Fact icon="bird" label="Bird Type" value={l.bird_type || "—"} />
        <Fact
          icon="calendar-outline"
          label="Placement"
          value={l.start_date ? formatDate(l.start_date) : "—"}
        />
      </View>
    </View>
  );
}

/** Where the flock's losses stand once this entry is applied. */
function MortalityPanel({
  flock,
}: {
  flock: NonNullable<ReturnType<typeof flockSummary>>;
}) {
  const styles = useStyles();
  const { colors } = useTheme();
  return (
    <View style={styles.panel}>
      <View style={styles.panelHead}>
        <AppIcon name="heart-pulse" size={18} color={colors.danger} />
        <Text style={[styles.panelTitle, { color: colors.danger }]}>Mortality Summary</Text>
      </View>
      <View style={styles.statRow}>
        <Stat
          label="Total Mortality"
          value={`${fmtInt(flock.mortality)} birds`}
          pct={flock.mortalityPct}
          tone="bad"
        />
        <Stat
          label="Total Culls"
          value={`${fmtInt(flock.culls)} birds`}
          pct={flock.cullsPct}
          tone="info"
        />
        <Stat
          label="Live Birds"
          value={`${fmtInt(flock.live)} birds`}
          pct={flock.livePct}
          tone="ok"
        />
      </View>
    </View>
  );
}

function Stat({
  label,
  value,
  pct,
  tone,
}: {
  label: string;
  value: string;
  pct: number;
  tone: Tone;
}) {
  const styles = useStyles();
  return (
    <View style={styles.stat}>
      <Text style={styles.statLabel}>{label}</Text>
      <Text style={styles.statValue}>{value}</Text>
      <Text style={[styles.statPill, styles[`pill_${tone}`]]}>
        {pct.toFixed(2)}% of Opening Birds
      </Text>
    </View>
  );
}

function Fact({ icon, label, value }: { icon: IconName; label: string; value: string }) {
  const styles = useStyles();
  const { colors } = useTheme();
  return (
    <View style={styles.fact}>
      <AppIcon name={icon} size={14} color={colors.textMuted} />
      <Text style={styles.factLabel} numberOfLines={1}>
        {label} :
      </Text>
      <Text style={styles.factValue} numberOfLines={1}>
        {value}
      </Text>
    </View>
  );
}

function SectionHead({
  n,
  title,
  icon,
  required,
}: {
  n: number;
  title: string;
  icon: IconName;
  required?: boolean;
}) {
  const styles = useStyles();
  const { colors } = useTheme();
  return (
    <View style={styles.sectionHead}>
      <Text style={styles.sectionNum}>{n}</Text>
      <Text style={styles.sectionTitle}>
        {title.toUpperCase()}
        {required ? <Text style={{ color: colors.danger }}> *</Text> : null}
      </Text>
      <AppIcon name={icon} size={16} color={colors.textMuted} />
    </View>
  );
}

/** Feed store left on the farm after this row — the web grid's Stock column.
 *  Read-only: it is derived from the opening balance and the kgs entered. */
function StockCell({ label, value }: { label: string; value: number | null }) {
  const styles = useStyles();
  const short = value != null && value < 0;
  return (
    <View style={styles.stockCell}>
      <Text style={styles.stockLabel}>{label}</Text>
      <View style={[styles.stockBox, short ? styles.stockBoxShort : null]}>
        <Text style={[styles.stockValue, short ? styles.stockValueShort : null]}>
          {value == null ? "Auto" : value.toFixed(1)}
        </Text>
      </View>
    </View>
  );
}

/** Grams per live bird for one feed slot. */
function PerBirdLine({ qty, birds }: { qty: number; birds: number }) {
  const styles = useStyles();
  const g = feedPerBirdG(qty, birds);
  if (g == null) return null;
  return <Text style={styles.perBird}>Feed / Bird: {g.toFixed(1)} g</Text>;
}

/** The day's feed against the breed standard, as a bar. */
function FeedBar({ feed }: { feed: NonNullable<ReturnType<typeof feedStandard>> }) {
  const styles = useStyles();
  const tone = feedTone(feed.pct);
  return (
    <View style={styles.bar}>
      <Text style={styles.barLabel}>
        {feed.totalKg.toFixed(1)} / {feed.stdKg.toFixed(1)} kg
      </Text>
      <View style={styles.barTrack}>
        <View
          style={[
            styles.barFill,
            styles[`fill_${tone}`],
            // Past the standard the bar is full and the percentage carries the
            // overshoot — a bar drawn past its own track reads as a glitch.
            { width: `${Math.min(Math.max(feed.pct, 0), 100)}%` },
          ]}
        />
      </View>
      <Text style={[styles.barPct, styles[`hint_${tone}`]]}>{feed.pct.toFixed(0)}%</Text>
    </View>
  );
}

/** Everything the advisories flagged on this row, collected in one block so it
 *  is read once rather than hunted for field by field. */
function ValidationSummary({
  issues,
  notes,
  label,
}: {
  issues: string[];
  notes: Hint[];
  label: string;
}) {
  const styles = useStyles();
  const { colors } = useTheme();
  const details = () =>
    Alert.alert(
      label,
      [...issues.map((i) => `• ${i}`), "", ...notes.map((n) => n.text)].join("\n").trim()
    );
  return (
    <View style={styles.validation}>
      <View style={styles.validationHead}>
        <AppIcon name="alert-outline" size={16} color={colors.danger} />
        <Text style={styles.validationTitle}>VALIDATION SUMMARY</Text>
      </View>
      {issues.map((i, k) => (
        <Text key={k} style={styles.validationLine}>
          • {i}
        </Text>
      ))}
      <Pressable onPress={details} hitSlop={8}>
        <Text style={styles.validationLink}>View Details</Text>
      </Pressable>
    </View>
  );
}

/**
 * The row's GPS stamp. Mandatory — the card says so whenever the fix is
 * missing, and `onSave` refuses the round rather than posting a record that
 * cannot be placed.
 */
function LocationPanel({ row, onRetake }: { row: GridRow; onRetake: () => void }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const has = hasFix(row);
  return (
    <>
      <View style={styles.geo}>
        <AppIcon
          name={has ? "map-marker-check" : "map-marker-alert-outline"}
          size={22}
          color={has ? colors.success : colors.danger}
        />
        <View style={styles.geoText}>
          <Text style={styles.geoTitle}>
            {row.locating ? "Getting location…" : has ? "Location Captured" : "No location yet"}
          </Text>
          {has ? (
            <Text style={styles.geoCoords}>
              {Number(row.values.entry_latitude).toFixed(4)}° N,{" "}
              {Number(row.values.entry_longitude).toFixed(4)}° E
            </Text>
          ) : null}
          {row.locatedAt ? (
            <Text style={styles.geoTime}>
              {/* The device's own clock, not UTC: a fix taken at 09:41 must not
                  read as the previous day east of Greenwich. */}
              {row.locatedAt.toLocaleDateString(undefined, {
                day: "2-digit",
                month: "short",
                year: "numeric",
              })}{" "}
              {row.locatedAt.toLocaleTimeString(undefined, {
                hour: "2-digit",
                minute: "2-digit",
              })}
            </Text>
          ) : null}
        </View>
        <Pressable onPress={onRetake} disabled={row.locating} hitSlop={8}>
          <View style={styles.geoBtn}>
            <AppIcon name="crosshairs-gps" size={16} color={colors.tint} />
            <Text style={styles.geoBtnText}>{has ? "Retake" : "Get Location"}</Text>
          </View>
        </Pressable>
      </View>
      {!has ? (
        <Text style={styles.geoWarn}>
          {row.locateFailed
            ? "Couldn't get a location — check that location permission and GPS are on. The record cannot be saved without one."
            : "GPS location is mandatory. Record cannot be saved without valid location."}
        </Text>
      ) : null}
    </>
  );
}

/**
 * The web grid's notification strip, in full: every advisory line the office
 * sees under a row, plus the cumulative-feed-vs-cap gauge. It is the whole
 * reason a supervisor can tell an over-feed from a heavy flock, so the phone
 * carries it rather than a summary of it.
 */
function FeedCheck({ advice }: { advice: Advice }) {
  const styles = useStyles();
  if (!advice.notes.length && !advice.cap) return null;
  return (
    <View style={styles.notes}>
      <Text style={styles.notesHead}>FEED CHECK</Text>
      {advice.notes.map((n, k) => (
        <HintLine key={k} hint={n} inline />
      ))}
      {advice.cap ? <CapGauge cap={advice.cap} /> : null}
    </View>
  );
}

/** How far a capped feed is through its kg/bird allowance — the changeover. */
function CapGauge({ cap }: { cap: CapProgress }) {
  const styles = useStyles();
  return (
    <View style={styles.capRow}>
      <Text style={styles.capLabel}>
        {cap.name} — cumulative feed vs cap
        {cap.note ? <Text style={styles[`hint_${cap.tone}`]}> · {cap.note}</Text> : null}
      </Text>
      <View style={styles.barTrack}>
        <View
          style={[
            styles.barFill,
            styles[`fill_${cap.tone}`],
            { width: `${Math.min(Math.max(cap.pct, 0), 100)}%` },
          ]}
        />
      </View>
      <Text style={styles.capSub}>
        {cap.cum.toFixed(3)} / {cap.cap.toFixed(3)} kg/bird cum. ({cap.pct.toFixed(0)}%)
      </Text>
    </View>
  );
}

function HintLine({ hint, inline }: { hint: Hint; inline?: boolean }) {
  const styles = useStyles();
  return (
    <Text style={[inline ? styles.noteLine : styles.hint, styles[`hint_${hint.tone}`]]}>
      {hint.text}
    </Text>
  );
}

/** Thousands-separated whole number, or an em dash when unknown. */
const fmtInt = (n?: number): string => (n == null ? "—" : n.toLocaleString());

const useStyles = makeStyles((colors) => ({
  screen: { flex: 1, backgroundColor: colors.bg },
  content: { padding: spacing.md, gap: spacing.md },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.md,
    ...shadow(1),
  },
  headerBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.xs,
    borderWidth: 1,
    borderColor: colors.onDark,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: 4,
  },
  headerBtnText: { ...type.caption, color: colors.onDark },
  headerNote: { ...type.caption, color: colors.textMuted },

  pairRow: { flexDirection: "row", gap: spacing.md },
  pairCell: { flex: 1 },

  rowHead: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: spacing.sm,
  },
  rowTitle: { ...type.h3, color: colors.text, flexShrink: 1 },
  remove: { ...type.label, color: colors.danger },

  panel: {
    backgroundColor: colors.surfaceAlt,
    borderRadius: radius.md,
    padding: spacing.md,
    marginBottom: spacing.md,
    gap: spacing.sm,
  },
  panelHead: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  panelTitle: { ...type.title, color: colors.broiler },
  factGrid: { flexDirection: "row", flexWrap: "wrap", rowGap: spacing.xs },
  fact: { flexDirection: "row", alignItems: "center", gap: spacing.xs, width: "50%", paddingRight: spacing.sm },
  factLabel: { ...type.caption, color: colors.textMuted, flexShrink: 1 },
  factValue: { ...type.caption, color: colors.text, fontWeight: "700", flexShrink: 1 },

  statRow: { flexDirection: "row", gap: spacing.sm },
  stat: { flex: 1, gap: 2 },
  statLabel: { ...type.caption, color: colors.textMuted },
  statValue: { ...type.h3, color: colors.text },
  statPill: {
    ...type.caption,
    fontSize: 10,
    overflow: "hidden",
    borderRadius: radius.pill,
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    alignSelf: "flex-start",
  },
  pill_ok: { backgroundColor: colors.successLight, color: colors.success },
  pill_bad: { backgroundColor: colors.dangerLight, color: colors.danger },
  pill_warn: { backgroundColor: colors.warningLight, color: colors.warning },
  pill_info: { backgroundColor: colors.infoLight, color: colors.info },

  sectionHead: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    marginBottom: spacing.sm,
  },
  sectionNum: {
    ...type.caption,
    color: colors.onDark,
    backgroundColor: colors.primary,
    width: 20,
    height: 20,
    borderRadius: radius.sm,
    textAlign: "center",
    lineHeight: 20,
    overflow: "hidden",
  },
  sectionTitle: { ...type.label, color: colors.text, letterSpacing: 0.5, flex: 1 },
  slotHead: { ...type.caption, color: colors.broiler, marginBottom: spacing.xs },

  stockCell: { marginBottom: spacing.lg },
  stockLabel: { ...type.label, color: colors.text, marginBottom: spacing.xs },
  stockBox: {
    minHeight: 50,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceAlt,
    paddingHorizontal: spacing.md,
    justifyContent: "center",
  },
  stockBoxShort: { borderColor: colors.danger, backgroundColor: colors.dangerLight },
  stockValue: { ...type.body, color: colors.textMuted },
  stockValueShort: { color: colors.danger, fontWeight: "700" },
  perBird: { ...type.caption, color: colors.textMuted, marginTop: -spacing.sm, marginBottom: spacing.md },

  bar: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginBottom: spacing.md },
  barLabel: { ...type.caption, color: colors.textMuted },
  barTrack: {
    flex: 1,
    height: 8,
    borderRadius: radius.pill,
    backgroundColor: colors.surfaceAlt,
    overflow: "hidden",
  },
  barFill: { height: 8, borderRadius: radius.pill },
  fill_ok: { backgroundColor: colors.success },
  fill_warn: { backgroundColor: colors.warning },
  fill_bad: { backgroundColor: colors.danger },
  fill_info: { backgroundColor: colors.textFaint },
  barPct: { ...type.caption, minWidth: 42, textAlign: "right" },

  validation: {
    backgroundColor: colors.dangerLight,
    borderRadius: radius.md,
    padding: spacing.md,
    marginBottom: spacing.md,
    gap: spacing.xs,
  },
  validationHead: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  validationTitle: { ...type.label, color: colors.danger, letterSpacing: 0.5 },
  validationLine: { ...type.caption, color: colors.danger },
  validationLink: { ...type.label, color: colors.danger, textDecorationLine: "underline" },

  geo: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: colors.surfaceAlt,
    borderRadius: radius.md,
    padding: spacing.md,
  },
  geoText: { flex: 1 },
  geoTitle: { ...type.label, color: colors.text },
  geoCoords: { ...type.caption, color: colors.textMuted },
  geoTime: { ...type.caption, color: colors.success },
  geoBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.xs,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.sm,
    backgroundColor: colors.surface,
  },
  geoBtnText: { ...type.caption, color: colors.tint },
  geoWarn: { ...type.caption, color: colors.danger, marginTop: spacing.xs, marginBottom: spacing.md },

  hint: { ...type.label, marginTop: -spacing.md, marginBottom: spacing.md },
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
  notesHead: { ...type.caption, color: colors.textMuted, letterSpacing: 0.5 },
  noteLine: { ...type.caption, lineHeight: 17 },
  capRow: { marginTop: spacing.xs, gap: spacing.xs },
  capLabel: { ...type.caption, color: colors.textMuted },
  capSub: { ...type.caption, color: colors.textMuted },
  statusPill: {
    ...type.caption,
    fontSize: 10,
    overflow: "hidden",
    borderRadius: radius.pill,
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
  },
  pill_near: { backgroundColor: colors.warningLight, color: colors.warning },
  rowHeadRight: { flexDirection: "row", alignItems: "center", gap: spacing.sm },

  footer: {
    borderTopWidth: 1,
    borderTopColor: colors.border,
    backgroundColor: colors.surface,
    paddingHorizontal: spacing.md,
    paddingTop: spacing.sm,
    gap: spacing.sm,
  },
  footerSummary: { ...type.caption, color: colors.textMuted },
  footerStrong: { color: colors.text, fontWeight: "700" },
  footerActions: { flexDirection: "row", gap: spacing.md, alignItems: "center" },
  footerCancel: { flex: 1 },
  footerSubmit: { flex: 2 },

  formError: {
    ...type.label,
    color: colors.danger,
    backgroundColor: colors.dangerLight,
    padding: spacing.md,
    borderRadius: radius.md,
  },
}));
