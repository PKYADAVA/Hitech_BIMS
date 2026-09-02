import { NativeStackScreenProps } from "@react-navigation/native-stack";
import React, { useEffect, useLayoutEffect, useState } from "react";
import { Alert, Pressable, ScrollView, Text, View } from "react-native";

import { http } from "@/api/client";
import { Envelope } from "@/api/types";
import { AppIcon, IconName } from "@/components/AppIcon";
import { toISODate } from "@/components/DatePicker";
import { FormControl } from "@/components/form";
import { FormField } from "@/config/forms";
import { ModuleStackParams } from "@/navigation/types";
import { queryClient } from "@/query/queryClient";
import { makeStyles, radius, spacing, type, useTheme, withAlpha } from "@/theme";
import { localDay } from "@/utils/format";

type Props = NativeStackScreenProps<ModuleStackParams, "HatchSettingForm">;

/**
 * Hatch Register & Sales Sheet — the document form.
 *
 * One setting batch over three independently-repeatable row groups (setter
 * allocations, hatcher output, customer sales) plus a running Damage/Hatch%/
 * Unsold Chicks summary — none of which the generic FormScreen or the
 * single-array DocumentForm can express. hatchery.HatchSettingAPI accepts the
 * header and all three arrays in one call (see hatchery/api_write.py), and
 * every derived figure here (Setting Qty, per-row totals, Hatch %, Unsold
 * Chicks) is computed client-side only — the web form does the same; there is
 * no server-side arithmetic to lean on, so it is reproduced here exactly.
 */

const SETTING_NO: FormField = { name: "setting_no", label: "Setting No (Batch ID)", type: "text", required: true, placeholder: "e.g. 44" };
const BATCH_FLOCK_NO: FormField = { name: "batch_flock_no", label: "Batch / Flock No", type: "text", readOnly: true, placeholder: "Assigned on save" };
const SUPPLIER_NAME: FormField = { name: "supplier_name", label: "Supplier Name", type: "text", required: true, placeholder: "Supplier name" };
const PRIMARY_MACHINE_NOS: FormField = { name: "primary_machine_nos", label: "Primary Machine Nos", type: "text", readOnly: true, placeholder: "Filled from Setter No. below" };
const AVG_EGG_WEIGHT: FormField = { name: "avg_egg_weight", label: "Avg Egg Weight", type: "text", placeholder: "e.g. EGG WT 55-58 GM" };
const RECEIVED_DATE: FormField = { name: "received_date", label: "Received Date", type: "date", required: true };
const RECEIVED_TIME: FormField = { name: "received_time", label: "Received Time", type: "time" };
const SETTING_DATE: FormField = { name: "setting_date", label: "Setting Date", type: "date", required: true };
const PUSH_TIME: FormField = { name: "push_time", label: "Push Time", type: "time" };
const TRANSFER_DATE: FormField = { name: "transfer_date", label: "Transfer Date", type: "date" };
const HATCH_DATE: FormField = { name: "hatch_date", label: "Hatch Date", type: "date" };

const RECEIVED_QTY: FormField = { name: "received_qty", label: "Received Qty", type: "number" };
const BREAKAGE_QTY: FormField = { name: "breakage_qty", label: "Damage Qty", type: "number" };
const CRACK_QTY: FormField = { name: "crack_qty", label: "Broken Qty", type: "number" };
const SETTING_QTY: FormField = { name: "setting_qty", label: "Setting Qty", type: "number", readOnly: true, transient: true };

const SETTER_TEMPERATURE: FormField = { name: "setter_temperature", label: "Setter Temperature", type: "text", placeholder: "e.g. 99F" };
const SETTER_HUMIDITY: FormField = { name: "setter_humidity", label: "Setter Humidity", type: "text", placeholder: "e.g. 60%" };
const HATCHER_TEMPERATURE: FormField = { name: "hatcher_temperature", label: "Hatcher Temperature", type: "text", placeholder: "e.g. 98.5F" };
const HATCHER_HUMIDITY: FormField = { name: "hatcher_humidity", label: "Hatcher Humidity", type: "text", placeholder: "e.g. 70%" };
const AVG_CHICK_WEIGHT: FormField = { name: "avg_chick_weight", label: "Avg Chicks Weight", type: "text", placeholder: "e.g. CHICKS WT 38-40 GM" };
const MEDICINE_VACCINE: FormField = { name: "medicine_vaccine", label: "Medicine / Vaccine", type: "text" };
const PACKING_BOXES_USED: FormField = { name: "packing_boxes_used", label: "Packing Boxes Used", type: "number" };
const REMARKS: FormField = { name: "remarks", label: "Remarks / Notes", type: "textarea" };
const PREPARED_BY: FormField = { name: "prepared_by", label: "Prepared By (Operator)", type: "text" };
const VERIFIED_BY: FormField = { name: "verified_by", label: "Verified By (Hatchery Manager)", type: "text" };

const SUB_LOT_FLOCK: FormField = { name: "sub_lot_flock", label: "Sub-Lot / Flock", type: "text" };
const SETTER_NO: FormField = { name: "setter_no", label: "Setter No.", type: "text" };
const NO_TRAYS: FormField = { name: "no_trays", label: "No. Trays", type: "number" };
const TRAY_SIZE: FormField = { name: "tray_size", label: "Tray Size", type: "number" };

