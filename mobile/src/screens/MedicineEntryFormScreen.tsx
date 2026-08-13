import { NativeStackScreenProps } from "@react-navigation/native-stack";
import React, { useLayoutEffect, useRef, useState } from "react";
import { Alert, Pressable, ScrollView, Text, View } from "react-native";

import { http } from "@/api/client";
import { Envelope } from "@/api/types";
import { FormControl } from "@/components/form";
import { FormField } from "@/config/forms";
import { ageAt } from "@/domain/flockAge";
import { ModuleStackParams } from "@/navigation/types";
import { queryClient } from "@/query/queryClient";
import { makeStyles, radius, spacing, type, useTheme } from "@/theme";

type Props = NativeStackScreenProps<ModuleStackParams, "MedicineEntryForm">;

/**
 * Medicine/Vaccine Consumption — the document form.
 *
 * One supervisor, one farm, one batch and one date over several consumption
 * lines, which is how the ERP form works and what its API accepts. The generic
 * FormScreen can express one record of flat fields; this needs a header that
 * governs many lines and a line you can add to, so it is its own screen.
 *
 * Every input is still a `FormControl`, so pickers, dates and validation
 * behave exactly as they do on every other form — only the layout is bespoke.
 */

const SUPERVISOR: FormField = {
  name: "supervisor", label: "Supervisor", type: "select", required: true,
  optionsPath: "/broiler/supervisors/", optionLabelKeys: ["name"],
};
/**
 * Farm and Batch cascade, the way the ERP form does: a supervisor's farms,
 * then that farm's open batches. Both take supplied `options` rather than a
 * list endpoint, because neither list is "all of them" — picking a supervisor
 * narrows Farm to the farms mapped to them, and picking a farm narrows Batch
 * to the flocks currently on it.
 */
const farmField = (options: Option[], ready: boolean): FormField => ({
  name: "farm", label: "Farm", type: "select", required: true, options,
  placeholder: ready ? undefined : "Select a supervisor first",
});
const batchField = (options: Option[], ready: boolean): FormField => ({
  name: "batch", label: "Batch", type: "select", required: true, options,
  placeholder: ready ? undefined : "Select a farm first",
});
const AGE: FormField = { name: "age_days", label: "Age (Days)", type: "number", readOnly: true };
const DATE: FormField = { name: "date", label: "Date", type: "date", required: true };
const ITEM: FormField = {
  name: "item", label: "Medicine / Vaccine", type: "select", required: true,
  optionsPath: "/items/", optionLabelKeys: ["description", "item_code"],
};
const UNIT: FormField = { name: "unit", label: "Unit", type: "text", readOnly: true };
const QTY: FormField = { name: "qty", label: "Quantity", type: "decimal", required: true };
const STOCK: FormField = { name: "stock", label: "Available Stock", type: "text", readOnly: true };
const REMARKS: FormField = { name: "remarks", label: "Remarks (Optional)", type: "text" };

const REMARKS_MAX = 200;

interface Option { value: string; label: string }

interface Line {
  item: string;
  unit: string;
  qty: string;
  stock: string;
}

const emptyLine = (): Line => ({ item: "", unit: "", qty: "", stock: "" });

const today = () => new Date().toISOString().slice(0, 10);

interface Farm { id: number; farm_name: string; farm_code: string }

interface FarmLookup {
  batch: number | null;
  batches: { id: number; name: string }[];
  start_date: string | null;
  next_date: string;
}

