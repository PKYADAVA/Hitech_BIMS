import { NativeStackScreenProps } from "@react-navigation/native-stack";
import React, { useLayoutEffect, useMemo, useState } from "react";
import { Alert, Pressable, ScrollView, Text, View } from "react-native";

import { http } from "@/api/client";
import { Envelope, Row } from "@/api/types";
import { AppIcon } from "@/components/AppIcon";
import { FormControl } from "@/components/form";
import { FormField } from "@/config/forms";
import { ModuleStackParams } from "@/navigation/types";
import { queryClient } from "@/query/queryClient";
import { makeStyles, radius, spacing, type, useTheme } from "@/theme";

type Props = NativeStackScreenProps<ModuleStackParams, "BirdSaleReceiptForm">;

/**
 * Bird Receipt — money in against bird sales.
 *
 * A document, not a row: one date, one location and one source (customer or
 * farmer) over however many payments were taken, which is the shape the ERP
 * form has and the shape its API already accepts (`{rows: [...]}`). Collecting
 * three cheques on one visit used to mean saving and starting again twice.
 *
 * Two rules come from the server rather than being restated here: the ledger
 * balance (a customer receipt shows the whole customer ledger, a farmer receipt
 * the cost-centre balance) and which Code each payment Mode allows.
 */

interface Option { value: string; label: string }

const DATE: FormField = { name: "date", label: "Date", type: "date", required: true };
const REF: FormField = { name: "reference_no", label: "Reference No.", type: "text" };
const REMARKS: FormField = { name: "remarks", label: "Remarks", type: "textarea" };
const AMOUNT: FormField = {
  name: "amount", label: "Amount", type: "decimal", required: true,
};
const BALANCE: FormField = {
  name: "balance", label: "Ledger Balance", type: "text", readOnly: true,
  placeholder: "₹ 0.00",
};

const locationField = (options: Option[]): FormField => ({
  name: "location", label: "Location", type: "select", required: true, options,
});
const partyField = (options: Option[], forFarmer: boolean): FormField => ({
  name: "party", label: "Customer / Farmer", type: "select", required: true, options,
  placeholder: `Select ${forFarmer ? "Farmer" : "Customer"}`,
});
const modeField = (options: Option[]): FormField => ({
  name: "mode", label: "Mode", type: "select", required: true, options,
});
const codeField = (options: Option[], modeChosen: boolean): FormField => ({
  name: "receipt_account", label: "Code", type: "select", required: true, options,
  placeholder: !modeChosen
    ? "Pick a mode first"
    : options.length ? "Select Code" : "No code mapped to that mode",
});

const REMARKS_MAX = 200;
const today = () => new Date().toISOString().slice(0, 10);

/** One payment on the receipt. */
interface Entry {
  party: string;
  balance: string;
  mode: string;
  receipt_account: string;
  amount: string;
  reference_no: string;
  remarks: string;
}

const emptyEntry = (): Entry => ({
  party: "", balance: "", mode: "", receipt_account: "",
  amount: "", reference_no: "", remarks: "",
});

interface Lookup {
  balance: string;
  modes: string[];
  mode_codes: Record<string, number[]>;
  accounts: { id: number; label: string }[];
}