const HATCHER_NO: FormField = { name: "hatcher_no", label: "Hatcher No.", type: "text" };
const INFERTILE_QTY: FormField = { name: "infertile_qty", label: "Infertile Qty", type: "number" };
const EARLY_DEAD_QTY: FormField = { name: "early_dead_qty", label: "Early Dead", type: "number" };
const BLASTING_QTY: FormField = { name: "blasting_qty", label: "Blasting Qty", type: "number" };
const DEAD_IN_SHELL_QTY: FormField = { name: "dead_in_shell_qty", label: "Dead-in-Shell", type: "number" };
const CULLS_MALF_QTY: FormField = { name: "culls_malf_qty", label: "Culls / Malformed", type: "number" };

const TRADER_CUSTOMER_NAME: FormField = { name: "trader_customer_name", label: "Customer Name", type: "text" };
const CHICKS_SOLD: FormField = { name: "chicks_sold", label: "Chicks Sold", type: "number" };
const DISCOUNT_PERCENT: FormField = { name: "discount_percent", label: "Discount %", type: "decimal" };
const RATE: FormField = { name: "rate", label: "Rate (₹)", type: "decimal" };
const PAYMENT_STATUS: FormField = {
  name: "payment_status", label: "Payment Status", type: "select",
  options: [{ value: "unpaid", label: "Unpaid" }, { value: "partial", label: "Partial" }, { value: "paid", label: "Paid" }],
};
const DELIVERY_NOTES: FormField = { name: "delivery_notes", label: "Delivery / Vehicle Notes", type: "text" };

interface EggRow { sub_lot_flock: string; setter_no: string; no_trays: string; tray_size: string }
const emptyEggRow = (): EggRow => ({ sub_lot_flock: "", setter_no: "", no_trays: "", tray_size: "" });

interface HatcherRow {
  hatcher_no: string; infertile_qty: string; early_dead_qty: string; blasting_qty: string;
  dead_in_shell_qty: string; culls_malf_qty: string;
}
const emptyHatcherRow = (): HatcherRow => ({
  hatcher_no: "", infertile_qty: "", early_dead_qty: "", blasting_qty: "",
  dead_in_shell_qty: "", culls_malf_qty: "",
});

interface SalesRow {
  trader_customer_name: string; chicks_sold: string; discount_percent: string;
  rate: string; payment_status: string; delivery_notes: string;
}
const emptySalesRow = (): SalesRow => ({
  trader_customer_name: "", chicks_sold: "", discount_percent: "",
  rate: "", payment_status: "unpaid", delivery_notes: "",
});

const n = (v: string | undefined) => Number(v) || 0;
const pct = (part: number, whole: number) => (whole ? (part / whole) * 100 : 0);
const fmtPct = (v: number) => `${v.toFixed(2)}%`;
const today = () => localDay();

/** A value counts as "already filled" — matches the web's Complete Data
 *  modal exactly (hatchery_list.html's isFilled()): blank/zero stays open
 *  for pending data, anything real locks. */
const isFilled = (v: string | undefined) => {
  const s = (v ?? "").trim();
  if (!s) return false;
  const num = Number(s);
  return Number.isFinite(num) && /^-?\d+(\.\d+)?$/.test(s) ? num !== 0 : true;
};

/** In Complete mode, a field that already has real data locks read-only —
 *  same field, same FormControl, just no longer editable. */
const lockIf = (field: FormField, locked: boolean): FormField =>
  locked ? { ...field, readOnly: true } : field;

/** UTC-safe "date string + N days", matching the web form's addDays() helper. */
function addDays(dateStr: string, days: number): string {
  if (!dateStr) return "";
  const d = new Date(`${dateStr}T00:00:00`);
  if (isNaN(d.getTime())) return "";
  d.setDate(d.getDate() + days);
  return toISODate(d);
}

function SectionHead({ icon, title, color, action }: {
  icon: IconName; title: string; color: string; action?: React.ReactNode;
}) {
  const styles = useStyles();
  return (
    <View style={[styles.sectionHead, { backgroundColor: withAlpha(color, 0.12) }]}>
      <View style={styles.sectionHeadLeft}>
        <AppIcon name={icon} size={18} color={color} />
        <Text style={[styles.sectionTitle, { color }]}>{title}</Text>
      </View>
      {action}
    </View>
  );
}

function SummaryRow({ label, value, tone }: { label: string; value: string; tone?: string }) {
  const styles = useStyles();
  const { colors } = useTheme();
  return (
    <View style={styles.billRow}>
      <Text style={styles.billLabel}>{label}</Text>
      <Text style={[styles.billValue, tone ? { color: tone } : undefined]}>{value}</Text>
    </View>
  );
}

