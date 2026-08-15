import { NativeStackScreenProps } from "@react-navigation/native-stack";
import React, { useEffect, useLayoutEffect, useState } from "react";
import { Alert, Pressable, ScrollView, Text, View } from "react-native";

import { http } from "@/api/client";
import { Envelope } from "@/api/types";
import { AppIcon, IconName } from "@/components/AppIcon";
import { FormControl } from "@/components/form";
import { FormField } from "@/config/forms";
import { ModuleStackParams } from "@/navigation/types";
import { queryClient } from "@/query/queryClient";
import { makeStyles, radius, spacing, type, useTheme, withAlpha } from "@/theme";

type Props = NativeStackScreenProps<ModuleStackParams, "EggPurchaseForm">;

/**
 * Egg Purchase — the document form.
 *
 * One supplier delivery over several egg-item lines plus freight/TCS/payment
 * terms, which is how the ERP form works and what hatchery.EggPurchaseAPI
 * accepts in one call (see hatchery/api_write.py — a header+rows POST, not a
 * parent-then-children two-step). The generic FormScreen can express one flat
 * record; this needs the header, a line you can add to, and a running Bill
 * Summary, so it is its own screen, styled to the reference's card sections
 * rather than the generic form's plain field list.
 */

const SUPPLIER: FormField = {
  name: "supplier", label: "Supplier", type: "select", required: true,
  optionsPath: "/suppliers/", optionLabelKeys: ["name", "code"], placeholder: "Select Supplier",
};
const WAREHOUSE: FormField = {
  name: "warehouse", label: "Warehouse", type: "select", required: true,
  optionsPath: "/warehouses/", optionLabelKeys: ["name", "code"], placeholder: "Select Warehouse",
};
const DATE: FormField = { name: "date", label: "Date", type: "date", required: true };
const DC_NO: FormField = { name: "dc_no", label: "DC No.", type: "text", placeholder: "Enter DC Number" };
/** Assigned by the backend on save (EggPurchase._next_transaction_no) — never
 *  user-entered, so it reads "Assigned on save" until there's a real one. */
const TRANSACTION_NO: FormField = {
  name: "transaction_no", label: "Transaction No.", type: "text", readOnly: true,
  placeholder: "Assigned on save",
};
const VEHICLE: FormField = { name: "vehicle", label: "Vehicle No.", type: "text", placeholder: "e.g. UP53AB1234" };
const DRIVER: FormField = { name: "driver", label: "Driver Name", type: "text", placeholder: "Driver Full Name" };
const ITEM: FormField = {
  name: "item", label: "Item", type: "select", required: true,
  optionsPath: "/items/", optionLabelKeys: ["description", "item_code"],
};
const SENT_QTY: FormField = { name: "sent_qty", label: "Sent Qty", type: "decimal" };
const RCV_QTY: FormField = { name: "rcv_qty", label: "Rcv Qty", type: "decimal" };
const FREE_QTY: FormField = { name: "free_qty", label: "Free Qty", type: "decimal" };
const NO_OF_BOXES: FormField = { name: "no_of_boxes", label: "No. of Boxes", type: "decimal" };
const RATE: FormField = { name: "rate", label: "Rate (₹)", type: "decimal", required: true };
const DISC_PCT: FormField = { name: "discount_percent", label: "Disc %", type: "decimal" };
const DISC_AMT: FormField = { name: "discount_amount", label: "Disc (₹)", type: "decimal" };
const PAY_ACCOUNT: FormField = {
  name: "pay_account", label: "Pay Account", type: "select",
  optionsPath: "/account/chart-of-accounts/", optionLabelKeys: ["description", "code"],
};
const FREIGHT_TYPE: FormField = {
  name: "freight_type", label: "Freight Type", type: "select",
  options: [{ value: "Exclude", label: "Exclude" }, { value: "Include", label: "Include" }],
};
const FREIGHT_AMOUNT: FormField = { name: "freight_amount", label: "Freight Amount (₹)", type: "decimal" };
const FREIGHT_ACCOUNT: FormField = {
  name: "freight_account", label: "Freight Account", type: "select",
  optionsPath: "/account/chart-of-accounts/", optionLabelKeys: ["description", "code"],
};
const TCS_PERCENT: FormField = { name: "tcs_percent", label: "TCS Rate (%)", type: "decimal" };
const REMARKS: FormField = { name: "remarks", label: "Remarks", type: "textarea" };