export function MedicineEntryFormScreen({ navigation }: Props) {
  const styles = useStyles();
  const { colors } = useTheme();

  const [head, setHead] = useState<Record<string, string>>({
    supervisor: "", farm: "", batch: "", age_days: "", date: today(),
  });
  /** The batch's resolved placement date — what age is measured from. */
  const [placedOn, setPlacedOn] = useState("");
  const [farmOptions, setFarmOptions] = useState<Option[]>([]);
  const [batchOptions, setBatchOptions] = useState<Option[]>([]);
  const [lines, setLines] = useState<Line[]>([emptyLine()]);
  const [remarks, setRemarks] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** Discards a stock recompute that a newer one has overtaken. */
  const stockToken = useRef(0);

  useLayoutEffect(() => {
    navigation.setOptions({ title: "Add Medicine/Vaccine Record" });
  }, [navigation]);

  /** The farms mapped to a supervisor — the Farm picker's whole list. */
  const loadFarms = async (supervisorId: string) => {
    try {
      const { data } = await http.get<Envelope<Farm[]>>(
        "/broiler/farms/", { params: { supervisor: supervisorId, page_size: 200 } });
      setFarmOptions(data.data.map((f) => ({
        value: String(f.id), label: f.farm_name || f.farm_code || `#${f.id}`,
      })));
    } catch {
      setFarmOptions([]);
    }
  };

  /** The farm's open batches, its active one, and that batch's placement. */
  const loadBatch = async (farmId: string, batchId?: string) => {
    try {
      const { data } = await http.get<Envelope<FarmLookup>>(
        "/broiler/farm-lookup",
        { params: batchId ? { farm: farmId, batch: batchId } : { farm: farmId } });
      const d = data.data;
      const options = (d.batches ?? []).map((b) => ({ value: String(b.id), label: b.name }));
      if (!batchId) setBatchOptions(options);
      const placed = d.batch ? d.start_date || "" : "";
      setPlacedOn(placed);
      setHead((cur) => {
        const batch = batchId ?? (d.batch != null ? String(d.batch) : "");
        return { ...cur, batch, age_days: ageAt(placed, cur.date) };
      });
    } catch {
      // A failed lookup leaves Batch and Age for the user to set by hand.
    }
  };

  const onHead = (name: string) => async (value: string) => {
    if (name === "date") {
      // The web form refuses a future entry date and snaps back; so do we.
      if (value && value > today()) {
        setError("Entry date cannot be later than today.");
        return;
      }
      setError(null);
    }
    const next = { ...head, [name]: value };
    // Age follows the date and the batch, so both recompute it locally —
    // no round trip, exactly as the web form does it.
    if (name === "date" || name === "batch") next.age_days = ageAt(placedOn, next.date);
    if (name === "supervisor" || name === "farm") {
      // Each step of the cascade clears the ones below it, so a stale farm
      // from the previous supervisor can never survive into the saved record.
      next.batch = "";
      next.age_days = "";
      setBatchOptions([]);
      setPlacedOn("");
    }
    if (name === "supervisor") {
      next.farm = "";
      setFarmOptions([]);
    }
    setHead(next);

    if (name === "supervisor" && value) await loadFarms(value);
    if (name === "farm" && value) await loadBatch(value);
    if (name === "batch" && value && next.farm) await loadBatch(next.farm, value);
    // Stock is read as of the dose's own date, at the dose's own farm.
    if (name === "farm" || name === "date") recomputeStock(next, lines);
  };

  const onLine = (index: number, key: keyof Line) => async (value: string) => {
    const next = lines.map((l, i) => (i === index ? { ...l, [key]: value } : l));
    setLines(next);
    if (key === "item" && value) {
      try {
        const u = await http.get<Envelope<{ unit: string }>>(
          "/broiler/medicine-item-lookup", { params: { item: value } });
        setLines((cur) => cur.map((l, i) => (i === index ? { ...l, unit: u.data.data.unit } : l)));
      } catch {
        /* unit is advisory */
      }
    }
    if (key === "item" || key === "qty") recomputeStock(head, next);
  };

  /**
   * Available Stock, line by line — the web form's running preview.
   *
   * It is the *closing* balance, not the opening one: opening minus this
   * line's quantity, and lines consuming the same item chain, so a second dose
   * of the same medicine shows what the first one left rather than repeating
   * the opening figure. That is the number the server will store.
   */
  const recomputeStock = async (h: Record<string, string>, rows: Line[]) => {
    const mine = ++stockToken.current;
    const opening: Record<string, number> = {};
    const running: Record<string, number> = {};
    const stocks: string[] = [];
    for (const line of rows) {
      if (!h.farm || !line.item) { stocks.push(""); continue; }
      const key = `${h.farm}:${line.item}`;
      if (!(key in running)) {
        if (!(key in opening)) {
          try {
            const s = await http.get<Envelope<{ stock: string }>>(
              "/broiler/medicine-stock-lookup",
              { params: { farm: h.farm, item: line.item, date: h.date } });
            if (mine !== stockToken.current) return;   // a newer recompute won
            opening[key] = Number(s.data.data.stock) || 0;
          } catch {
            opening[key] = 0;   // balance is advisory until save
          }
        }
        running[key] = opening[key];
      }
      running[key] -= Number(line.qty) || 0;
      stocks.push(running[key].toFixed(2));
    }
    if (mine !== stockToken.current) return;
    setLines((cur) => cur.map((l, i) => (i < stocks.length ? { ...l, stock: stocks[i] } : l)));
  };

  const submit = async () => {
    setError(null);
    if (!head.supervisor) return setError("Supervisor is required.");
    if (!head.farm) return setError("Farm is required.");
    if (!head.date) return setError("Date is required.");
    const filled = lines.filter((l) => l.item && l.qty);
    if (!filled.length) return setError("Add at least one line with an item and a quantity.");

    setSaving(true);
    try {
      await http.post("/broiler/medicine-entries/save", {
        supervisor: head.supervisor,
        date: head.date,
        // The header governs every line; only the item and quantity differ.
        rows: filled.map((l) => ({
          farm: head.farm,
          batch: head.batch || null,
          age_days: head.age_days || null,
          item: l.item,
          qty: l.qty,
          remarks,
        })),
      });
      queryClient.invalidateQueries({ queryKey: ["list", "/broiler/medicine-vaccine-entries/"] });
      navigation.goBack();
    } catch (e: unknown) {
      const message = (e as { message?: string })?.message;
      setError(message ?? "Could not save.");
      Alert.alert("Could not save", message ?? "Please check the entries and try again.");
    } finally {
      setSaving(false);
    }
  };

  const SectionHead = ({ n, title }: { n: number; title: string }) => (
    <View style={styles.sectionHead}>
      <View style={styles.badge}><Text style={styles.badgeText}>{n}</Text></View>
      <Text style={styles.sectionTitle}>{title}</Text>
    </View>
  );

  return (
    <View style={styles.screen}>
      <ScrollView contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
        {error ? <Text style={styles.error}>{error}</Text> : null}

        <View style={styles.card}>
          <FormControl field={SUPERVISOR} value={head.supervisor} values={head}
                       onChange={onHead("supervisor")} />
        </View>

        <Text style={styles.recordsLabel}>MEDICINE/VACCINE RECORDS</Text>

        <View style={styles.card}>
          <SectionHead n={1} title="LOCATION & BATCH" />
          <View style={styles.row}>
            <View style={styles.cell}>
              <FormControl field={farmField(farmOptions, !!head.supervisor)}
                           value={head.farm} values={head} onChange={onHead("farm")} />
            </View>
            <View style={styles.cell}>
              <FormControl field={batchField(batchOptions, !!head.farm)}
                           value={head.batch} values={head} onChange={onHead("batch")} />
            </View>
          </View>
          <View style={styles.row}>
            <View style={styles.cell}>
              <FormControl field={AGE} value={head.age_days} values={head} onChange={onHead("age_days")} />
            </View>
            <View style={styles.cell}>
              <FormControl field={DATE} value={head.date} values={head} onChange={onHead("date")} />
            </View>
          </View>
        </View>

        <View style={styles.card}>
          <SectionHead n={2} title="ITEM & CONSUMPTION" />
          {lines.map((line, i) => (
            <View key={i} style={i > 0 ? styles.lineDivider : undefined}>
              {lines.length > 1 ? (
                <View style={styles.lineHead}>
                  <Text style={styles.lineNo}>Line {i + 1}</Text>
                  <Pressable onPress={() => {
                    // Removing a line re-chains the ones after it: they were
                    // showing a balance that counted the dose just deleted.
                    const rest = lines.filter((_, j) => j !== i);
                    setLines(rest);
                    recomputeStock(head, rest);
                  }}>
                    <Text style={[styles.remove, { color: colors.danger }]}>Remove</Text>
                  </Pressable>
                </View>
              ) : null}
              <FormControl field={ITEM} value={line.item} onChange={onLine(i, "item")} />
              <View style={styles.row}>
                <View style={styles.cell}>
                  <FormControl field={UNIT} value={line.unit} onChange={onLine(i, "unit")} />
                </View>
                <View style={styles.cell}>
                  <FormControl field={QTY} value={line.qty} onChange={onLine(i, "qty")} />
                </View>
                <View style={styles.cell}>
                  <FormControl field={STOCK} value={line.stock} onChange={onLine(i, "stock")} />
                </View>
              </View>
            </View>
          ))}
        </View>

        <Pressable style={styles.addRow} onPress={() => setLines((cur) => [...cur, emptyLine()])}>
          <Text style={[styles.addRowText, { color: colors.tint }]}>+  Add Another Row</Text>
        </Pressable>

        <View style={styles.card}>
          <SectionHead n={3} title="REMARKS" />
          <FormControl field={REMARKS} value={remarks}
                       onChange={(v) => setRemarks(v.slice(0, REMARKS_MAX))} />
          <Text style={styles.counter}>{remarks.length}/{REMARKS_MAX}</Text>
        </View>

      </ScrollView>

      <View style={styles.footer}>
        <Pressable style={styles.cancel} onPress={() => navigation.goBack()}>
          <Text style={styles.cancelText}>Cancel</Text>
        </Pressable>
        <Pressable style={[styles.submit, { backgroundColor: colors.tint }, saving && { opacity: 0.6 }]}
                   onPress={submit} disabled={saving}>
          <Text style={styles.submitText}>{saving ? "Saving…" : "Submit"}</Text>
        </Pressable>
      </View>
    </View>
  );
}