export function HatchSettingFormScreen({ navigation, route }: Props) {
  const styles = useStyles();
  const { colors } = useTheme();
  const editing = route.params?.row ?? null;
  // Only means anything against a saved record — a fresh batch has nothing
  // to lock yet, so this is the full form regardless of how it was reached.
  const completing = !!(route.params?.completing && editing);

  const [head, setHead] = useState<Record<string, string>>({
    setting_no: "", batch_flock_no: "", supplier_name: "", primary_machine_nos: "",
    avg_egg_weight: "", received_date: today(), received_time: "", setting_date: today(),
    push_time: "", transfer_date: "", hatch_date: "",
    received_qty: "", breakage_qty: "", crack_qty: "",
    setter_temperature: "", setter_humidity: "", hatcher_temperature: "", hatcher_humidity: "",
    avg_chick_weight: "", medicine_vaccine: "", packing_boxes_used: "", remarks: "",
    prepared_by: "", verified_by: "",
  });
  const [lastAutoTransfer, setLastAutoTransfer] = useState("");
  const [lastAutoHatch, setLastAutoHatch] = useState("");
  const [eggRows, setEggRows] = useState<EggRow[]>([emptyEggRow()]);
  const [hatcherRows, setHatcherRows] = useState<HatcherRow[]>([emptyHatcherRow()]);
  const [salesRows, setSalesRows] = useState<SalesRow[]>([emptySalesRow()]);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(!!editing);
  const [error, setError] = useState<string | null>(null);

  useLayoutEffect(() => {
    navigation.setOptions({
      title: completing ? "Complete Hatch Register" : editing ? "Edit Hatch Register" : "New Hatch Register",
    });
  }, [navigation, editing, completing]);

  // An existing setting is loaded fresh — the list row is only a summary, not
  // the full egg-intake/hatcher-output/sales-line rows this form edits.
  useEffect(() => {
    if (!editing) return;
    (async () => {
      try {
        const { data } = await http.get<Envelope<Record<string, unknown>>>(
          `/hatchery/hatch-settings/save/${editing.id}`);
        const d = data.data as Record<string, any>;
        setHead({
          setting_no: d.setting_no ?? "", batch_flock_no: d.batch_flock_no ?? "",
          supplier_name: d.supplier_name ?? "", primary_machine_nos: d.primary_machine_nos ?? "",
          avg_egg_weight: d.avg_egg_weight ?? "",
          received_date: d.received_date ?? today(), received_time: (d.received_time ?? "").slice(0, 5),
          setting_date: d.setting_date ?? today(), push_time: (d.push_time ?? "").slice(0, 5),
          transfer_date: d.transfer_date ?? "", hatch_date: d.hatch_date ?? "",
          received_qty: d.received_qty ?? "", breakage_qty: d.breakage_qty ?? "", crack_qty: d.crack_qty ?? "",
          setter_temperature: d.setter_temperature ?? "", setter_humidity: d.setter_humidity ?? "",
          hatcher_temperature: d.hatcher_temperature ?? "", hatcher_humidity: d.hatcher_humidity ?? "",
          avg_chick_weight: d.avg_chick_weight ?? "", medicine_vaccine: d.medicine_vaccine ?? "",
          packing_boxes_used: d.packing_boxes_used ?? "", remarks: d.remarks ?? "",
          prepared_by: d.prepared_by ?? "", verified_by: d.verified_by ?? "",
        });
        // Loaded dates are treated as already-settled, not auto-computed —
        // editing setting_date from here on only re-triggers the 18/21-day
        // default if the user then blanks transfer/hatch date themselves.
        setLastAutoTransfer("");
        setLastAutoHatch("");
        const eggs = (d.egg_intakes ?? []) as any[];
        setEggRows(eggs.length ? eggs.map((r) => ({
          sub_lot_flock: r.sub_lot_flock ?? "", setter_no: r.setter_no ?? "",
          no_trays: r.no_trays ?? "", tray_size: r.tray_size ?? "",
        })) : [emptyEggRow()]);
        const hatchers = (d.hatcher_outputs ?? []) as any[];
        setHatcherRows(hatchers.length ? hatchers.map((r) => ({
          hatcher_no: r.hatcher_no ?? "", infertile_qty: r.infertile_qty ?? "",
          early_dead_qty: r.early_dead_qty ?? "", blasting_qty: r.blasting_qty ?? "",
          dead_in_shell_qty: r.dead_in_shell_qty ?? "", culls_malf_qty: r.culls_malf_qty ?? "",
        })) : [emptyHatcherRow()]);
        const sales = (d.sales_lines ?? []) as any[];
        setSalesRows(sales.length ? sales.map((r) => ({
          trader_customer_name: r.trader_customer_name ?? "", chicks_sold: r.chicks_sold ?? "",
          discount_percent: r.discount_percent ?? "", rate: r.rate ?? "",
          payment_status: r.payment_status ?? "unpaid", delivery_notes: r.delivery_notes ?? "",
        })) : [emptySalesRow()]);
      } catch {
        setError("Could not load this hatch setting.");
      } finally {
        setLoading(false);
      }
    })();
  }, [editing]);

  const onHead = (name: string) => (value: string) => setHead((cur) => ({ ...cur, [name]: value }));

  // Setting Date drives Transfer/Hatch Date defaults (+18 / +21 days) until
  // the user hand-edits either — the same "sticky once touched" rule the web
  // form uses, so a correction here isn't silently overwritten on the next
  // Setting Date tweak.
  const onSettingDate = (value: string) => {
    setHead((cur) => {
      const next: Record<string, string> = { ...cur, setting_date: value };
      if (value) {
        if (!cur.transfer_date || cur.transfer_date === lastAutoTransfer) {
          const t = addDays(value, 18);
          next.transfer_date = t;
          setLastAutoTransfer(t);
        }
        if (!cur.hatch_date || cur.hatch_date === lastAutoHatch) {
          const h = addDays(value, 21);
          next.hatch_date = h;
          setLastAutoHatch(h);
        }
      }
      return next;
    });
  };

  const onEgg = (index: number, key: keyof EggRow) => (value: string) =>
    setEggRows((cur) => cur.map((row, i) => (i === index ? { ...row, [key]: value } : row)));
  const onHatcher = (index: number, key: keyof HatcherRow) => (value: string) =>
    setHatcherRows((cur) => cur.map((row, i) => (i === index ? { ...row, [key]: value } : row)));
  const onSales = (index: number, key: keyof SalesRow) => (value: string) =>
    setSalesRows((cur) => cur.map((row, i) => (i === index ? { ...row, [key]: value } : row)));

  // --- Derived figures — every one of these is computed client-side only;
  // there is no server-side arithmetic for this document to lean on (see
  // HatchSettingFormScreen's file doc comment), so the web form's exact
  // formulas are reproduced here.
  const receivedQty = n(head.received_qty);
  const breakageQty = n(head.breakage_qty);
  const crackQty = n(head.crack_qty);
  const settingQty = Math.max(receivedQty - breakageQty - crackQty, 0);
  const breakagePercent = pct(breakageQty, receivedQty);
  const crackPercent = pct(crackQty, receivedQty);

  const eggRowsComputed = eggRows.map((r) => ({ ...r, total_eggs: n(r.no_trays) * n(r.tray_size) }));
  const totalTrays = eggRowsComputed.reduce((s, r) => s + n(r.no_trays), 0);
  const totalEggsAllocated = eggRowsComputed.reduce((s, r) => s + r.total_eggs, 0);
  const balanceEggQty = settingQty - totalEggsAllocated;
  // Web joins with a bare comma (recalcPrimaryMachineNos in hatchery_form.html) — matched exactly.
  const primaryMachineNos = [...new Set(eggRows.map((r) => r.setter_no.trim()).filter(Boolean))].join(",");

  const hatcherRowsComputed = hatcherRows.map((r) => {
    const transfer = Math.max(settingQty - (n(r.infertile_qty) + n(r.early_dead_qty) + n(r.blasting_qty)), 0);
    const saleable = Math.max(transfer - (n(r.dead_in_shell_qty) + n(r.culls_malf_qty)), 0);
    return { ...r, transfer_qty: transfer, saleable_chicks: saleable };
  });
  const totalSaleableChicks = hatcherRowsComputed.reduce((s, r) => s + r.saleable_chicks, 0);
  const hatchPercent = pct(totalSaleableChicks, settingQty);

  const salesRowsComputed = salesRows.map((r) => {
    const sold = n(r.chicks_sold);
    const discount = n(r.discount_percent);
    const billed = Math.round(sold / (1 + discount / 100));
    const free = Math.round(sold - billed);
    const amount = billed * n(r.rate);
    return { ...r, billed_chicks: billed, free_chicks: free, total_amount: amount };
  });
  const totalChicksSold = salesRowsComputed.reduce((s, r) => s + n(r.chicks_sold), 0);
  const totalSalesAmount = salesRowsComputed.reduce((s, r) => s + r.total_amount, 0);
  const unsoldChicks = totalSaleableChicks - totalChicksSold;

  const submit = async () => {
    setError(null);
    if (!head.setting_no.trim()) return setError("Setting No (Batch ID) is required.");
    if (!head.supplier_name.trim()) return setError("Supplier Name is required.");
    if (!head.received_date) return setError("Received Date is required.");
    if (!head.setting_date) return setError("Setting Date is required.");

    setSaving(true);
    try {
      const payload = {
        ...head,
        primary_machine_nos: primaryMachineNos,
        setting_qty: String(settingQty),
        egg_intakes: eggRowsComputed
          .filter((r) => r.setter_no.trim() || n(r.no_trays) || n(r.tray_size))
          .map((r) => ({
            sub_lot_flock: r.sub_lot_flock, setter_no: r.setter_no,
            no_trays: r.no_trays || "0", tray_size: r.tray_size || "0", total_eggs: String(r.total_eggs),
          })),
        hatcher_outputs: hatcherRowsComputed
          .filter((r) => r.hatcher_no.trim() || r.transfer_qty || r.saleable_chicks)
          .map((r) => ({
            hatcher_no: r.hatcher_no, infertile_qty: r.infertile_qty || "0",
            early_dead_qty: r.early_dead_qty || "0", blasting_qty: r.blasting_qty || "0",
            transfer_qty: String(r.transfer_qty), dead_in_shell_qty: r.dead_in_shell_qty || "0",
            culls_malf_qty: r.culls_malf_qty || "0", saleable_chicks: String(r.saleable_chicks),
          })),
        sales_lines: salesRowsComputed
          .filter((r) => r.trader_customer_name.trim() || n(r.chicks_sold))
          .map((r) => ({
            trader_customer_name: r.trader_customer_name, chicks_sold: r.chicks_sold || "0",
            discount_percent: r.discount_percent || "0", free_chicks: String(r.free_chicks),
            billed_chicks: String(r.billed_chicks), rate: r.rate || "0",
            total_amount: String(r.total_amount), payment_status: r.payment_status,
            delivery_notes: r.delivery_notes,
          })),
      };
      if (editing) {
        await http.put(`/hatchery/hatch-settings/save/${editing.id}`, payload);
      } else {
        await http.post("/hatchery/hatch-settings/save", payload);
      }
      queryClient.invalidateQueries({ queryKey: ["list", "/hatchery/hatch-settings/"] });
      navigation.goBack();
    } catch (e: unknown) {
      const message = (e as { message?: string })?.message;
      setError(message ?? "Could not save.");
      Alert.alert("Could not save", message ?? "Please check the entries and try again.");
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <View style={styles.screen} />;

  return (
    <View style={styles.screen}>
      <ScrollView contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
        {error ? <Text style={styles.error}>{error}</Text> : null}

        <View style={styles.card}>
          <SectionHead icon="calendar-range" title="1. HATCH LOT & TIMELINE" color={colors.tint} />
          <View style={styles.cardBody}>
            <FormControl field={lockIf(SETTING_NO, completing)} value={head.setting_no} onChange={onHead("setting_no")} />
            <View style={styles.row}>
              <View style={styles.cell}><FormControl field={BATCH_FLOCK_NO} value={head.batch_flock_no} onChange={onHead("batch_flock_no")} /></View>
              <View style={styles.cell}><FormControl field={lockIf(AVG_EGG_WEIGHT, completing && isFilled(head.avg_egg_weight))} value={head.avg_egg_weight} onChange={onHead("avg_egg_weight")} /></View>
            </View>
            <FormControl field={lockIf(SUPPLIER_NAME, completing)} value={head.supplier_name} onChange={onHead("supplier_name")} />
            <FormControl field={PRIMARY_MACHINE_NOS} value={primaryMachineNos} onChange={() => {}} />
            <View style={styles.row}>
              <View style={styles.cell}><FormControl field={lockIf(RECEIVED_DATE, completing && isFilled(head.received_date))} value={head.received_date} onChange={onHead("received_date")} /></View>
              <View style={styles.cell}><FormControl field={lockIf(RECEIVED_TIME, completing && isFilled(head.received_time))} value={head.received_time} onChange={onHead("received_time")} /></View>
            </View>
            <View style={styles.row}>
              <View style={styles.cell}><FormControl field={lockIf(SETTING_DATE, completing)} value={head.setting_date} onChange={onSettingDate} /></View>
              <View style={styles.cell}><FormControl field={lockIf(PUSH_TIME, completing && isFilled(head.push_time))} value={head.push_time} onChange={onHead("push_time")} /></View>
            </View>
            <View style={styles.row}>
              <View style={styles.cell}><FormControl field={TRANSFER_DATE} value={head.transfer_date} onChange={onHead("transfer_date")} /></View>
              <View style={styles.cell}><FormControl field={HATCH_DATE} value={head.hatch_date} onChange={onHead("hatch_date")} /></View>
            </View>
          </View>
        </View>

        <View style={styles.card}>
          <SectionHead icon="egg-outline" title="2. EGG INTAKE & MULTI-SETTER" color={colors.success} />
          <View style={styles.cardBody}>
            <View style={styles.row}>
              <View style={styles.cell}><FormControl field={lockIf(RECEIVED_QTY, completing && isFilled(head.received_qty))} value={head.received_qty} onChange={onHead("received_qty")} /></View>
              <View style={styles.cell}><FormControl field={SETTING_QTY} value={String(settingQty)} onChange={() => {}} /></View>
            </View>
            <View style={styles.row}>
              <View style={styles.cell}><FormControl field={lockIf(BREAKAGE_QTY, completing && isFilled(head.breakage_qty))} value={head.breakage_qty} onChange={onHead("breakage_qty")} /></View>
              <View style={styles.cell}><FormControl field={lockIf(CRACK_QTY, completing && isFilled(head.crack_qty))} value={head.crack_qty} onChange={onHead("crack_qty")} /></View>
            </View>
            <Text style={styles.hint}>
              Damage {fmtPct(breakagePercent)} · Broken {fmtPct(crackPercent)} — targets: Damage &lt; 1.00%, Broken &lt; 0.75%
            </Text>
          </View>
          <View style={[styles.cardBody, styles.lineDivider]}>
            <Text style={styles.subheading}>SETTER ALLOCATION ({eggRows.length})</Text>
            {eggRows.map((row, i) => {
              // Matches the web's Complete Data modal exactly: a setter row
              // with a Setter No. or a Total Eggs already on it is done —
              // only a genuinely blank row stays open, and only then can it
              // be removed again.
              const rowLocked = completing && (isFilled(row.setter_no) || eggRowsComputed[i].total_eggs !== 0);
              return (
              <View key={i} style={i > 0 ? styles.lineDivider : undefined}>
                <View style={styles.lineHead}>
                  <View style={styles.cell}><FormControl field={lockIf(SUB_LOT_FLOCK, rowLocked)} value={row.sub_lot_flock} onChange={onEgg(i, "sub_lot_flock")} /></View>
                  {eggRows.length > 1 && !rowLocked ? (
                    <Pressable style={styles.removeBtn} onPress={() => setEggRows((cur) => cur.filter((_, j) => j !== i))}
                               accessibilityRole="button" accessibilityLabel="Remove setter row">
                      <AppIcon name="trash-can-outline" size={16} color={colors.danger} />
                    </Pressable>
                  ) : null}
                </View>
                <View style={styles.row}>
                  <View style={styles.cell}><FormControl field={lockIf(SETTER_NO, rowLocked)} value={row.setter_no} onChange={onEgg(i, "setter_no")} /></View>
                  <View style={styles.cell}><FormControl field={lockIf(NO_TRAYS, rowLocked)} value={row.no_trays} onChange={onEgg(i, "no_trays")} /></View>
                  <View style={styles.cell}><FormControl field={lockIf(TRAY_SIZE, rowLocked)} value={row.tray_size} onChange={onEgg(i, "tray_size")} /></View>
                </View>
                <View style={[styles.itemTotal, { backgroundColor: withAlpha(colors.success, 0.1) }]}>
                  <Text style={styles.itemTotalLabel}>Total Eggs</Text>
                  <Text style={[styles.itemTotalValue, { color: colors.success }]}>{eggRowsComputed[i].total_eggs.toLocaleString("en-IN")}</Text>
                </View>
              </View>
              );
            })}
          </View>
          <Pressable style={styles.addRow} onPress={() => setEggRows((cur) => [...cur, emptyEggRow()])}>
            <AppIcon name="plus" size={16} color={colors.success} />
            <Text style={[styles.addRowText, { color: colors.success }]}>Add Setter Row</Text>
          </Pressable>
          <View style={styles.cardBody}>
            <SummaryRow label="Total Trays" value={totalTrays.toLocaleString("en-IN")} />
            <SummaryRow label="Balance Egg Qty" value={balanceEggQty.toLocaleString("en-IN")}
                        tone={balanceEggQty === 0 ? colors.success : colors.danger} />
          </View>
        </View>

        <View style={styles.card}>
          <SectionHead icon="cog-outline" title="3. CANDLING & HATCH OUTPUT" color={colors.warning} />
          <View style={styles.cardBody}>
            <Text style={styles.subheading}>HATCHER OUTPUT ({hatcherRows.length})</Text>
            {hatcherRows.map((row, i) => {
              const computed = hatcherRowsComputed[i];
              // Each field of a hatcher row locks on its own once it has
              // real data — a row can be half pending (candling done, hatch
              // output still to come) — matching the web's Complete Data
              // modal field-by-field. The row can only be removed while none
              // of its fields have been touched yet.
              const lockHatcherNo = completing && isFilled(row.hatcher_no);
              const lockInfertile = completing && isFilled(row.infertile_qty);
              const lockEarlyDead = completing && isFilled(row.early_dead_qty);
              const lockBlasting = completing && isFilled(row.blasting_qty);
              const lockDeadInShell = completing && isFilled(row.dead_in_shell_qty);
              const lockCulls = completing && isFilled(row.culls_malf_qty);
              const hasAnyData = lockHatcherNo || lockInfertile || lockEarlyDead
                || lockBlasting || lockDeadInShell || lockCulls;
              return (
                <View key={i} style={i > 0 ? styles.lineDivider : undefined}>
                  <View style={styles.lineHead}>
                    <View style={styles.cell}><FormControl field={lockIf(HATCHER_NO, lockHatcherNo)} value={row.hatcher_no} onChange={onHatcher(i, "hatcher_no")} /></View>
                    {hatcherRows.length > 1 && !hasAnyData ? (
                      <Pressable style={styles.removeBtn} onPress={() => setHatcherRows((cur) => cur.filter((_, j) => j !== i))}
                                 accessibilityRole="button" accessibilityLabel="Remove hatcher row">
                        <AppIcon name="trash-can-outline" size={16} color={colors.danger} />
                      </Pressable>
                    ) : null}
                  </View>
                  <View style={styles.row}>
                    <View style={styles.cell}><FormControl field={lockIf(INFERTILE_QTY, lockInfertile)} value={row.infertile_qty} onChange={onHatcher(i, "infertile_qty")} /></View>
                    <View style={styles.cell}><FormControl field={lockIf(EARLY_DEAD_QTY, lockEarlyDead)} value={row.early_dead_qty} onChange={onHatcher(i, "early_dead_qty")} /></View>
                  </View>
                  <View style={styles.row}>
                    <View style={styles.cell}><FormControl field={lockIf(BLASTING_QTY, lockBlasting)} value={row.blasting_qty} onChange={onHatcher(i, "blasting_qty")} /></View>
                    <View style={styles.cell}><FormControl field={lockIf(DEAD_IN_SHELL_QTY, lockDeadInShell)} value={row.dead_in_shell_qty} onChange={onHatcher(i, "dead_in_shell_qty")} /></View>
                  </View>
                  <FormControl field={lockIf(CULLS_MALF_QTY, lockCulls)} value={row.culls_malf_qty} onChange={onHatcher(i, "culls_malf_qty")} />
                  <View style={styles.row}>
                    <View style={[styles.itemTotal, styles.cell, { backgroundColor: withAlpha(colors.warning, 0.1) }]}>
                      <Text style={styles.itemTotalLabel}>Transfer Qty</Text>
                      <Text style={[styles.itemTotalValue, { color: colors.warning }]}>{computed.transfer_qty.toLocaleString("en-IN")}</Text>
                    </View>
                    <View style={[styles.itemTotal, styles.cell, { backgroundColor: withAlpha(colors.warning, 0.1) }]}>
                      <Text style={styles.itemTotalLabel}>Saleable Chicks</Text>
                      <Text style={[styles.itemTotalValue, { color: colors.warning }]}>{computed.saleable_chicks.toLocaleString("en-IN")}</Text>
                    </View>
                  </View>
                </View>
              );
            })}
          </View>
          <Pressable style={styles.addRow} onPress={() => setHatcherRows((cur) => [...cur, emptyHatcherRow()])}>
            <AppIcon name="plus" size={16} color={colors.warning} />
            <Text style={[styles.addRowText, { color: colors.warning }]}>Add Hatcher Row</Text>
          </Pressable>
          <View style={styles.cardBody}>
            <SummaryRow label="Hatch % (of Setting Qty)" value={fmtPct(hatchPercent)} tone={colors.warning} />
            <Text style={styles.hint}>Target: Max Infertility &lt; 12.00% · Max Dead-in-Shell &lt; 2.00% · Min Saleable Hatch 65–70%</Text>
          </View>
        </View>

        <View style={styles.card}>
          <SectionHead icon="thermometer" title="4. ENVIRONMENT & CONSUMABLES" color={colors.info} />
          <View style={styles.cardBody}>
            <View style={styles.row}>
              <View style={styles.cell}><FormControl field={SETTER_TEMPERATURE} value={head.setter_temperature} onChange={onHead("setter_temperature")} /></View>
              <View style={styles.cell}><FormControl field={SETTER_HUMIDITY} value={head.setter_humidity} onChange={onHead("setter_humidity")} /></View>
            </View>
            <View style={styles.row}>
              <View style={styles.cell}><FormControl field={HATCHER_TEMPERATURE} value={head.hatcher_temperature} onChange={onHead("hatcher_temperature")} /></View>
              <View style={styles.cell}><FormControl field={HATCHER_HUMIDITY} value={head.hatcher_humidity} onChange={onHead("hatcher_humidity")} /></View>
            </View>
            <View style={styles.row}>
              <View style={styles.cell}><FormControl field={AVG_CHICK_WEIGHT} value={head.avg_chick_weight} onChange={onHead("avg_chick_weight")} /></View>
              <View style={styles.cell}><FormControl field={PACKING_BOXES_USED} value={head.packing_boxes_used} onChange={onHead("packing_boxes_used")} /></View>
            </View>
            <FormControl field={MEDICINE_VACCINE} value={head.medicine_vaccine} onChange={onHead("medicine_vaccine")} />
            <FormControl field={REMARKS} value={head.remarks} onChange={onHead("remarks")} />
          </View>
        </View>

        <View style={[styles.card, { borderColor: withAlpha(colors.hatchery, 0.3) }]}>
          <SectionHead icon="truck-delivery" title="5. HATCHERY SALE & CLEARANCE" color={colors.hatchery} />
          <View style={styles.cardBody}>
            {salesRows.map((row, i) => {
              const computed = salesRowsComputed[i];
              // Matches the web's Complete Data modal: a sale already
              // recorded (a customer name or a sold quantity) is done,
              // Payment Status included — updating an existing sale's status
              // is what full Edit is for, not this quick top-up.
              const rowLocked = completing && (isFilled(row.trader_customer_name) || isFilled(row.chicks_sold));
              return (
                <View key={i} style={i > 0 ? styles.lineDivider : undefined}>
                  <View style={styles.lineHead}>
                    <View style={styles.cell}><FormControl field={lockIf(TRADER_CUSTOMER_NAME, rowLocked)} value={row.trader_customer_name} onChange={onSales(i, "trader_customer_name")} /></View>
                    {salesRows.length > 1 && !rowLocked ? (
                      <Pressable style={styles.removeBtn} onPress={() => setSalesRows((cur) => cur.filter((_, j) => j !== i))}
                                 accessibilityRole="button" accessibilityLabel="Remove customer row">
                        <AppIcon name="trash-can-outline" size={16} color={colors.danger} />
                      </Pressable>
                    ) : null}
                  </View>
                  <View style={styles.row}>
                    <View style={styles.cell}><FormControl field={lockIf(CHICKS_SOLD, rowLocked)} value={row.chicks_sold} onChange={onSales(i, "chicks_sold")} /></View>
                    <View style={styles.cell}><FormControl field={lockIf(DISCOUNT_PERCENT, rowLocked)} value={row.discount_percent} onChange={onSales(i, "discount_percent")} /></View>
                  </View>
                  <View style={styles.row}>
                    <View style={styles.cell}><FormControl field={lockIf(RATE, rowLocked)} value={row.rate} onChange={onSales(i, "rate")} /></View>
                    <View style={styles.cell}><FormControl field={lockIf(PAYMENT_STATUS, rowLocked)} value={row.payment_status} onChange={onSales(i, "payment_status")} /></View>
                  </View>
                  <FormControl field={lockIf(DELIVERY_NOTES, rowLocked)} value={row.delivery_notes} onChange={onSales(i, "delivery_notes")} />
                  <View style={styles.row}>
                    <View style={[styles.itemTotal, styles.cell, { backgroundColor: withAlpha(colors.hatchery, 0.1) }]}>
                      <Text style={styles.itemTotalLabel}>Billed / Free</Text>
                      <Text style={[styles.itemTotalValue, { color: colors.hatchery }]}>{computed.billed_chicks} / {computed.free_chicks}</Text>
                    </View>
                    <View style={[styles.itemTotal, styles.cell, { backgroundColor: withAlpha(colors.hatchery, 0.1) }]}>
                      <Text style={styles.itemTotalLabel}>Total Amount</Text>
                      <Text style={[styles.itemTotalValue, { color: colors.hatchery }]}>
                        ₹ {computed.total_amount.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </Text>
                    </View>
                  </View>
                </View>
              );
            })}
          </View>
          <Pressable style={styles.addRow} onPress={() => setSalesRows((cur) => [...cur, emptySalesRow()])}>
            <AppIcon name="plus" size={16} color={colors.hatchery} />
            <Text style={[styles.addRowText, { color: colors.hatchery }]}>Add Customer Row</Text>
          </Pressable>
          <View style={styles.cardBody}>
            <SummaryRow label="Total Sales" value={`₹ ${totalSalesAmount.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`} />
            <View style={[styles.billRow, styles.billTotalRow]}>
              <Text style={styles.billTotalLabel}>Unsold Chicks</Text>
              <Text style={[styles.billTotalValue, { color: colors.hatchery }]}>{unsoldChicks.toLocaleString("en-IN")}</Text>
            </View>
          </View>
        </View>

        <View style={styles.card}>
          <SectionHead icon="clipboard-text-outline" title="AUDIT & SIGN-OFF" color={colors.textMuted} />
          <View style={styles.cardBody}>
            <FormControl field={PREPARED_BY} value={head.prepared_by} onChange={onHead("prepared_by")} />
            <FormControl field={VERIFIED_BY} value={head.verified_by} onChange={onHead("verified_by")} />
          </View>
        </View>
      </ScrollView>

      <View style={styles.footer}>
        <Pressable style={[styles.cancel, { borderColor: colors.danger }]} onPress={() => navigation.goBack()}>
          <AppIcon name="close" size={16} color={colors.danger} />
          <Text style={[styles.cancelText, { color: colors.danger }]}>Cancel</Text>
        </Pressable>
        <Pressable style={[styles.submit, { backgroundColor: colors.hatchery }, saving && { opacity: 0.6 }]}
                   onPress={submit} disabled={saving}>
          <AppIcon name="check" size={16} color="#fff" />
          <Text style={styles.submitText}>{saving ? "Saving…" : "Save Hatch Register"}</Text>
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
    borderWidth: 1, borderColor: colors.border, overflow: "hidden",
  },
  cardBody: { padding: spacing.md, gap: spacing.sm },
  sectionHead: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
  },
  sectionHeadLeft: { flexDirection: "row", alignItems: "center", gap: spacing.xs },
  sectionTitle: { ...type.label, letterSpacing: 0.6, fontWeight: "800" },
  subheading: { ...type.caption, color: colors.textMuted, fontWeight: "800", letterSpacing: 0.4 },
  row: { flexDirection: "row", gap: spacing.sm, alignItems: "flex-start" },
  cell: { flex: 1, minWidth: 0 },
  hint: { ...type.caption, color: colors.textFaint },
  lineDivider: { borderTopWidth: 1, borderTopColor: colors.border, paddingTop: spacing.sm, marginTop: spacing.sm },
  lineHead: { flexDirection: "row", alignItems: "flex-end", gap: spacing.sm },
  removeBtn: {
    width: 36, height: 36, borderRadius: radius.sm, alignItems: "center", justifyContent: "center",
    borderWidth: 1, borderColor: colors.border, marginBottom: 2,
  },
  itemTotal: {
    flexDirection: "row", justifyContent: "space-between", alignItems: "center",
    borderRadius: radius.sm, paddingHorizontal: spacing.sm, paddingVertical: spacing.xs, marginTop: spacing.xs,
  },
  itemTotalLabel: { ...type.caption, color: colors.textMuted },
  itemTotalValue: { ...type.title, fontWeight: "800" },
  addRow: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.xs,
    borderTopWidth: 1, borderTopColor: colors.border, borderStyle: "dashed",
    paddingVertical: spacing.sm,
  },
  addRowText: { ...type.body, fontWeight: "700" },
  billRow: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 4 },
  billLabel: { ...type.body, color: colors.textMuted },
  billValue: { ...type.body, color: colors.text, fontWeight: "600" },
  billTotalRow: { borderTopWidth: 1, borderTopColor: colors.border, marginTop: spacing.xs, paddingTop: spacing.sm },
  billTotalLabel: { ...type.title, fontWeight: "800" },
  billTotalValue: { ...type.h3, fontWeight: "800" },
  error: { ...type.caption, color: colors.danger },
  footer: {
    flexDirection: "row", gap: spacing.sm, padding: spacing.md,
    borderTopWidth: 1, borderTopColor: colors.border, backgroundColor: colors.surface,
  },
  cancel: {
    flex: 1, height: 48, borderRadius: radius.md, borderWidth: 1,
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.xs,
  },
  cancelText: { ...type.title },
  submit: {
    flex: 2, height: 48, borderRadius: radius.md,
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.xs,
  },
  submitText: { ...type.title, color: "#fff" },
}));