interface ItemRow {
  item: string; sent_qty: string; rcv_qty: string; free_qty: string;
  no_of_boxes: string; rate: string; discount_percent: string; discount_amount: string;
}
const emptyItem = (): ItemRow => ({
  item: "", sent_qty: "", rcv_qty: "", free_qty: "",
  no_of_boxes: "", rate: "", discount_percent: "", discount_amount: "",
});

const itemTotal = (row: ItemRow): number => {
  const basis = Number(row.rcv_qty) || Number(row.sent_qty) || 0;
  const amount = (Number(row.rate) || 0) * basis;
  const pctOff = (amount * (Number(row.discount_percent) || 0)) / 100;
  return amount - pctOff - (Number(row.discount_amount) || 0);
};

const today = () => new Date().toISOString().slice(0, 10);
const rupees = (n: number) =>
  `₹ ${n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

/** A section's own colour-tinted header — icon, title, and its own accent,
 *  matching the reference's banded card sections rather than one uniform look. */
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

export function EggPurchaseFormScreen({ navigation, route }: Props) {
  const styles = useStyles();
  const { colors } = useTheme();
  /** The saved purchase being corrected, or null when recording a new one. */
  const editing = route.params?.row ?? null;

  const [head, setHead] = useState<Record<string, string>>({
    transaction_no: (editing as { transaction_no?: string })?.transaction_no ?? "",
    date: today(), supplier: "", warehouse: "", dc_no: "", vehicle: "", driver: "",
    payment_mode: "pay_later", pay_account: "", freight_type: "Exclude",
    freight_amount: "", freight_account: "", tcs_percent: "0.10", remarks: "",
  });
  const [tcsApplicable, setTcsApplicable] = useState(false);
  const [items, setItems] = useState<ItemRow[]>([emptyItem()]);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(!!editing);
  const [error, setError] = useState<string | null>(null);

  useLayoutEffect(() => {
    navigation.setOptions({ title: editing ? "Edit Egg Purchase" : "Add Egg Purchase" });
  }, [navigation, editing]);

  // An existing purchase is loaded fresh rather than trusting the list row —
  // the list's own row is a summary (item_names, not the full item rows this
  // form needs to let you correct them).
  useEffect(() => {
    if (!editing) return;
    (async () => {
      try {
        const { data } = await http.get<Envelope<Record<string, unknown>>>(
          `/hatchery/egg-purchases/save/${editing.id}`);
        const d = data.data as Record<string, any>;
        setHead({
          transaction_no: d.transaction_no ?? "",
          date: d.date ?? today(), supplier: d.supplier ?? "", warehouse: d.warehouse ?? "",
          dc_no: d.dc_no ?? "", vehicle: d.vehicle ?? "", driver: d.driver ?? "",
          payment_mode: d.payment_mode ?? "pay_later", pay_account: d.pay_account ?? "",
          freight_type: d.freight_type ?? "Exclude", freight_amount: d.freight_amount ?? "",
          freight_account: d.freight_account ?? "", tcs_percent: d.tcs_percent ?? "0.10",
          remarks: d.remarks ?? "",
        });
        setTcsApplicable(!!d.tcs_applicable);
        const rows = (d.items ?? []) as ItemRow[];
        setItems(rows.length ? rows : [emptyItem()]);
      } catch {
        setError("Could not load this purchase.");
      } finally {
        setLoading(false);
      }
    })();
  }, [editing]);

  const onHead = (name: string) => (value: string) => setHead((cur) => ({ ...cur, [name]: value }));
  const onItem = (index: number, key: keyof ItemRow) => (value: string) =>
    setItems((cur) => cur.map((row, i) => (i === index ? { ...row, [key]: value } : row)));

  // --- Bill Summary — mirrors hatchery.EggPurchase.gross_amount /
  // freight_included_amount / tcs_amount / net_amount exactly: freight only
  // enters the payable total when Freight Type is Include, and TCS is taken
  // on that same (freight-included-or-not) base. A total that always added
  // freight regardless of the flag would show one number here and a
  // different one once this actually saves.
  const grossTotal = items.reduce((sum, row) => sum + itemTotal(row), 0);
  const freightIncluded = head.freight_type === "Include";
  const freightAmount = Number(head.freight_amount) || 0;
  const freightBase = grossTotal + (freightIncluded ? freightAmount : 0);
  const tcsAmount = tcsApplicable ? (freightBase * (Number(head.tcs_percent) || 0)) / 100 : 0;
  const netPayable = freightBase + tcsAmount;
  // Net Quantity/Net Rate — EggPurchase.net_quantity()/net_rate(): the eggs
  // that actually arrived (received + free, bonus stock included) and what
  // they cost per received egg once freight/TCS are folded in. Free Qty has
  // no cost basis of its own, so the rate still divides by Rcv Qty only.
  const netQuantity = items.reduce((sum, row) => sum + (Number(row.rcv_qty) || 0) + (Number(row.free_qty) || 0), 0);
  const rcvQtyTotal = items.reduce((sum, row) => sum + (Number(row.rcv_qty) || 0), 0);
  const netRate = rcvQtyTotal ? netPayable / rcvQtyTotal : 0;

  const submit = async () => {
    setError(null);
    if (!head.supplier) return setError("Supplier is required.");
    if (!head.warehouse) return setError("Warehouse is required.");
    if (!head.date) return setError("Date is required.");
    const filled = items.filter((row) => row.item && row.rate);
    if (!filled.length) return setError("Add at least one item with a rate.");

    setSaving(true);
    try {
      const payload = {
        ...head,
        tcs_applicable: tcsApplicable,
        items: filled.map((row) => ({
          item: row.item, sent_qty: row.sent_qty || "0", rcv_qty: row.rcv_qty || "0",
          free_qty: row.free_qty || "0", no_of_boxes: row.no_of_boxes || "0",
          rate: row.rate, discount_percent: row.discount_percent || "0",
          discount_amount: row.discount_amount || "0",
        })),
      };
      if (editing) {
        await http.put(`/hatchery/egg-purchases/save/${editing.id}`, payload);
      } else {
        await http.post("/hatchery/egg-purchases/save", payload);
      }
      queryClient.invalidateQueries({ queryKey: ["list", "/hatchery/egg-purchases/"] });
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
          <SectionHead icon="truck-outline" title="VENDOR & LOGISTICS" color={colors.tint} />
          <View style={styles.cardBody}>
            <View style={styles.row}>
              <View style={styles.cell}><FormControl field={SUPPLIER} value={head.supplier} onChange={onHead("supplier")} /></View>
              <View style={styles.cell}><FormControl field={WAREHOUSE} value={head.warehouse} onChange={onHead("warehouse")} /></View>
            </View>
            <View style={styles.row}>
              <View style={styles.cell}><FormControl field={DATE} value={head.date} onChange={onHead("date")} /></View>
              <View style={styles.cell}><FormControl field={DC_NO} value={head.dc_no} onChange={onHead("dc_no")} /></View>
            </View>
            <View style={styles.row}>
              <View style={styles.cell}><FormControl field={TRANSACTION_NO} value={head.transaction_no} onChange={onHead("transaction_no")} /></View>
              <View style={styles.cell}><FormControl field={VEHICLE} value={head.vehicle} onChange={onHead("vehicle")} /></View>
            </View>
            <FormControl field={DRIVER} value={head.driver} onChange={onHead("driver")} />
          </View>
        </View>

        <View style={styles.card}>
          <SectionHead icon="egg-outline" title={`ITEM DETAILS (${items.length})`} color={colors.success} />
          <View style={styles.cardBody}>
            {items.map((row, i) => (
              <View key={i} style={i > 0 ? styles.lineDivider : undefined}>
                <View style={styles.lineHead}>
                  <View style={styles.cell}>
                    <FormControl field={ITEM} value={row.item} onChange={onItem(i, "item")} />
                  </View>
                  {items.length > 1 ? (
                    <Pressable
                      style={styles.removeBtn}
                      onPress={() => setItems((cur) => cur.filter((_, j) => j !== i))}
                      accessibilityRole="button" accessibilityLabel="Remove item"
                    >
                      <AppIcon name="trash-can-outline" size={16} color={colors.danger} />
                    </Pressable>
                  ) : null}
                </View>
                <View style={styles.row}>
                  <View style={styles.cell}><FormControl field={SENT_QTY} value={row.sent_qty} onChange={onItem(i, "sent_qty")} /></View>
                  <View style={styles.cell}><FormControl field={RCV_QTY} value={row.rcv_qty} onChange={onItem(i, "rcv_qty")} /></View>
                  <View style={styles.cell}><FormControl field={FREE_QTY} value={row.free_qty} onChange={onItem(i, "free_qty")} /></View>
                </View>
                <View style={styles.row}>
                  <View style={styles.cell}><FormControl field={NO_OF_BOXES} value={row.no_of_boxes} onChange={onItem(i, "no_of_boxes")} /></View>
                  <View style={styles.cell}><FormControl field={RATE} value={row.rate} onChange={onItem(i, "rate")} /></View>
                </View>
                <View style={styles.row}>
                  <View style={styles.cell}><FormControl field={DISC_PCT} value={row.discount_percent} onChange={onItem(i, "discount_percent")} /></View>
                  <View style={styles.cell}><FormControl field={DISC_AMT} value={row.discount_amount} onChange={onItem(i, "discount_amount")} /></View>
                </View>
                <View style={[styles.itemTotal, { backgroundColor: withAlpha(colors.success, 0.1) }]}>
                  <Text style={styles.itemTotalLabel}>Item Total</Text>
                  <Text style={[styles.itemTotalValue, { color: colors.success }]}>{rupees(itemTotal(row))}</Text>
                </View>
              </View>
            ))}
          </View>
          <Pressable style={styles.addRow} onPress={() => setItems((cur) => [...cur, emptyItem()])}>
            <AppIcon name="plus" size={16} color={colors.success} />
            <Text style={[styles.addRowText, { color: colors.success }]}>Add Another Egg Item</Text>
          </Pressable>
        </View>

        <View style={styles.card}>
          <SectionHead icon="truck-fast-outline" title="FREIGHT & TAXES" color={colors.warning} />
          <View style={styles.cardBody}>
            <View style={styles.row}>
              <View style={styles.cell}>
                <FormControl field={FREIGHT_TYPE} value={head.freight_type} onChange={onHead("freight_type")} />
              </View>
              <View style={styles.cell}>
                <Text style={styles.label}>Payment Term</Text>
                <View style={styles.radioRow}>
                  {(["pay_later", "pay_in_bill"] as const).map((mode) => (
                    <Pressable
                      key={mode} style={styles.radioOption}
                      onPress={() => onHead("payment_mode")(mode)}
                      accessibilityRole="radio" accessibilityState={{ checked: head.payment_mode === mode }}
                    >
                      <View style={[styles.radioDot, head.payment_mode === mode && { borderColor: colors.warning }]}>
                        {head.payment_mode === mode ? <View style={[styles.radioDotFill, { backgroundColor: colors.warning }]} /> : null}
                      </View>
                      <Text style={styles.radioLabel}>{mode === "pay_later" ? "Credit" : "Paid"}</Text>
                    </Pressable>
                  ))}
                </View>
              </View>
            </View>
            <View style={styles.row}>
              <View style={styles.cell}><FormControl field={PAY_ACCOUNT} value={head.pay_account} onChange={onHead("pay_account")} /></View>
              <View style={styles.cell}><FormControl field={FREIGHT_ACCOUNT} value={head.freight_account} onChange={onHead("freight_account")} /></View>
            </View>
            <FormControl field={FREIGHT_AMOUNT} value={head.freight_amount} onChange={onHead("freight_amount")} />
            <Pressable
              style={styles.tcsToggle} onPress={() => setTcsApplicable((v) => !v)}
              accessibilityRole="checkbox" accessibilityState={{ checked: tcsApplicable }}
            >
              <View style={[styles.checkbox, tcsApplicable && { backgroundColor: colors.warning, borderColor: colors.warning }]}>
                {tcsApplicable ? <AppIcon name="check" size={14} color="#fff" /> : null}
              </View>
              <Text style={styles.radioLabel}>Enable TCS</Text>
            </Pressable>
            {tcsApplicable ? (
              <FormControl field={TCS_PERCENT} value={head.tcs_percent} onChange={onHead("tcs_percent")} />
            ) : null}
          </View>
        </View>

        <View style={[styles.card, { borderColor: withAlpha(colors.hatchery, 0.3) }]}>
          <SectionHead icon="chart-box-outline" title="BILL SUMMARY" color={colors.hatchery} />
          <View style={styles.cardBody}>
            <View style={styles.billRow}>
              <Text style={styles.billLabel}>Gross Total</Text>
              <Text style={styles.billValue}>{rupees(grossTotal)}</Text>
            </View>
            <View style={styles.billRow}>
              <Text style={styles.billLabel}>
                Freight Charges{freightAmount > 0 ? (freightIncluded ? " (included)" : " (excluded)") : ""}
              </Text>
              <Text style={styles.billValue}>{freightIncluded ? "+ " : ""}{rupees(freightAmount)}</Text>
            </View>
            {tcsApplicable ? (
              <View style={styles.billRow}>
                <Text style={styles.billLabel}>TCS Tax ({head.tcs_percent || "0"}%)</Text>
                <Text style={styles.billValue}>+ {rupees(tcsAmount)}</Text>
              </View>
            ) : null}
            <View style={styles.billRow}>
              <Text style={styles.billLabel}>Net Quantity</Text>
              <Text style={styles.billValue}>{netQuantity.toLocaleString("en-IN")}</Text>
            </View>
            <View style={styles.billRow}>
              <Text style={styles.billLabel}>Net Rate</Text>
              <Text style={styles.billValue}>{rupees(netRate)}</Text>
            </View>
            <View style={[styles.billRow, styles.billTotalRow]}>
              <Text style={styles.billTotalLabel}>Net Payable Amount</Text>
              <Text style={[styles.billTotalValue, { color: colors.hatchery }]}>{rupees(netPayable)}</Text>
            </View>
          </View>
        </View>

        <View style={styles.card}>
          <FormControl field={REMARKS} value={head.remarks} onChange={onHead("remarks")} />
        </View>
      </ScrollView>

      <View style={styles.footer}>
        <Pressable style={[styles.cancel, { borderColor: colors.danger }]} onPress={() => navigation.goBack()}>
          <AppIcon name="close" size={16} color={colors.danger} />
          <Text style={[styles.cancelText, { color: colors.danger }]}>Cancel</Text>
        </Pressable>
        <Pressable style={[styles.submit, { backgroundColor: colors.warning }, saving && { opacity: 0.6 }]}
                   onPress={submit} disabled={saving}>
          <AppIcon name="check" size={16} color="#fff" />
          <Text style={styles.submitText}>{saving ? "Saving…" : "Save Purchase"}</Text>
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
  row: { flexDirection: "row", gap: spacing.sm, alignItems: "flex-start" },
  cell: { flex: 1, minWidth: 0 },
  label: { ...type.caption, color: colors.textMuted, fontWeight: "700" },
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
  radioRow: { flexDirection: "row", gap: spacing.lg, marginTop: spacing.xs, marginBottom: spacing.xs },
  radioOption: { flexDirection: "row", alignItems: "center", gap: spacing.xs },
  radioDot: {
    width: 20, height: 20, borderRadius: 10, borderWidth: 2, borderColor: colors.border,
    alignItems: "center", justifyContent: "center",
  },
  radioDotFill: { width: 10, height: 10, borderRadius: 5 },
  radioLabel: { ...type.body, color: colors.text },
  tcsToggle: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginTop: spacing.xs },
  checkbox: {
    width: 22, height: 22, borderRadius: 5, borderWidth: 2, borderColor: colors.border,
    alignItems: "center", justifyContent: "center",
  },
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