const useStyles = makeStyles((colors) => ({
  screen: { flex: 1, backgroundColor: colors.bg },
  body: { padding: spacing.md, paddingBottom: spacing.xl, gap: spacing.md },
  card: {
    backgroundColor: colors.surface, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border, padding: spacing.md,
  },
  recordsLabel: { ...type.label, color: colors.textMuted, letterSpacing: 0.6 },
  sectionHead: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginBottom: spacing.sm },
  badge: {
    width: 24, height: 24, borderRadius: 6, backgroundColor: colors.tint,
    alignItems: "center", justifyContent: "center",
  },
  badgeText: { color: colors.onDark, fontWeight: "800", fontSize: 12 },
  sectionTitle: { ...type.label, color: colors.tint, letterSpacing: 0.6 },
  row: { flexDirection: "row", gap: spacing.sm, alignItems: "flex-start" },
  cell: { flex: 1, minWidth: 0 },
  lineDivider: { borderTopWidth: 1, borderTopColor: colors.border, paddingTop: spacing.sm, marginTop: spacing.sm },
  lineHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  lineNo: { ...type.caption, color: colors.textMuted },
  remove: { ...type.caption, fontWeight: "700" },
  counter: { ...type.caption, color: colors.textMuted, textAlign: "right" },
  addRow: {
    borderWidth: 1, borderStyle: "dashed", borderColor: colors.tint,
    borderRadius: radius.md, paddingVertical: spacing.md, alignItems: "center",
  },
  addRowText: { ...type.title },
  error: { ...type.caption, color: colors.danger },
  footer: {
    flexDirection: "row", gap: spacing.sm, padding: spacing.md,
    borderTopWidth: 1, borderTopColor: colors.border, backgroundColor: colors.surface,
  },
  cancel: {
    flex: 1, height: 48, borderRadius: radius.md, borderWidth: 1,
    borderColor: colors.border, alignItems: "center", justifyContent: "center",
  },
  cancelText: { ...type.title, color: colors.text },
  submit: { flex: 2, height: 48, borderRadius: radius.md, alignItems: "center", justifyContent: "center" },
  submitText: { ...type.title, color: colors.onDark },
}));
