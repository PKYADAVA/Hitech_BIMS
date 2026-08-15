import { NativeStackScreenProps } from "@react-navigation/native-stack";
import React, { useEffect, useLayoutEffect, useState } from "react";
import { Alert, Pressable, ScrollView, Text, View } from "react-native";

import { farmBatches } from "@/api/lookups";
import { http } from "@/api/client";
import { Envelope } from "@/api/types";
import { CapturePermissionError, capturePhoto, pickDocument, pickPhoto } from "@/capture";
import { AppIcon, IconName } from "@/components/AppIcon";
import { FormControl } from "@/components/form";
import { FormField } from "@/config/forms";
import { ModuleStackParams } from "@/navigation/types";
import { writeThrough } from "@/net/writeThrough";
import { queryClient } from "@/query/queryClient";
import { makeStyles, radius, spacing, type, useTheme, withAlpha } from "@/theme";

type Props = NativeStackScreenProps<ModuleStackParams, "GeneralPurchaseForm">;

/**
 * General Purchase — the document form for a non-egg supplier bill: feed,
 * medicine, consumables. One header over several item lines, each landing on
 * either a warehouse or straight onto a farm (+ the flock it's for), plus
 * freight, TDS, bag/batch tracking and up to three reference-document scans.
 *
 * Posts multipart to purchase/general-purchases/save, which runs the web
 * form's own posting helpers (purchase.views._apply_posted_general_purchase_fields
 * / _save_general_purchase_items via purchase/api_write.py) — so a phone save
 * is held to the same validation and net-amount arithmetic as a browser save.
 * The simpler generic Document Form still exists for this resource but has no
 * layout for the destination toggle, TDS, bag/batch or attachments this needs.
 */

interface Option { value: string; label: string }

const PURCHASE_NO: FormField = {
  name: "purchase_no", label: "Purchase No.", type: "text", readOnly: true,
  placeholder: "Assigned on save",
};
const DATE: FormField = { name: "date", label: "Date", type: "date", required: true };
const SUPPLIER: FormField = {
  name: "supplier", label: "Supplier", type: "select", required: true,
  optionsPath: "/suppliers/", optionLabelKeys: ["name", "code"], placeholder: "Select Supplier",
};
const BILL_NO: FormField = { name: "bill_no", label: "Bill No.", type: "text" };
const DC_NO: FormField = { name: "dc_no", label: "DC No.", type: "text" };
const VEHICLE_NO: FormField = { name: "vehicle_no", label: "Vehicle No.", type: "text", placeholder: "e.g. UP53AB1234" };
const DRIVER_NAME: FormField = { name: "driver_name", label: "Driver Name", type: "text" };
const DRIVER_MOBILE: FormField = { name: "driver_mobile", label: "Driver Mobile", type: "text" };
const CALCULATION_BASED_ON: FormField = {
  name: "calculation_based_on", label: "Calculate On", type: "select",
  options: [
    { value: "Sent Quantity", label: "Sent Quantity" },
    { value: "Received Quantity", label: "Received Quantity" },
  ],
};
const PAYMENT_TERMS: FormField = {
  name: "payment_terms", label: "Payment Terms", type: "select",
  options: [
    { value: "Cash", label: "Cash" }, { value: "Credit", label: "Credit" },
    { value: "Cheque", label: "Cheque" }, { value: "Bank Transfer", label: "Bank Transfer" },
  ],
};