export function BirdSaleReceiptFormScreen({ navigation, route }: Props) {
  const styles = useStyles();
  const { colors } = useTheme();
  const mode = route.params?.mode ?? "create";
  const existing = route.params?.row ?? null;

  const [head, setHead] = useState<Record<string, string>>({
    date: today(), location: "", sale_type: "customer",
  });
  const [entries, setEntries] = useState<Entry[]>([emptyEntry()]);
  const [locations, setLocations] = useState<Option[]>([]);
  const [customers, setCustomers] = useState<Option[]>([]);
  const [farmers, setFarmers] = useState<Option[]>([]);
  const [lookup, setLookup] = useState<Lookup | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const forFarmer = head.sale_type === "farmer";

  useLayoutEffect(() => {
    navigation.setOptions({
      title: mode === "create" ? "Add Bird Receipt" : "Edit Bird Receipt",
    });
  }, [navigation, mode]);

  React.useEffect(() => {
    loadPickers();
    if (!existing) return;
    const str = (v: unknown) => (v == null ? "" : String(v));
    setHead({
      date: str(existing.date) || today(),
      location: str(existing.location),
      sale_type: str(existing.sale_type) || "customer",
    });
    setEntries([{
      party: str(existing.customer) || str(existing.farmer),
      balance: "",
      mode: str(existing.mode),
      receipt_account: str(existing.receipt_account),
      amount: str(existing.amount),
      reference_no: str(existing.reference_no),
      remarks: str(existing.remarks),
    }]);
  }, []);

  const loadPickers = async () => {
    const pull = async (path: string, label: (r: Row) => string) => {
      try {
        const { data } = await http.get<Envelope<Row[]>>(path, { params: { page_size: 500 } });
        return data.data.map((r) => ({ value: String(r.id), label: label(r) }));
      } catch {
        return [];
      }
    };
    setLocations(await pull("/warehouses/",
      (r) => String(r.name || r.code || `#${r.id}`)));
    setCustomers(await pull("/customers/", (r) => String(r.name || `#${r.id}`)));
    setFarmers(await pull("/broiler/farmers/", (r) => String(r.farmer_name || `#${r.id}`)));
    try {
      const { data } = await http.get<Envelope<Lookup>>("/broiler/receipt-lookup");
      setLookup(data.data);
    } catch {
      /* pickers fall back to empty; the server still validates on save */
    }
  };

  const modeOptions = useMemo<Option[]>(
    () => (lookup?.modes ?? []).map((m) => ({ value: m, label: m })), [lookup]);

  /** Codes allowed for a mode. An unmapped mode offers every Bank/Cash code. */
  const codesFor = (chosen: string): Option[] => {
    if (!lookup) return [];
    const mapped = lookup.mode_codes?.[chosen] ?? [];
    const all = lookup.accounts.map((a) => ({ value: String(a.id), label: a.label }));
    return mapped.length ? all.filter((a) => mapped.includes(Number(a.value))) : all;
  };

  const onHead = (name: string) => async (value: string) => {
    const next = { ...head, [name]: value };
    if (name === "sale_type") {
      // Switching source changes who the parties are, so a party picked under
      // the old one cannot survive it.
      setEntries((cur) => cur.map((e) => ({ ...e, party: "", balance: "" })));
    }
    setHead(next);
    if (name === "location") entries.forEach((_, i) => refreshBalance(i, next));
  };

  const setEntry = (index: number, key: keyof Entry, value: string) =>
    setEntries((cur) => cur.map((e, i) => (i === index ? { ...e, [key]: value } : e)));

  /** The outstanding balance for this party, as the server computes it. */
  const refreshBalance = async (index: number, h = head) => {
    const entry = entries[index];
    if (!entry?.party) return;
    try {
      const { data } = await http.get<Envelope<Lookup>>("/broiler/receipt-lookup", {
        params: {
          location: h.location, sale_type: h.sale_type,
          [h.sale_type === "farmer" ? "farmer" : "customer"]: entry.party,
        },
      });
      setEntry(index, "balance", data.data.balance ?? "0");
    } catch {
      /* advisory only — the receipt still saves */
    }
  };

  const onEntry = (index: number, key: keyof Entry) => async (value: string) => {
    setEntry(index, key, value);
    if (key === "mode") setEntry(index, "receipt_account", "");
    if (key === "party") {
      setEntry(index, "balance", "");
      // Read from the value just chosen; state has not re-rendered yet.
      const h = head;
      try {
        const { data } = await http.get<Envelope<Lookup>>("/broiler/receipt-lookup", {
          params: {
            location: h.location, sale_type: h.sale_type,
            [h.sale_type === "farmer" ? "farmer" : "customer"]: value,
          },
        });
        setEntry(index, "balance", data.data.balance ?? "0");
      } catch {
        /* advisory only */
      }
    }
  };

  const submit = async () => {
    setError(null);
    if (!head.date) return setError("Date is required.");
    if (!head.location) return setError("Select a location.");
    const filled = entries.filter((e) => e.party && e.amount);
    if (!filled.length) {
      return setError("Add at least one entry with a party and an amount.");
    }
    const noCode = filled.findIndex((e) => !e.receipt_account);
    if (noCode >= 0) return setError(`Choose a Code for entry ${noCode + 1}.`);

    setSaving(true);
    try {
      const rows = filled.map((e) => ({
        date: head.date,
        location: head.location,
        sale_type: head.sale_type,
        customer: forFarmer ? null : e.party,
        farmer: forFarmer ? e.party : null,
        mode: e.mode,
        receipt_account: e.receipt_account,
        amount: e.amount,
        reference_no: e.reference_no,
        remarks: e.remarks,
      }));
      // Editing touches one saved receipt, so it posts that row flat; a new
      // receipt posts the whole document. Same shape the web form uses.
      if (existing?.id) {
        await http.put(`/broiler/bird-sale-receipts/save/${existing.id}`, rows[0]);
      } else {
        await http.post("/broiler/bird-sale-receipts/save", { rows });
      }
      queryClient.invalidateQueries({ queryKey: ["resource", "/broiler/bird-sale-receipts/"] });
      navigation.goBack();
    } catch (e: unknown) {
      const err = e as { message?: string; fields?: Record<string, string[]> };
      const detail = Object.values(err.fields ?? {}).flat().join(" ");
      const message = detail || err.message || "Could not save the receipt.";
      setError(message);
      Alert.alert("Could not save", message);
    } finally {
      setSaving(false);
    }
  };

  const SectionHead = ({ icon, title, extra }: {
    icon: string; title: string; extra?: React.ReactNode;
  }) => (
    <View style={styles.sectionHead}>
      <View style={[styles.badge, { backgroundColor: colors.broilerLight ?? colors.surfaceAlt }]}>
        <AppIcon name={icon as never} size={16} color={colors.broiler ?? colors.tint} />
      </View>
      <Text style={[styles.sectionTitle, { color: colors.broiler ?? colors.tint }]}>{title}</Text>
      <View style={{ flex: 1 }} />
      {extra}
    </View>
  );

  return (
    <View style={styles.screen}>
      <ScrollView contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
        {error ? <Text style={styles.error}>{error}</Text> : null}

        <View style={styles.card}>
          <SectionHead icon="file-document-outline" title="RECEIPT HEADER" />
          <View style={styles.row}>
            <View style={styles.cell}>
              <FormControl field={DATE} value={head.date} values={head} onChange={onHead("date")} />
            </View>
            <View style={styles.cell}>
              <Text style={styles.fieldLabel}>Receipt Source</Text>
              <View style={styles.sourceRow}>
                {(["customer", "farmer"] as const).map((kind) => (
                  <Pressable key={kind} style={styles.radio}
                             onPress={() => onHead("sale_type")(kind)}>
                    <View style={[styles.radioDot,
                                  head.sale_type === kind && { borderColor: colors.broiler ?? colors.tint }]}>
                      {head.sale_type === kind ? (
                        <View style={[styles.radioFill,
                                      { backgroundColor: colors.broiler ?? colors.tint }]} />
                      ) : null}
                    </View>
                    <Text style={styles.radioText}>
                      {kind === "customer" ? "Customer" : "Farmer"}
                    </Text>
                  </Pressable>
                ))}
              </View>
            </View>
          </View>
          <FormControl field={locationField(locations)} value={head.location}
                       values={head} onChange={onHead("location")} />
        </View>

        <View style={styles.card}>
          <SectionHead
            icon="receipt"
            title={`RECEIPT RECORDS (${entries.length} ${entries.length === 1 ? "Entry" : "Entries"})`}
            extra={
              <Pressable style={styles.addChip}
                         onPress={() => setEntries((c) => [...c, emptyEntry()])}>
                <Text style={[styles.addChipText, { color: colors.tint }]}>+ Add</Text>
              </Pressable>
            }
          />

          {entries.map((entry, i) => (
            <View key={i} style={styles.entry}>
              <View style={[styles.entryHead,
                            { backgroundColor: colors.broilerLight ?? colors.surfaceAlt }]}>
                <AppIcon name="credit-card-outline" size={16}
                         color={colors.broiler ?? colors.tint} />
                <Text style={[styles.entryTitle, { color: colors.broiler ?? colors.tint }]}>
                  {i + 1}. PAYMENT ENTRY
                </Text>
                <View style={{ flex: 1 }} />
                {entries.length > 1 ? (
                  <Pressable onPress={() => setEntries((c) => c.filter((_, j) => j !== i))}
                             hitSlop={8} accessibilityLabel={`Remove entry ${i + 1}`}>
                    <AppIcon name="trash-can-outline" size={18} color={colors.danger} />
                  </Pressable>
                ) : null}
              </View>

              <View style={styles.entryBody}>
                <FormControl field={partyField(forFarmer ? farmers : customers, forFarmer)}
                             value={entry.party} onChange={onEntry(i, "party")} />
                <FormControl field={BALANCE}
                             value={entry.balance ? `₹ ${entry.balance}` : ""}
                             onChange={() => {}} />

                <View style={styles.divider} />
                <Text style={[styles.subHead, { color: colors.broiler ?? colors.tint }]}>
                  PAYMENT DETAILS
                </Text>
                <View style={styles.row}>
                  <View style={styles.cell}>
                    <FormControl field={modeField(modeOptions)} value={entry.mode}
                                 onChange={onEntry(i, "mode")} />
                  </View>
                  <View style={styles.cell}>
                    <FormControl field={codeField(codesFor(entry.mode), !!entry.mode)}
                                 value={entry.receipt_account}
                                 onChange={onEntry(i, "receipt_account")} />
                  </View>
                </View>
                <View style={styles.row}>
                  <View style={styles.cell}>
                    <FormControl field={AMOUNT} value={entry.amount}
                                 onChange={onEntry(i, "amount")} />
                  </View>
                  <View style={styles.cell}>
                    <FormControl field={REF} value={entry.reference_no}
                                 onChange={onEntry(i, "reference_no")} />
                  </View>
                </View>
                <FormControl field={REMARKS} value={entry.remarks}
                             onChange={(v) => setEntry(i, "remarks", v.slice(0, REMARKS_MAX))} />
                <Text style={styles.counter}>{entry.remarks.length}/{REMARKS_MAX}</Text>
              </View>
            </View>
          ))}

          <Pressable style={styles.addAnother}
                     onPress={() => setEntries((c) => [...c, emptyEntry()])}>
            <Text style={[styles.addAnotherText, { color: colors.tint }]}>
              +  Add Another Receipt
            </Text>
          </Pressable>
        </View>
      </ScrollView>

      <View style={styles.footer}>
        <Pressable style={[styles.cancel, { borderColor: colors.danger }]}
                   onPress={() => navigation.goBack()}>
          <AppIcon name="close" size={18} color={colors.danger} />
          <Text style={[styles.cancelText, { color: colors.danger }]}>Cancel</Text>
        </Pressable>
        <Pressable style={[styles.submit, { backgroundColor: colors.broiler ?? colors.tint },
                           saving && { opacity: 0.6 }]}
                   onPress={submit} disabled={saving}>
          <AppIcon name="check" size={18} color={colors.onDark} />
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
  sectionHead: { flexDirection: "row", alignItems: "center", gap: spacing.sm,
                 marginBottom: spacing.sm },
  badge: { width: 28, height: 28, borderRadius: 7, alignItems: "center", justifyContent: "center" },
  sectionTitle: { ...type.label, letterSpacing: 0.6 },
  row: { flexDirection: "row", gap: spacing.sm, alignItems: "flex-start" },
  cell: { flex: 1, minWidth: 0 },
  fieldLabel: { ...type.label, color: colors.text, marginBottom: spacing.xs },

  sourceRow: { flexDirection: "row", gap: spacing.md, paddingVertical: spacing.sm },
  radio: { flexDirection: "row", alignItems: "center", gap: spacing.xs },
  radioDot: {
    width: 20, height: 20, borderRadius: 10, borderWidth: 2, borderColor: colors.border,
    alignItems: "center", justifyContent: "center",
  },
  radioFill: { width: 10, height: 10, borderRadius: 5 },
  radioText: { ...type.body, color: colors.text },

  addChip: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm,
    paddingHorizontal: spacing.md, paddingVertical: spacing.xs,
  },
  addChipText: { ...type.caption, fontWeight: "700" },

  entry: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    overflow: "hidden", marginBottom: spacing.sm,
  },
  entryHead: { flexDirection: "row", alignItems: "center", gap: spacing.sm,
               paddingHorizontal: spacing.md, paddingVertical: spacing.sm },
  entryTitle: { ...type.label, letterSpacing: 0.4 },
  entryBody: { padding: spacing.md },
  divider: { height: 1, backgroundColor: colors.border, marginVertical: spacing.md },
  subHead: { ...type.label, letterSpacing: 0.6, marginBottom: spacing.xs },
  counter: { ...type.caption, color: colors.textMuted, textAlign: "right" },

  addAnother: {
    borderWidth: 1, borderStyle: "dashed", borderColor: colors.tint,
    borderRadius: radius.md, paddingVertical: spacing.md, alignItems: "center",
  },
  addAnotherText: { ...type.title },

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
    flex: 1.4, height: 48, borderRadius: radius.md,
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.xs,
  },
  submitText: { ...type.title, color: colors.onDark },
}));