const ITEM: FormField = {
  name: "item", label: "Item", type: "select", required: true,
  optionsPath: "/items/", optionLabelKeys: ["description", "item_code"],
};
const UNIT: FormField = { name: "unit", label: "Unit", type: "text", placeholder: "e.g. Kg, Bag" };
const WAREHOUSE: FormField = {
  name: "warehouse", label: "Warehouse", type: "select", required: true,
  optionsPath: "/warehouses/", optionLabelKeys: ["name", "code"], placeholder: "Select Warehouse",
};
const FARM: FormField = {
  name: "farm", label: "Farm", type: "select", required: true,
  optionsPath: "/broiler/farms/", optionLabelKeys: ["farm_name", "farm_code"], placeholder: "Select Farm",
};
const batchField = (options: Option[]): FormField => ({
  name: "batch", label: "Batch", type: "select", options,
  placeholder: options.length ? "Select Batch" : "Select a farm first",
});
const SENT_QTY: FormField = { name: "sent_qty", label: "Sent Qty", type: "decimal" };
const RCV_QTY: FormField = { name: "rcv_qty", label: "Rcv Qty", type: "decimal" };
const FREE_QTY: FormField = { name: "free_qty", label: "Free Qty", type: "decimal" };
const RATE: FormField = { name: "rate", label: "Rate (₹)", type: "decimal", required: true };
const DISC_PCT: FormField = { name: "discount_percent", label: "Disc %", type: "decimal" };
const DISC_AMT: FormField = { name: "discount_amount", label: "Disc (₹)", type: "decimal" };
const GST_PCT: FormField = { name: "gst_percent", label: "GST %", type: "decimal" };

// The values the server stores. "Extra" and "Included in Bill" were retired —
// they read as the opposite of what they did, and freight already inside a
// supplier's price was being added to the bill a second time.
const FREIGHT_TYPE: FormField = {
  name: "freight_type", label: "Freight Type", type: "select",
  options: [
    { value: "No Freight", label: "No Freight" },
    { value: "Freight Included", label: "Freight Included" },
    { value: "Freight Extra", label: "Freight Extra" },
  ],
};
const FREIGHT_SETTLEMENT: FormField = {
  name: "freight_settlement", label: "Freight Settlement", type: "select",
  options: [
    { value: "In Purchase Bill", label: "Included in Purchase Bill" },
    { value: "Separate Bill", label: "Separate Freight Bill" },
  ],
};
const FREIGHT_TRANSPORTER: FormField = {
  name: "freight_transporter", label: "Transporter", type: "text",
};
const FREIGHT_AMOUNT: FormField = { name: "freight_amount", label: "Freight Amount (₹)", type: "decimal" };
const PAY_ACCOUNT: FormField = {
  name: "pay_account", label: "Pay Account", type: "select",
  optionsPath: "/account/chart-of-accounts/", optionLabelKeys: ["description", "code"],
};
const FREIGHT_ACCOUNT: FormField = {
  name: "freight_account", label: "Freight Account", type: "select",
  optionsPath: "/account/chart-of-accounts/", optionLabelKeys: ["description", "code"],
};

const BAG_TYPE: FormField = {
  name: "bag_type", label: "Bag Type", type: "select",
  options: [
    { value: "Jute Bag", label: "Jute Bag" }, { value: "HDPE Bag", label: "HDPE Bag" },
    { value: "Loose", label: "Loose" },
  ],
};
const NO_OF_BAGS: FormField = { name: "no_of_bags", label: "No. of Bags", type: "decimal" };
const BATCH_NO: FormField = { name: "batch_no", label: "Batch No. (Reference)", type: "text" };
const EXPIRY_DATE: FormField = { name: "expiry_date", label: "Expiry Date", type: "date" };
const TDS_CODE: FormField = { name: "tds_code", label: "TDS Code", type: "text" };
const TDS_AMOUNT: FormField = { name: "tds_amount", label: "TDS Amount (₹)", type: "decimal" };

const OTHER_CHARGES_ACCOUNT: FormField = {
  name: "other_charges_account", label: "Other Charges Account", type: "select",
  optionsPath: "/account/chart-of-accounts/", optionLabelKeys: ["description", "code"],
};
const OTHER_CHARGES_AMOUNT: FormField = { name: "other_charges_amount", label: "Other Charges Amount (₹)", type: "decimal" };

const REMARKS: FormField = { name: "remarks", label: "Remarks", type: "textarea" };

const REF_DOC_SLOTS = [
  { key: "reference_document_1", label: "Reference Document 1" },
  { key: "reference_document_2", label: "Reference Document 2" },
  { key: "reference_document_3", label: "Reference Document 3" },
] as const;

interface ItemRow {
  item: string; unit: string;
  destinationType: "warehouse" | "farm"; destinationId: string; batch: string;
  sent_qty: string; rcv_qty: string; free_qty: string;
  rate: string; discount_percent: string; discount_amount: string; gst_percent: string;
}
const emptyItem = (): ItemRow => ({
  item: "", unit: "", destinationType: "warehouse", destinationId: "", batch: "",
  sent_qty: "", rcv_qty: "", free_qty: "",
  rate: "", discount_percent: "", discount_amount: "", gst_percent: "",
});

/** Mirrors purchase.GeneralPurchaseItem.save(): the effective quantity is
 *  Sent or Received depending on the *header's* calculation basis, not a
 *  per-row choice, then discount and GST are applied in that order. */
const itemTotal = (row: ItemRow, calcBasis: string): number => {
  const qty = calcBasis === "Received Quantity" ? Number(row.rcv_qty) || 0 : Number(row.sent_qty) || 0;
  const subtotal = qty * (Number(row.rate) || 0) * (1 - (Number(row.discount_percent) || 0) / 100)
    - (Number(row.discount_amount) || 0);
  return subtotal * (1 + (Number(row.gst_percent) || 0) / 100);
};

const today = () => new Date().toISOString().slice(0, 10);
const rupees = (n: number) =>
  `₹ ${n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const isLocalUri = (uri: string) => !!uri && !/^https?:\/\//i.test(uri);

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

export function GeneralPurchaseFormScreen({ navigation, route }: Props) {
  const styles = useStyles();
  const { colors } = useTheme();
  /** The saved purchase being corrected, or null when recording a new one. */
  const editing = route.params?.row ?? null;

  const [head, setHead] = useState<Record<string, string>>({
    purchase_no: (editing as { purchase_no?: string })?.purchase_no ?? "",
    date: today(), supplier: "", bill_no: "", dc_no: "",
    vehicle_no: "", driver_name: "", driver_mobile: "",
    calculation_based_on: "Received Quantity", payment_terms: "Cash",
    freight_type: "No Freight", freight_settlement: "In Purchase Bill",
    freight_transporter: "", freight_amount: "", payment_mode: "pay_later",
    pay_account: "", freight_account: "",
    bag_type: "", no_of_bags: "", batch_no: "", expiry_date: "",
    tds_code: "", tds_amount: "",
    other_charges_account: "", other_charges_type: "Add", other_charges_amount: "",
    remarks: "",
  });
  const [tdsApplicable, setTdsApplicable] = useState(false);
  const [items, setItems] = useState<ItemRow[]>([emptyItem()]);
  const [refDocs, setRefDocs] = useState<string[]>(["", "", ""]);
  const [batchOptionsByFarm, setBatchOptionsByFarm] = useState<Record<string, Option[]>>({});
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(!!editing);
  const [error, setError] = useState<string | null>(null);

  useLayoutEffect(() => {
    navigation.setOptions({ title: editing ? "Edit General Purchase" : "Add General Purchase" });
  }, [navigation, editing]);

  // An existing purchase is loaded fresh rather than trusting the list row —
  // the list's own row is a summary, not the full item rows this form needs.
  useEffect(() => {
    if (!editing) return;
    (async () => {
      try {
        const { data } = await http.get<Envelope<Record<string, unknown>>>(
          `/purchase/general-purchases/save/${editing.id}`);
        const d = data.data as { header: Record<string, any>; items: Record<string, any>[] };
        const h = d.header;
        setHead({
          purchase_no: h.purchase_no ?? "", date: h.date ?? today(), supplier: h.supplier ?? "",
          bill_no: h.bill_no ?? "", dc_no: h.dc_no ?? "",
          vehicle_no: h.vehicle_no ?? "", driver_name: h.driver_name ?? "", driver_mobile: h.driver_mobile ?? "",
          calculation_based_on: h.calculation_based_on ?? "Received Quantity",
          payment_terms: h.payment_terms ?? "Cash",
          freight_type: h.freight_type ?? "No Freight",
          freight_settlement: h.freight_settlement ?? "In Purchase Bill",
          freight_transporter: h.freight_transporter ?? "",
          freight_amount: h.freight_amount ?? "",
          payment_mode: h.payment_mode ?? "pay_later",
          pay_account: h.pay_account ?? "", freight_account: h.freight_account ?? "",
          bag_type: h.bag_type ?? "", no_of_bags: h.no_of_bags ?? "",
          batch_no: h.batch_no ?? "", expiry_date: h.expiry_date ?? "",
          tds_code: h.tds_code ?? "", tds_amount: h.tds_amount ?? "",
          other_charges_account: h.other_charges_account ?? "",
          other_charges_type: h.other_charges_type ?? "Add",
          other_charges_amount: h.other_charges_amount ?? "",
          remarks: h.remarks ?? "",
        });
        setTdsApplicable(!!h.tds_applicable);
        setRefDocs([h.reference_document_1 ?? "", h.reference_document_2 ?? "", h.reference_document_3 ?? ""]);
        const rows = (d.items ?? []).map((it) => {
          const [kind, id] = String(it.destination ?? "").split(":");
          return {
            item: it.item ?? "", unit: it.unit ?? "",
            destinationType: kind === "farm" ? "farm" as const : "warehouse" as const,
            destinationId: id ?? "", batch: it.batch ?? "",
            sent_qty: it.sent_qty ?? "", rcv_qty: it.rcv_qty ?? "", free_qty: it.free_qty ?? "",
            rate: it.rate ?? "", discount_percent: it.discount_percent ?? "",
            discount_amount: it.discount_amount ?? "", gst_percent: it.gst_percent ?? "",
          };
        });
        setItems(rows.length ? rows : [emptyItem()]);
        for (const row of rows) {
          if (row.destinationType === "farm" && row.destinationId) void loadBatches(row.destinationId);
        }
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

  const loadBatches = async (farmId: string) => {
    if (!farmId || batchOptionsByFarm[farmId]) return;
    try {
      const rows = await farmBatches(farmId);
      setBatchOptionsByFarm((cur) => ({
        ...cur,
        [farmId]: rows.map((b) => ({
          value: String(b.id), label: b.is_active ? `${b.batch_name} (Active)` : b.batch_name,
        })),
      }));
    } catch { /* advisory — the picker just stays empty */ }
  };

  const onDestinationType = (index: number, kind: "warehouse" | "farm") =>
    setItems((cur) => cur.map((row, i) => (i === index
      ? { ...row, destinationType: kind, destinationId: "", batch: "" } : row)));
  const onDestinationId = (index: number) => (value: string) => {
    setItems((cur) => cur.map((row, i) => (i === index ? { ...row, destinationId: value, batch: "" } : row)));
    if (items[index]?.destinationType === "farm") void loadBatches(value);
  };

  const attachRefDoc = (index: number) => {
    const take = async (source: () => Promise<{ uri: string } | null>) => {
      try {
        const picked = await source();
        if (picked) setRefDocs((cur) => cur.map((u, i) => (i === index ? picked.uri : u)));
      } catch (e) {
        Alert.alert(
          e instanceof CapturePermissionError ? "Permission needed" : "Could not attach that",
          (e as Error)?.message ?? "Please try again.",
        );
      }
    };
    Alert.alert("Attach Document", "Where is this coming from?", [
      { text: "Take a photo", onPress: () => take(capturePhoto) },
      { text: "Photo gallery", onPress: () => take(pickPhoto) },
      { text: "File (PDF, doc)", onPress: () => take(pickDocument) },
      { text: "Cancel", style: "cancel" },
    ]);
  };
  const removeRefDoc = (index: number) => setRefDocs((cur) => cur.map((u, i) => (i === index ? "" : u)));

  // --- Bill Summary — mirrors purchase.GeneralPurchase.gross_amount /
  // freight_included_amount / other_charges_signed / compute_net_amount
  // exactly: freight only enters the payable total when Freight Type is
  // its own bill, other charges add or deduct per their own toggle, and
  // the round-off is whatever nudges the pre-round total to the nearest whole
  // rupee — never user-entered.
  const grossTotal = items.reduce((sum, row) => sum + itemTotal(row, head.calculation_based_on), 0);
  // Only freight that lands on this supplier's own bill: charged on top, and
  // not left to a transporter who invoices separately. The old rule added it
  // when the type said the carriage was already inside the price, which billed
  // it twice.
  const freightOnThisBill = head.freight_type === "Freight Extra"
    && head.freight_settlement !== "Separate Bill";
  const freightAmount = Number(head.freight_amount) || 0;
  const freightBase = grossTotal + (freightOnThisBill ? freightAmount : 0);
  const otherChargesAmount = Number(head.other_charges_amount) || 0;
  const otherChargesSigned = head.other_charges_type === "Deduct" ? -otherChargesAmount : otherChargesAmount;
  const tdsAmount = tdsApplicable ? Number(head.tds_amount) || 0 : 0;
  const preRound = freightBase + otherChargesSigned - tdsAmount;
  const netAmount = Math.round(preRound);
  const roundOff = netAmount - preRound;

  const submit = async () => {
    setError(null);
    if (!head.supplier) return setError("Supplier is required.");
    if (!head.date) return setError("Date is required.");
    const filled = items.filter((row) => row.item && row.rate && row.destinationId);
    if (!filled.length) return setError("Add at least one item with a rate and a destination.");

    setSaving(true);
    try {
      const fields: Record<string, unknown> = {
        ...head,
        tds_applicable: tdsApplicable ? "on" : "",
        items: JSON.stringify(filled.map((row) => ({
          item: row.item, unit: row.unit || "",
          destination: `${row.destinationType}:${row.destinationId}`,
          batch: row.destinationType === "farm" ? row.batch || "" : "",
          sent_qty: row.sent_qty || "0", rcv_qty: row.rcv_qty || "0", free_qty: row.free_qty || "0",
          rate: row.rate, discount_percent: row.discount_percent || "0",
          discount_amount: row.discount_amount || "0", gst_percent: row.gst_percent || "0",
        }))),
      };
      // Nothing lost by re-sending nothing: an unchanged slot already holds a
      // saved URL, and only a freshly-picked local file needs to go back out.
      const files = REF_DOC_SLOTS
        .map((slot, i) => ({ field: slot.key, uri: refDocs[i] }))
        .filter((f) => isLocalUri(f.uri));

      const url = editing
        ? `/purchase/general-purchases/save/${editing.id}`
        : "/purchase/general-purchases/save";
      await writeThrough({
        type: "general_purchase", label: "General Purchase",
        method: "POST", path: url,
        body: { fields, files },
      });
      queryClient.invalidateQueries({ queryKey: ["list", "/purchase/general-purchases/"] });
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
          <SectionHead icon="truck-outline" title="PURCHASE DETAILS" color={colors.tint} />
          <View style={styles.cardBody}>
            <View style={styles.row}>
              <View style={styles.cell}><FormControl field={DATE} value={head.date} onChange={onHead("date")} /></View>
              <View style={styles.cell}><FormControl field={SUPPLIER} value={head.supplier} onChange={onHead("supplier")} /></View>
            </View>
            <View style={styles.row}>
              <View style={styles.cell}><FormControl field={PURCHASE_NO} value={head.purchase_no} onChange={onHead("purchase_no")} /></View>
              <View style={styles.cell}><FormControl field={BILL_NO} value={head.bill_no} onChange={onHead("bill_no")} /></View>
            </View>
            <View style={styles.row}>
              <View style={styles.cell}><FormControl field={DC_NO} value={head.dc_no} onChange={onHead("dc_no")} /></View>
              <View style={styles.cell}><FormControl field={VEHICLE_NO} value={head.vehicle_no} onChange={onHead("vehicle_no")} /></View>
            </View>
            <View style={styles.row}>
              <View style={styles.cell}><FormControl field={DRIVER_NAME} value={head.driver_name} onChange={onHead("driver_name")} /></View>
              <View style={styles.cell}><FormControl field={DRIVER_MOBILE} value={head.driver_mobile} onChange={onHead("driver_mobile")} /></View>
            </View>
            <View style={styles.row}>
              <View style={styles.cell}><FormControl field={CALCULATION_BASED_ON} value={head.calculation_based_on} onChange={onHead("calculation_based_on")} /></View>
              <View style={styles.cell}><FormControl field={PAYMENT_TERMS} value={head.payment_terms} onChange={onHead("payment_terms")} /></View>
            </View>
          </View>
        </View>

        <View style={styles.card}>
          <SectionHead icon="cart-outline" title={`PURCHASE ITEMS (${items.length})`} color={colors.success} />
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
                <FormControl field={UNIT} value={row.unit} onChange={onItem(i, "unit")} />

                <Text style={styles.label}>Destination</Text>
                <View style={styles.radioRow}>
                  {(["warehouse", "farm"] as const).map((kind) => (
                    <Pressable
                      key={kind} style={styles.radioOption}
                      onPress={() => onDestinationType(i, kind)}
                      accessibilityRole="radio" accessibilityState={{ checked: row.destinationType === kind }}
                    >
                      <View style={[styles.radioDot, row.destinationType === kind && { borderColor: colors.success }]}>
                        {row.destinationType === kind
                          ? <View style={[styles.radioDotFill, { backgroundColor: colors.success }]} /> : null}
                      </View>
                      <Text style={styles.radioLabel}>{kind === "warehouse" ? "Warehouse" : "Farm"}</Text>
                    </Pressable>
                  ))}
                </View>
                {row.destinationType === "warehouse" ? (
                  <FormControl field={WAREHOUSE} value={row.destinationId} onChange={onDestinationId(i)} />
                ) : (
                  <View style={styles.row}>
                    <View style={styles.cell}>
                      <FormControl field={FARM} value={row.destinationId} onChange={onDestinationId(i)} />
                    </View>
                    <View style={styles.cell}>
                      <FormControl
                        field={batchField(batchOptionsByFarm[row.destinationId] || [])}
                        value={row.batch} onChange={onItem(i, "batch")}
                      />
                    </View>
                  </View>
                )}

                <View style={styles.row}>
                  <View style={styles.cell}><FormControl field={SENT_QTY} value={row.sent_qty} onChange={onItem(i, "sent_qty")} /></View>
                  <View style={styles.cell}><FormControl field={RCV_QTY} value={row.rcv_qty} onChange={onItem(i, "rcv_qty")} /></View>
                  <View style={styles.cell}><FormControl field={FREE_QTY} value={row.free_qty} onChange={onItem(i, "free_qty")} /></View>
                </View>
                <View style={styles.row}>
                  <View style={styles.cell}><FormControl field={RATE} value={row.rate} onChange={onItem(i, "rate")} /></View>
                  <View style={styles.cell}><FormControl field={GST_PCT} value={row.gst_percent} onChange={onItem(i, "gst_percent")} /></View>
                </View>
                <View style={styles.row}>
                  <View style={styles.cell}><FormControl field={DISC_PCT} value={row.discount_percent} onChange={onItem(i, "discount_percent")} /></View>
                  <View style={styles.cell}><FormControl field={DISC_AMT} value={row.discount_amount} onChange={onItem(i, "discount_amount")} /></View>
                </View>
                <View style={[styles.itemTotal, { backgroundColor: withAlpha(colors.success, 0.1) }]}>
                  <Text style={styles.itemTotalLabel}>Item Total</Text>
                  <Text style={[styles.itemTotalValue, { color: colors.success }]}>
                    {rupees(itemTotal(row, head.calculation_based_on))}
                  </Text>
                </View>
              </View>
            ))}
          </View>
          <Pressable style={styles.addRow} onPress={() => setItems((cur) => [...cur, emptyItem()])}>
            <AppIcon name="plus" size={16} color={colors.success} />
            <Text style={[styles.addRowText, { color: colors.success }]}>Add Another Item</Text>
          </Pressable>
        </View>

        <View style={styles.card}>
          <SectionHead icon="truck-fast-outline" title="FREIGHT & PAYMENT" color={colors.warning} />
          <View style={styles.cardBody}>
            <View style={styles.row}>
              <View style={styles.cell}>
                <FormControl field={FREIGHT_TYPE} value={head.freight_type} onChange={onHead("freight_type")} />
              </View>
              <View style={styles.cell}>
                <FormControl field={FREIGHT_AMOUNT} value={head.freight_amount}
                             onChange={onHead("freight_amount")} />
              </View>
            </View>
            {/* Settlement is only a question for freight charged on top, and a
                transporter only exists when that freight is billed separately.
                The server forces both back for the other types, so a phone
                that never shows them cannot post a contradiction. */}
            {head.freight_type === "Freight Extra" ? (
              <View style={styles.row}>
                <View style={styles.cell}>
                  <FormControl field={FREIGHT_SETTLEMENT} value={head.freight_settlement}
                               onChange={onHead("freight_settlement")} />
                </View>
                <View style={styles.cell}>
                  {head.freight_settlement === "Separate Bill" ? (
                    <FormControl field={FREIGHT_TRANSPORTER} value={head.freight_transporter}
                                 onChange={onHead("freight_transporter")} />
                  ) : null}
                </View>
              </View>
            ) : null}
            <Text style={styles.label}>Payment Status</Text>
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
            <View style={styles.row}>
              <View style={styles.cell}><FormControl field={PAY_ACCOUNT} value={head.pay_account} onChange={onHead("pay_account")} /></View>
              <View style={styles.cell}><FormControl field={FREIGHT_ACCOUNT} value={head.freight_account} onChange={onHead("freight_account")} /></View>
            </View>
          </View>
        </View>

        <View style={styles.card}>
          <SectionHead icon="package-variant-closed" title="BAG & BATCH / TDS DETAILS" color={colors.info} />
          <View style={styles.cardBody}>
            <View style={styles.row}>
              <View style={styles.cell}><FormControl field={BAG_TYPE} value={head.bag_type} onChange={onHead("bag_type")} /></View>
              <View style={styles.cell}><FormControl field={NO_OF_BAGS} value={head.no_of_bags} onChange={onHead("no_of_bags")} /></View>
            </View>
            <View style={styles.row}>
              <View style={styles.cell}><FormControl field={BATCH_NO} value={head.batch_no} onChange={onHead("batch_no")} /></View>
              <View style={styles.cell}><FormControl field={EXPIRY_DATE} value={head.expiry_date} onChange={onHead("expiry_date")} /></View>
            </View>
            <FormControl field={TDS_CODE} value={head.tds_code} onChange={onHead("tds_code")} />
            <Pressable
              style={styles.tdsToggle} onPress={() => setTdsApplicable((v) => !v)}
              accessibilityRole="checkbox" accessibilityState={{ checked: tdsApplicable }}
            >
              <View style={[styles.checkbox, tdsApplicable && { backgroundColor: colors.info, borderColor: colors.info }]}>
                {tdsApplicable ? <AppIcon name="check" size={14} color="#fff" /> : null}
              </View>
              <Text style={styles.radioLabel}>TDS Applicable</Text>
            </Pressable>
            {tdsApplicable ? (
              <FormControl field={TDS_AMOUNT} value={head.tds_amount} onChange={onHead("tds_amount")} />
            ) : null}
          </View>
        </View>

        <View style={[styles.card, { borderColor: withAlpha(colors.purchase, 0.3) }]}>
          <SectionHead icon="chart-box-outline" title="OTHER CHARGES & SUMMARY" color={colors.purchase} />
          <View style={styles.cardBody}>
            <View style={styles.row}>
              <View style={styles.cell}><FormControl field={OTHER_CHARGES_ACCOUNT} value={head.other_charges_account} onChange={onHead("other_charges_account")} /></View>
              <View style={styles.cell}><FormControl field={OTHER_CHARGES_AMOUNT} value={head.other_charges_amount} onChange={onHead("other_charges_amount")} /></View>
            </View>
            <Text style={styles.label}>Other Charges Type</Text>
            <View style={styles.radioRow}>
              {(["Add", "Deduct"] as const).map((t) => (
                <Pressable
                  key={t} style={styles.radioOption}
                  onPress={() => onHead("other_charges_type")(t)}
                  accessibilityRole="radio" accessibilityState={{ checked: head.other_charges_type === t }}
                >
                  <View style={[styles.radioDot, head.other_charges_type === t && { borderColor: colors.tint }]}>
                    {head.other_charges_type === t ? <View style={[styles.radioDotFill, { backgroundColor: colors.tint }]} /> : null}
                  </View>
                  <Text style={styles.radioLabel}>{t}</Text>
                </Pressable>
              ))}
            </View>

            <View style={styles.billDivider} />
            <View style={styles.billRow}>
              <Text style={styles.billLabel}>Gross Total</Text>
              <Text style={styles.billValue}>{rupees(grossTotal)}</Text>
            </View>
            <View style={styles.billRow}>
              {/* Say which of the three situations the figure is in, rather
                  than "included"/"excluded", which read as the opposite of
                  what they meant. */}
              <Text style={styles.billLabel}>
                Freight Charges{freightAmount > 0
                  ? freightOnThisBill ? " (on this bill)"
                    : head.freight_settlement === "Separate Bill" ? " (transporter bills)"
                      : " (in the price)"
                  : ""}
              </Text>
              <Text style={styles.billValue}>{freightOnThisBill ? "+ " : ""}{rupees(freightAmount)}</Text>
            </View>
            {otherChargesAmount > 0 ? (
              <View style={styles.billRow}>
                <Text style={styles.billLabel}>Other Charges ({head.other_charges_type})</Text>
                <Text style={styles.billValue}>{otherChargesSigned >= 0 ? "+ " : "− "}{rupees(Math.abs(otherChargesSigned))}</Text>
              </View>
            ) : null}
            {tdsApplicable ? (
              <View style={styles.billRow}>
                <Text style={styles.billLabel}>TDS</Text>
                <Text style={styles.billValue}>− {rupees(tdsAmount)}</Text>
              </View>
            ) : null}
            <View style={styles.billRow}>
              <Text style={styles.billLabel}>Round Off</Text>
              <Text style={styles.billValue}>{roundOff >= 0 ? "+ " : "− "}{rupees(Math.abs(roundOff))}</Text>
            </View>
            <View style={[styles.billRow, styles.billTotalRow]}>
              <Text style={styles.billTotalLabel}>Net Payable Amount</Text>
              <Text style={[styles.billTotalValue, { color: colors.tint }]}>{rupees(netAmount)}</Text>
            </View>
          </View>
        </View>

        <View style={styles.card}>
          <SectionHead icon="paperclip" title="REMARKS & ATTACHMENTS" color={colors.textMuted} />
          <View style={styles.cardBody}>
            <FormControl field={REMARKS} value={head.remarks} onChange={onHead("remarks")} />
            <Text style={styles.label}>Reference Documents (Up to 3)</Text>
            {REF_DOC_SLOTS.map((slot, i) => {
              const filled = !!refDocs[i];
              return (
                <View key={slot.key} style={styles.slotRow}>
                  <AppIcon name={filled ? "check-circle" : "file-document-outline"} size={16}
                           color={filled ? colors.success : colors.textMuted} />
                  <Text style={styles.slotLabel} numberOfLines={1}>{slot.label}</Text>
                  {filled ? (
                    <Pressable onPress={() => removeRefDoc(i)}>
                      <Text style={[styles.slotButtonText, { color: colors.danger }]}>Remove</Text>
                    </Pressable>
                  ) : null}
                  <Pressable
                    style={[styles.slotButton, filled && { borderColor: colors.success }]}
                    onPress={() => attachRefDoc(i)}>
                    <Text style={[styles.slotButtonText, { color: filled ? colors.success : colors.tint }]}>
                      {filled ? "Replace" : "Upload"}
                    </Text>
                  </Pressable>
                </View>
              );
            })}
          </View>
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
  tdsToggle: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginTop: spacing.xs },
  checkbox: {
    width: 22, height: 22, borderRadius: 5, borderWidth: 2, borderColor: colors.border,
    alignItems: "center", justifyContent: "center",
  },
  billDivider: { borderTopWidth: 1, borderTopColor: colors.border, marginTop: spacing.xs },
  billRow: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 4 },
  billLabel: { ...type.body, color: colors.textMuted },
  billValue: { ...type.body, color: colors.text, fontWeight: "600" },
  billTotalRow: { borderTopWidth: 1, borderTopColor: colors.border, marginTop: spacing.xs, paddingTop: spacing.sm },
  billTotalLabel: { ...type.title, fontWeight: "800" },
  billTotalValue: { ...type.h3, fontWeight: "800" },
  slotRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingVertical: 6 },
  slotLabel: { ...type.body, color: colors.text, flex: 1 },
  slotButton: { borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm, paddingHorizontal: spacing.sm, paddingVertical: 4 },
  slotButtonText: { ...type.caption, fontWeight: "700" },
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