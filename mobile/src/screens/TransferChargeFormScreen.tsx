/**
 * Add Transfer Charges — the entry screen on the phone.
 *
 * The same four steps the browser's Add screen asks, in the same order: pick
 * the trip this cost belongs to, say how it is treated and paid, list what
 * was charged, then attach the evidence and write the sentence. A phone has
 * no room for the web's wide allocation table, so a Common line's split is
 * read as a short summary line rather than a full per-farm grid — the
 * number is still the server's own (`previewAllocation`), never recomputed
 * here.
 *
 * Nothing here decides anything: every save, post, cancel and allocation
 * figure goes to the web module's own view, which runs the identical
 * engine the browser's Add screen posts to.
 */
import { NativeStackScreenProps } from "@react-navigation/native-stack";
import { useQuery } from "@tanstack/react-query";
import React, { useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Image,
  Linking,
  Modal,
  Pressable,
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import {
  attachTransferChargeFiles,
  detachTransferChargeFile,
  getTransferCharge,
  lookupStockTransferTrips,
  previewAllocation,
  saveTransferCharge,
  StockTransferTripGroup,
  TransferChargeAllocationInput,
  TransferChargeLineInput,
  TransferChargeMasters,
  transferChargeMasters,
  TransferChargeRow,
} from "@/api/transferCharges";
import { capturePhoto, CapturedImage, CapturePermissionError, pickDocument, pickPhoto } from "@/capture";
import { confirm, notify } from "@/ui/confirm";
import { billUrl, chargeIcon, isoDate, transferChargeMoney as money } from "@/domain/transferCharge";
import { AppIcon, IconName } from "@/components/AppIcon";
import { DateField } from "@/components/DateField";
import { Card, Screen, SearchBar } from "@/components/ui";
import { ModuleStackParams } from "@/navigation/types";
import { makeStyles, radius, shadow, spacing, type, withAlpha } from "@/theme";
import { useTheme } from "@/theme/ThemeProvider";

type Props = NativeStackScreenProps<ModuleStackParams, "TransferChargeForm">;

/** Pop back to the list -- or, lacking any history to pop (this screen was
 *  the stack's own first entry, e.g. a web refresh landed here directly),
 *  go to the list explicitly rather than leave the saved entry on screen. */
function goToList(navigation: Props["navigation"]): void {
  if (navigation.canGoBack()) navigation.goBack();
  else navigation.navigate("TransferChargeList");
}

interface Option {
  value: string;
  label: string;
}

/** One charge line as the screen holds it, plus what the server's
 *  allocation preview answered for it last. */
interface Line extends TransferChargeLineInput {
  previewRows?: { farm_id: number; farm_name: string; allocated_amount: number; percentage: number }[];
}

const BLANK_LINE: Line = {
  charge_type: "",
  description: "",
  charge_scope: "Common",
  basis: "Fixed",
  total_amount: "",
  allocation_method: "Equal",
  allocations: [],
};

type Attachment = TransferChargeRow["attachments"][number];

export function TransferChargeFormScreen({ route, navigation }: Props) {
  const styles = useStyles();
  const { colors } = useTheme();
  const id = route?.params?.id;

  const masters = useQuery({ queryKey: ["transfer-charge-masters"], queryFn: transferChargeMasters });
  const M = masters.data;

  const [chargeNo, setChargeNo] = useState("");
  const [date, setDate] = useState(isoDate(new Date()));
  const [trips, setTrips] = useState<StockTransferTripGroup[]>([]);
  const [treatment, setTreatment] = useState("Expense Only");
  const [paymentMode, setPaymentMode] = useState("Paid Now");
  const [paidFrom, setPaidFrom] = useState("");
  const [payableAccount, setPayableAccount] = useState("");
  const [payeeName, setPayeeName] = useState("");
  const [costCentre, setCostCentre] = useState("");
  const [lines, setLines] = useState<Line[]>([{ ...BLANK_LINE }]);
  const [openLine, setOpenLine] = useState<number | null>(0);
  const [bills, setBills] = useState<CapturedImage[]>([]);
  const [saved, setSaved] = useState<Attachment[]>([]);
  const [narration, setNarration] = useState("");
  const [narrationTouched, setTouched] = useState(false);
  const [headerRemarks, setHeaderRemarks] = useState("");
  const [status, setStatus] = useState("Draft");
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState("");

  // Trip search (Step 1).
  const [tripQuery, setTripQuery] = useState("");
  const [tripResults, setTripResults] = useState<StockTransferTripGroup[]>([]);
  const [searchingTrips, setSearchingTrips] = useState(false);

  const readOnly = status !== "Draft" && status !== "Pending Approval";

  /* -- what the pickers hold ----------------------------------------- */

  const chargeTypes: Option[] = useMemo(
    () => (M?.charge_types ?? []).map((c) => ({ value: String(c.id), label: c.name })),
    [M]
  );
  const allocationMethods: Option[] = useMemo(
    () => (M?.allocation_methods ?? []).map((m) => ({ value: m, label: m })),
    [M]
  );
  const bankCashAccounts: Option[] = useMemo(
    () => (M?.bank_cash_accounts ?? []).map((a) => ({ value: String(a.id), label: a.name })),
    [M]
  );
  const payableAccounts: Option[] = useMemo(
    () =>
      (M?.payable_accounts ?? []).map((a) => ({ value: String(a.id), label: `${a.code} · ${a.description}` })),
    [M]
  );

  // The aggregated destination farms across every picked trip -- the basis
  // every Common line's allocation is split across.
  const farms = useMemo(() => {
    const byFarm = new Map<number, { farm_id: number; farm_name: string; quantity: number; stock_value: number }>();
    trips.forEach((t) =>
      t.farms.forEach((f) => {
        const row = byFarm.get(f.farm_id);
        if (row) {
          row.quantity += Number(f.quantity || 0);
          row.stock_value += Number(f.stock_value || 0);
        } else {
          byFarm.set(f.farm_id, { ...f });
        }
      })
    );
    return Array.from(byFarm.values());
  }, [trips]);

  const totalCharges = lines.reduce((sum, l) => sum + lineTotal(l), 0);
  const buckets = useMemo(() => chargeBuckets(lines, chargeTypes), [lines, chargeTypes]);

  /* -- opening a saved charge ------------------------------------------ */

  useEffect(() => {
    if (!id) return;
    let alive = true;
    getTransferCharge(id).then(async (data) => {
      if (!alive) return;
      setChargeNo(data.charge_no);
      setDate(data.charge_date);
      setTreatment(data.treatment);
      setPaymentMode(data.payment_mode);
      setPaidFrom(data.paid_from ? String(data.paid_from) : "");
      setPayableAccount(data.payable_account ? String(data.payable_account) : "");
      setPayeeName(data.payee_name);
      setCostCentre(data.cost_centre ? String(data.cost_centre) : "");
      setNarration(data.narration);
      setTouched(!!data.narration);
      setHeaderRemarks(data.header_remarks);
      setStatus(data.status);
      setSaved(data.attachments);
      setLines(
        data.lines.map((l) => ({
          charge_type: String(l.charge_type),
          description: l.description,
          charge_scope: l.charge_scope,
          basis: l.basis,
          total_amount: String(l.total_amount),
          allocation_method: l.allocation_method,
          allocations: l.allocations.map((a) => ({
            destination_farm: a.destination_farm,
            allocated_amount: String(a.allocated_amount),
            percentage: String(a.percentage ?? ""),
            remarks: a.remarks ?? "",
          })),
        }))
      );
      // Re-expand the saved ids back into their original (dc_no, date)
      // groups, exactly as the web Add screen does when editing a draft.
      if (data.stock_transfer_ids.length) {
        const groups = await lookupStockTransferTrips({ ids: data.stock_transfer_ids.join(",") });
        if (alive) setTrips(Array.isArray(groups) ? groups : [groups]);
      }
    });
    return () => {
      alive = false;
    };
  }, [id]);

  /* -- the preview number, until a real one exists ---------------------- */

  useEffect(() => {
    if (id) return;
    setChargeNo((was) => was || "Preview pending");
  }, [id]);

  /* -- the sentence, until somebody writes their own --------------------- */

  useEffect(() => {
    if (narrationTouched) return;
    if (!trips.length) {
      setNarration("");
      return;
    }
    const names = farms.map((f) => f.farm_name);
    const to =
      names.length <= 1 ? names[0] || "destination" : names.slice(0, -1).join(", ") + " and " + names[names.length - 1];
    const dc = trips.map((t) => t.dc_no).join(", ");
    setNarration(`Transfer charges for ${dc} to ${to}.`);
  }, [trips, farms, narrationTouched]);

  /* -- trip search (Step 1) --------------------------------------------- */

  useEffect(() => {
    if (!tripQuery.trim()) {
      setTripResults([]);
      return;
    }
    let alive = true;
    setSearchingTrips(true);
    const timer = setTimeout(async () => {
      try {
        const rows = await lookupStockTransferTrips({
          q: tripQuery.trim(),
          exclude_header: id,
        });
        if (alive) setTripResults(Array.isArray(rows) ? rows : [rows]);
      } finally {
        if (alive) setSearchingTrips(false);
      }
    }, 300);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [tripQuery, id]);

  function isPicked(t: StockTransferTripGroup) {
    return trips.some((p) => p.dc_no === t.dc_no && p.date === t.date);
  }

  function pickTrip(t: StockTransferTripGroup) {
    if (isPicked(t)) {
      setTrips((was) => was.filter((p) => !(p.dc_no === t.dc_no && p.date === t.date)));
    } else {
      setTrips((was) => [...was, t]);
    }
  }

  /* -- allocation preview for a Common line ------------------------------ */

  async function refreshPreview(index: number, next: Line[]) {
    const line = next[index];
    if (line.charge_scope !== "Common" || farms.length < 2 || !Number(line.total_amount || 0)) return;
    try {
      const resp = await previewAllocation({
        farms: farms.map((f) => ({
          farm_id: f.farm_id,
          farm_name: f.farm_name,
          quantity: String(f.quantity),
          stock_value: String(f.stock_value),
        })),
        total_amount: String(line.total_amount || 0),
        allocation_method: line.allocation_method || "Equal",
      });
      setLines((was) =>
        was.map((l, i) =>
          i === index
            ? {
                ...l,
                previewRows: resp.rows.map((r) => ({
                  farm_id: r.destination_farm,
                  farm_name: r.destination_farm_name || "",
                  allocated_amount: r.allocated_amount,
                  percentage: r.percentage || 0,
                })),
              }
            : l
        )
      );
    } catch {
      // A preview that fails to load is not worth interrupting typing for;
      // the save itself will still refuse a line the server can't allocate.
    }
  }

  function updateLine(index: number, patch: Partial<Line>) {
    setLines((was) => {
      const next = was.map((l, i) => (i === index ? { ...l, ...patch } : l));
      refreshPreview(index, next);
      return next;
    });
  }

  /* -- bills -------------------------------------------------------------- */

  async function addBill(from: "camera" | "library" | "document") {
    try {
      const picked =
        from === "camera" ? await capturePhoto() : from === "library" ? await pickPhoto() : await pickDocument();
      if (picked) setBills((was) => [...was, picked]);
    } catch (e) {
      if (e instanceof CapturePermissionError) {
        Alert.alert(
          "Permission needed",
          from === "camera" ? "Allow the camera to photograph a receipt." : "Allow access to attach a file."
        );
        return;
      }
      Alert.alert("That did not work", "The file could not be added.");
    }
  }

  async function dropSaved(bill: Attachment) {
    if (!id) return;
    const ok = await confirm({
      title: `Remove ${bill.file_name}?`,
      message: "The charge keeps everything else.",
      confirmLabel: "Remove",
      cancelLabel: "Keep",
      destructive: true,
    });
    if (!ok) return;
    try {
      await detachTransferChargeFile(id, bill.id);
      setSaved((was) => was.filter((b) => b.id !== bill.id));
    } catch (e) {
      notify(refusal(e, "It could not be removed."));
    }
  }

  /* -- saving --------------------------------------------------------------- */

  function body(action?: "post", submitForApproval?: boolean, allowDuplicate?: boolean) {
    return {
      dc_no: trips.map((t) => t.dc_no).join(", "),
      charge_date: date,
      stock_transfer_ids: trips.flatMap((t) => t.stock_transfer_ids),
      treatment,
      payment_mode: paymentMode,
      paid_from: paymentMode === "Paid Now" ? paidFrom : "",
      payable_account: paymentMode === "Pay Later" ? payableAccount : "",
      payee_name: payeeName,
      cost_centre: costCentre,
      narration,
      header_remarks: headerRemarks,
      submit_for_approval: submitForApproval,
      action,
      allow_duplicate: allowDuplicate,
      lines: lines
        .filter((l) => l.charge_type)
        .map((l) => ({
          charge_type: l.charge_type,
          description: l.description,
          charge_scope: l.charge_scope,
          basis: l.basis,
          total_amount: l.charge_scope === "Common" ? l.total_amount : lineTotal(l).toFixed(2),
          allocation_method: l.allocation_method,
          allocations: l.allocations,
        })),
    };
  }

  const typed = () =>
    trips.length > 0 || bills.length > 0 || lines.some((l) => l.charge_type || Number(l.total_amount || 0) > 0);

  async function leave() {
    if (!typed()) {
      goToList(navigation);
      return;
    }
    const ok = await confirm({
      title: id ? "Leave without saving your changes?" : "Leave without saving this charge?",
      message: "Anything entered here will be lost. Nothing has been saved yet.",
      confirmLabel: "Leave",
      cancelLabel: "Stay",
      destructive: true,
    });
    if (ok) goToList(navigation);
  }

  async function save(action?: "post", submitForApproval?: boolean, allowDuplicate?: boolean) {
    if (!trips.length) {
      setProblem("Select at least one Stock Transfer first.");
      return;
    }
    if (!lines.some((l) => l.charge_type)) {
      setProblem("Add at least one charge line.");
      return;
    }
    setProblem("");
    setSaving(true);
    try {
      const result = await saveTransferCharge(body(action, submitForApproval, allowDuplicate), id);
      if (bills.length) {
        const form = new FormData();
        bills.forEach((b) => form.append("files", { uri: b.uri, name: b.name, type: b.mimeType } as unknown as Blob));
        try {
          await attachTransferChargeFiles(result.id, form);
        } catch {
          Alert.alert("Saved, without its files", "The charge saved; its attachments did not.");
        }
      }
      notify(
        result.status === "Posted" ? "Posted" : result.status === "Pending Approval" ? "Submitted" : "Draft saved",
        `${result.charge_no} saved as ${result.status}.`
      );
      goToList(navigation);
    } catch (e) {
      const data = (e as { response?: { data?: { error?: Record<string, unknown> } } })?.response?.data?.error as
        | { message?: string; duplicate?: boolean; existing?: string[] }
        | undefined;
      if (data?.duplicate) {
        setSaving(false);
        const ok = await confirm({
          title: "Already charged",
          message: `${data.message}\n\nPost anyway?`,
          confirmLabel: "Post anyway",
          cancelLabel: "Not now",
        });
        if (ok) await save(action, submitForApproval, true);
        return;
      }
      setProblem(data?.message || "It could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  if (masters.isLoading) {
    return (
      <Screen edges={["left", "right"]}>
        <View style={styles.centre}>
          <ActivityIndicator />
          <Text style={styles.muted}>Reading the masters</Text>
        </View>
      </Screen>
    );
  }

  return (
    <Screen edges={["left", "right"]}>
      <ScrollView contentContainerStyle={styles.page} keyboardShouldPersistTaps="handled">
        <Card style={styles.box}>
          <View style={[styles.boxIcon, { backgroundColor: withAlpha(colors.tint, 0.14) }]}>
            <AppIcon name="truck" size={18} color={colors.tint} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.boxName} numberOfLines={1}>
              {chargeNo || "New Transfer Charge"}
            </Text>
            <Text style={styles.muted}>{status}</Text>
          </View>
          <Text style={styles.boxAmount}>{money(totalCharges)}</Text>
        </Card>

        {readOnly ? (
          <Card style={styles.noteCard}>
            <Text style={styles.note}>This one is {status.toLowerCase()}, so it is shown as it stands.</Text>
          </Card>
        ) : null}

        <Section step={1} title="Transfer Charge & Select Stock Transfers">
          <Field label="Charge Date" required>
            <DateField value={date} onChange={setDate} />
          </Field>

          {!readOnly ? (
            <>
              <SearchBar value={tripQuery} onChangeText={setTripQuery} placeholder="Search by DC No." />
              {searchingTrips ? <ActivityIndicator style={{ marginVertical: spacing.sm }} /> : null}
              {tripResults.map((t) => (
                <TripRow key={`${t.dc_no}-${t.date}`} trip={t} picked={isPicked(t)} onPress={() => pickTrip(t)} />
              ))}
            </>
          ) : null}

          {trips.length === 0 ? (
            <Text style={styles.muted}>No Stock Transfer selected yet.</Text>
          ) : (
            <View style={styles.chips}>
              {trips.map((t) => (
                <View key={`${t.dc_no}-${t.date}`} style={styles.chip}>
                  <Text style={styles.chipText}>
                    {t.dc_no} · {t.date}
                  </Text>
                  {!readOnly ? (
                    <Pressable onPress={() => pickTrip(t)} hitSlop={8}>
                      <AppIcon name="close" size={14} color={colors.textMuted} />
                    </Pressable>
                  ) : null}
                </View>
              ))}
            </View>
          )}

          {farms.length > 0 ? (
            <View style={styles.farmSummary}>
              <Text style={styles.label}>
                {farms.length} destination {farms.length === 1 ? "farm" : "farms"}
              </Text>
              {farms.map((f) => (
                <Text key={f.farm_id} style={styles.muted}>
                  {f.farm_name} — {f.quantity.toLocaleString("en-IN")} qty
                </Text>
              ))}
            </View>
          ) : null}
        </Section>

        <Section
          step={2}
          title="Transfer Charges Entry"
          action={
            readOnly ? undefined : (
              <Pressable
                style={styles.addItem}
                onPress={() => {
                  setLines((was) => [...was, { ...BLANK_LINE }]);
                  setOpenLine(lines.length);
                }}
              >
                <AppIcon name="plus" size={14} color={colors.tint} />
                <Text style={styles.addItemText}>Add Charge</Text>
              </Pressable>
            )
          }
        >
          {lines.map((line, index) =>
            index === openLine && !readOnly ? (
              <LineFields
                key={index}
                masters={M}
                line={line}
                index={index}
                farms={farms}
                canRemove={lines.length > 1}
                onChange={(patch) => updateLine(index, patch)}
                onRemove={() => {
                  setLines((was) => was.filter((_, i) => i !== index));
                  setOpenLine(null);
                }}
                onCollapse={() => setOpenLine(null)}
              />
            ) : (
              <LineCard
                key={index}
                line={line}
                chargeTypeName={chargeTypes.find((c) => c.value === line.charge_type)?.label || ""}
                onPress={() => !readOnly && setOpenLine(index)}
              />
            )
          )}
        </Section>

        <Section step={3} title="Charge Allocation & Total Summary">
          <View style={styles.costingLine}>
            <Text style={styles.label}>
              Costing: {farms.length} {farms.length === 1 ? "farm" : "farms"}
            </Text>
            <Text style={styles.muted}>
              Qty:{" "}
              {farms
                .reduce((sum, f) => sum + f.quantity, 0)
                .toLocaleString("en-IN")}
            </Text>
          </View>
          <View style={styles.bucketRow}>
            {([
              ["Transport", buckets.transport, "truck"],
              ["Loading", buckets.loading, "package-up"],
              ["Unloading", buckets.unloading, "package-down"],
              ["Toll / Other", buckets.other, "receipt"],
            ] as const).map(([label, amount, icon]) => (
              <View key={label} style={styles.bucket}>
                <AppIcon name={icon} size={16} color={colors.textMuted} />
                <Text style={styles.bucketLabel}>{label}</Text>
                <Text style={styles.bucketAmount}>{money(amount)}</Text>
              </View>
            ))}
          </View>
          <View style={styles.grandTotal}>
            <Text style={styles.grandTotalLabel}>Total Transfer Charges</Text>
            <Text style={styles.grandTotalAmount}>{money(totalCharges)}</Text>
          </View>
        </Section>

        <Section step={4} title="Supporting Documents & Remarks">
          <View style={styles.bills}>
            {!readOnly ? (
              <>
                <Pressable style={styles.billAdd} onPress={() => addBill("camera")}>
                  <AppIcon name="camera" size={18} color={colors.tint} />
                  <Text style={styles.billAddText}>Photo</Text>
                </Pressable>
                <Pressable style={styles.billAdd} onPress={() => addBill("library")}>
                  <AppIcon name="image-multiple-outline" size={18} color={colors.tint} />
                  <Text style={styles.billAddText}>Gallery</Text>
                </Pressable>
                <Pressable style={styles.billAdd} onPress={() => addBill("document")}>
                  <AppIcon name="file-pdf-box" size={18} color={colors.tint} />
                  <Text style={styles.billAddText}>File</Text>
                </Pressable>
              </>
            ) : null}
            {saved.map((bill) => (
              <View key={`saved-${bill.id}`} style={styles.bill}>
                <Pressable
                  style={styles.billFace}
                  onPress={() => Linking.openURL(billUrl(bill.url)).catch(() => undefined)}
                  accessibilityLabel={`Open ${bill.file_name}`}
                >
                  {/^image/.test(bill.file_type || "") ? (
                    <Image source={{ uri: billUrl(bill.url) }} style={styles.billImage} />
                  ) : (
                    <AppIcon name="file-pdf-box" size={22} color={colors.danger} />
                  )}
                </Pressable>
                <Text style={styles.billName} numberOfLines={1}>
                  {bill.file_name}
                </Text>
                {!readOnly ? (
                  <Pressable style={styles.billX} onPress={() => dropSaved(bill)}>
                    <AppIcon name="close" size={10} color={colors.onDark} />
                  </Pressable>
                ) : null}
              </View>
            ))}
            {bills.map((bill, index) => (
              <View key={bill.uri} style={styles.bill}>
                <View style={styles.billFace}>
                  {/^image/.test(bill.mimeType || "") ? (
                    <Image source={{ uri: bill.uri }} style={styles.billImage} />
                  ) : (
                    <AppIcon name="file-pdf-box" size={22} color={colors.danger} />
                  )}
                </View>
                <Text style={styles.billName} numberOfLines={1}>
                  {bill.name}
                </Text>
                <Pressable style={styles.billX} onPress={() => setBills((was) => was.filter((_, i) => i !== index))}>
                  <AppIcon name="close" size={10} color={colors.onDark} />
                </Pressable>
              </View>
            ))}
          </View>
          <Field label="Narration">
            <TextInput
              style={[styles.input, styles.textarea]}
              value={narration}
              onChangeText={(v) => {
                setTouched(true);
                setNarration(v);
              }}
              multiline
              placeholder="What this was for, as it should read on the voucher"
              placeholderTextColor={colors.textFaint}
            />
          </Field>
          <Field label="Remarks">
            <TextInput
              style={[styles.input, styles.textarea]}
              value={headerRemarks}
              onChangeText={setHeaderRemarks}
              multiline
              placeholder="Anything else worth noting"
              placeholderTextColor={colors.textFaint}
            />
          </Field>
        </Section>

        <Section step={5} title="Accounting & Payment">
          <Field label="Accounting Treatment" required>
            <View style={styles.toggleRow}>
              {["Expense Only", "Add to Inventory Cost"].map((opt) => (
                <Pressable
                  key={opt}
                  style={[styles.toggle, treatment === opt && styles.toggleOn]}
                  disabled={readOnly}
                  onPress={() => setTreatment(opt)}
                >
                  <Text style={[styles.toggleText, treatment === opt && styles.toggleTextOn]}>{opt}</Text>
                </Pressable>
              ))}
            </View>
          </Field>
          <Field label="Payment / Posting" required>
            <View style={styles.toggleRow}>
              {["Paid Now", "Pay Later"].map((opt) => (
                <Pressable
                  key={opt}
                  style={[styles.toggle, paymentMode === opt && styles.toggleOn]}
                  disabled={readOnly}
                  onPress={() => setPaymentMode(opt)}
                >
                  <Text style={[styles.toggleText, paymentMode === opt && styles.toggleTextOn]}>{opt}</Text>
                </Pressable>
              ))}
            </View>
          </Field>
          {paymentMode === "Paid Now" ? (
            <Field label="Paid From (Cash/Bank)" required>
              <Picker title="Paid From" value={paidFrom} options={bankCashAccounts} onChange={setPaidFrom} />
            </Field>
          ) : (
            <Field label="Payable To (Ledger)" required>
              <Picker title="Payable Ledger" value={payableAccount} options={payableAccounts} onChange={setPayableAccount} />
            </Field>
          )}
          <Field label="Paid To">
            <TextInput
              style={styles.input}
              value={payeeName}
              onChangeText={setPayeeName}
              placeholder="Transporter / Driver name"
              placeholderTextColor={colors.textFaint}
            />
          </Field>
        </Section>

        {problem ? (
          <Card style={styles.problem}>
            <AppIcon name="alert-circle-outline" size={16} color={colors.danger} />
            <Text style={styles.problemText}>{problem}</Text>
          </Card>
        ) : null}
      </ScrollView>

      {!readOnly ? (
        <View style={[styles.foot, shadow(2)]}>
          <Pressable style={[styles.footBtn, styles.cancelBtn]} disabled={saving} onPress={leave}>
            <Text style={styles.cancelText}>Cancel</Text>
          </Pressable>
          <Pressable style={[styles.footBtn, styles.draftBtn]} disabled={saving} onPress={() => save()}>
            <Text style={styles.draftText}>Save Draft</Text>
          </Pressable>
          <Pressable
            style={[styles.footBtn, styles.submitBtn]}
            disabled={saving}
            onPress={() => save(undefined, true)}
          >
            <Text style={styles.submitText}>Submit</Text>
          </Pressable>
          <Pressable
            style={[styles.footBtn, styles.postBtn]}
            disabled={saving}
            onPress={async () => {
              const ok = await confirm({
                title: "Save & Post?",
                message: "Once posted this Transfer Charge cannot be edited.",
                confirmLabel: "Post",
                cancelLabel: "Not yet",
              });
              if (ok) save("post");
            }}
          >
            {saving ? <ActivityIndicator color={colors.onDark} /> : <Text style={styles.postText}>Save &amp; Post</Text>}
          </Pressable>
        </View>
      ) : null}
    </Screen>
  );
}

/* ------------------------------------------------------------------ */

function lineTotal(line: Line): number {
  if (line.charge_scope === "Farm-wise") {
    return (line.allocations || []).reduce((sum, a) => sum + (Number(a.allocated_amount) || 0), 0);
  }
  return Number(line.total_amount || 0);
}

/** The four headline buckets the server's own `recalculate()` groups by
 *  (`TransferChargeHeader`) -- shown as a preview here so the summary step
 *  never disagrees with what posting will actually total. */
function chargeBuckets(
  lines: Line[],
  chargeTypes: Option[]
): { transport: number; loading: number; unloading: number; other: number } {
  const buckets = { transport: 0, loading: 0, unloading: 0, other: 0 };
  for (const line of lines) {
    if (!line.charge_type) continue;
    const name = (chargeTypes.find((c) => c.value === line.charge_type)?.label || "").trim().toLowerCase();
    const amount = lineTotal(line);
    if (name === "transport") buckets.transport += amount;
    else if (name === "loading") buckets.loading += amount;
    else if (name === "unloading") buckets.unloading += amount;
    else buckets.other += amount;
  }
  return buckets;
}

function refusal(error: unknown, fallback: string): string {
  const said = (error as { response?: { data?: { error?: { message?: string } } } })?.response?.data?.error
    ?.message;
  return said || fallback;
}

function TripRow({
  trip,
  picked,
  onPress,
}: {
  trip: StockTransferTripGroup;
  picked: boolean;
  onPress: () => void;
}) {
  const styles = useStyles();
  const { colors } = useTheme();
  return (
    <Pressable style={[styles.tripRow, picked && styles.tripRowPicked]} onPress={onPress}>
      <View style={{ flex: 1, minWidth: 0 }}>
        <Text style={styles.tripDc} numberOfLines={1}>
          {trip.dc_no} · {trip.date}
        </Text>
        <Text style={styles.muted} numberOfLines={1}>
          {trip.from_location || "—"} → {trip.farm_count} {trip.farm_count === 1 ? "farm" : "farms"}
        </Text>
        {trip.already_charged ? (
          <Text style={styles.warnText}>Already on {trip.existing_charge_nos.join(", ")}</Text>
        ) : null}
      </View>
      <AppIcon
        name={picked ? "checkbox-marked" : "checkbox-blank-outline"}
        size={20}
        color={picked ? colors.tint : colors.textFaint}
      />
    </Pressable>
  );
}

/** A line at rest: what it is, and what it comes to. */
function LineCard({
  line,
  chargeTypeName,
  onPress,
}: {
  line: Line;
  chargeTypeName: string;
  onPress: () => void;
}) {
  const styles = useStyles();
  const { colors } = useTheme();
  const blank = !line.charge_type;
  return (
    <Pressable style={[styles.line, blank && styles.lineBlank]} onPress={onPress}>
      <View style={[styles.lineIcon, { backgroundColor: blank ? colors.surfaceAlt : withAlpha(colors.tint, 0.1) }]}>
        <AppIcon
          name={blank ? "plus" : chargeIcon(chargeTypeName)}
          size={16}
          color={blank ? colors.textMuted : colors.tint}
        />
      </View>
      <View style={{ flex: 1, minWidth: 0 }}>
        <Text style={[styles.lineTitle, blank && styles.lineTitleBlank]} numberOfLines={1}>
          {blank ? "Charge type, scope and amount" : chargeTypeName || "Not classified"}
        </Text>
        <Text style={styles.muted} numberOfLines={1}>
          {blank ? "Press to fill this line" : line.description || line.charge_scope}
        </Text>
      </View>
      <Text style={[styles.lineAmount, blank && styles.lineTitleBlank]}>{money(lineTotal(line))}</Text>
    </Pressable>
  );
}

/** A line, open: scope decides whether the amount is one figure split by
 *  the engine (Common) or entered per farm directly (Farm-wise). */
function LineFields({
  masters,
  line,
  index,
  farms,
  canRemove,
  onChange,
  onRemove,
  onCollapse,
}: {
  masters?: TransferChargeMasters;
  line: Line;
  index: number;
  farms: { farm_id: number; farm_name: string; quantity: number; stock_value: number }[];
  canRemove: boolean;
  onChange: (patch: Partial<Line>) => void;
  onRemove: () => void;
  onCollapse: () => void;
}) {
  const styles = useStyles();
  const { colors } = useTheme();
  const chargeTypes: Option[] = (masters?.charge_types ?? []).map((c) => ({ value: String(c.id), label: c.name }));
  const allocationMethods: Option[] = (masters?.allocation_methods ?? []).map((m) => ({ value: m, label: m }));

  function allocationFor(farmId: number): TransferChargeAllocationInput {
    return (
      (line.allocations || []).find((a) => a.destination_farm === farmId) || {
        destination_farm: farmId,
        allocated_amount: "",
        remarks: "",
      }
    );
  }

  function setFarmAmount(farmId: number, amount: string) {
    const rest = (line.allocations || []).filter((a) => a.destination_farm !== farmId);
    onChange({ allocations: [...rest, { ...allocationFor(farmId), allocated_amount: amount }] });
  }

  return (
    <View style={styles.lineOpen}>
      <View style={styles.lineOpenHead}>
        <Text style={styles.lineOpenTitle}>Line {index + 1}</Text>
        <View style={{ flex: 1 }} />
        {canRemove ? (
          <Pressable style={styles.lineTool} onPress={onRemove} hitSlop={8}>
            <AppIcon name="trash-can-outline" size={15} color={colors.danger} />
          </Pressable>
        ) : null}
        <Pressable style={styles.lineTool} onPress={onCollapse} hitSlop={8}>
          <AppIcon name="chevron-up" size={17} color={colors.textMuted} />
        </Pressable>
      </View>

      <Field label="Charge Type" required>
        <Picker title="Charge Type" value={line.charge_type} options={chargeTypes} onChange={(v) => onChange({ charge_type: v })} />
      </Field>
      <Field label="Description">
        <TextInput
          style={styles.input}
          value={line.description}
          onChangeText={(v) => onChange({ description: v })}
          placeholder="What this charge was for"
          placeholderTextColor={colors.textFaint}
        />
      </Field>
      <Field label="Scope" required>
        <View style={styles.toggleRow}>
          {(["Common", "Farm-wise"] as const).map((scope) => (
            <Pressable
              key={scope}
              style={[styles.toggle, line.charge_scope === scope && styles.toggleOn]}
              onPress={() => onChange({ charge_scope: scope })}
            >
              <Text style={[styles.toggleText, line.charge_scope === scope && styles.toggleTextOn]}>{scope}</Text>
            </Pressable>
          ))}
        </View>
      </Field>

      {line.charge_scope === "Common" ? (
        <>
          <Field label="Allocation Method" required>
            <Picker
              title="Allocation Method"
              value={line.allocation_method || "Equal"}
              options={allocationMethods}
              onChange={(v) => onChange({ allocation_method: v })}
            />
          </Field>
          <Field label="Total Amount" required>
            <TextInput
              style={styles.input}
              value={line.total_amount}
              onChangeText={(v) => onChange({ total_amount: v })}
              keyboardType="decimal-pad"
              placeholder="0.00"
              placeholderTextColor={colors.textFaint}
            />
          </Field>
          {line.previewRows?.length ? (
            <View style={styles.previewBox}>
              <Text style={styles.label}>Split across {line.previewRows.length} farms</Text>
              {line.previewRows.map((r) => (
                <View key={r.farm_id} style={styles.previewRow}>
                  <Text style={styles.previewFarm} numberOfLines={1}>
                    {r.farm_name}
                  </Text>
                  <Text style={styles.previewAmount}>
                    {money(r.allocated_amount)} ({r.percentage}%)
                  </Text>
                </View>
              ))}
            </View>
          ) : farms.length === 1 ? (
            <Text style={styles.muted}>The whole amount goes to {farms[0]?.farm_name}.</Text>
          ) : null}
        </>
      ) : (
        <View style={styles.farmWiseBox}>
          <Text style={styles.label}>Amount per destination farm</Text>
          {farms.length === 0 ? (
            <Text style={styles.muted}>Select a Stock Transfer first.</Text>
          ) : (
            farms.map((f) => (
              <View key={f.farm_id} style={styles.farmAmountRow}>
                <Text style={styles.farmAmountLabel} numberOfLines={1}>
                  {f.farm_name}
                </Text>
                <TextInput
                  style={[styles.input, styles.farmAmountInput]}
                  value={allocationFor(f.farm_id).allocated_amount}
                  onChangeText={(v) => setFarmAmount(f.farm_id, v)}
                  keyboardType="decimal-pad"
                  placeholder="0.00"
                  placeholderTextColor={colors.textFaint}
                />
              </View>
            ))
          )}
        </View>
      )}
    </View>
  );
}

function Section({
  step,
  title,
  action,
  children,
}: {
  step: number;
  title: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  const styles = useStyles();
  return (
    <Card padded={false} style={styles.section}>
      <View style={styles.sectionHead}>
        <View style={styles.step}>
          <Text style={styles.stepText}>{step}</Text>
        </View>
        <Text style={styles.sectionTitle}>{title}</Text>
        <View style={{ flex: 1 }} />
        {action}
      </View>
      <View style={styles.sectionBody}>{children}</View>
    </Card>
  );
}

function Field({
  label,
  required,
  children,
}: {
  label: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  const styles = useStyles();
  const { colors } = useTheme();
  return (
    <View style={styles.field}>
      <Text style={styles.label}>
        {label}
        {required ? <Text style={{ color: colors.danger }}> *</Text> : null}
      </Text>
      {children}
    </View>
  );
}

function Picker({
  title,
  value,
  options,
  onChange,
}: {
  title: string;
  value: string;
  options: Option[];
  onChange: (value: string) => void;
}) {
  const styles = useStyles();
  const { colors } = useTheme();
  const [open, setOpen] = useState(false);
  const label = options.find((o) => o.value === value)?.label;

  return (
    <>
      <Pressable style={[styles.input, styles.pick]} onPress={() => setOpen(true)}>
        <Text style={label ? styles.pickText : styles.pickPlaceholder} numberOfLines={1}>
          {label ?? `Select ${title.toLowerCase()}`}
        </Text>
        <AppIcon name="chevron-down" size={18} color={colors.textFaint} />
      </Pressable>

      <Modal visible={open} animationType="slide" onRequestClose={() => setOpen(false)}>
        <SafeAreaView style={styles.modal} edges={["top", "bottom"]}>
          <View style={styles.sheetHead}>
            <Text style={styles.sheetTitle}>{title}</Text>
            <Pressable onPress={() => setOpen(false)} hitSlop={12}>
              <Text style={styles.sheetClose}>Close</Text>
            </Pressable>
          </View>
          <ScrollView contentContainerStyle={{ padding: spacing.md }}>
            {options.map((o) => (
              <Pressable
                key={o.value}
                style={styles.option}
                onPress={() => {
                  onChange(o.value);
                  setOpen(false);
                }}
              >
                <Text style={styles.optionText}>{o.label}</Text>
                {o.value === value ? <AppIcon name="check" size={16} color={colors.tint} /> : null}
              </Pressable>
            ))}
            {options.length === 0 ? <Text style={styles.muted}>Nothing to choose from.</Text> : null}
          </ScrollView>
        </SafeAreaView>
      </Modal>
    </>
  );
}

const useStyles = makeStyles((colors) => ({
  page: { padding: spacing.md, paddingBottom: 120, gap: spacing.sm },
  centre: { flex: 1, alignItems: "center", justifyContent: "center", gap: spacing.sm },
  muted: { ...type.caption, color: colors.textMuted },
  warnText: { ...type.caption, color: colors.warning },

  box: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  boxIcon: { width: 36, height: 36, borderRadius: radius.sm, alignItems: "center", justifyContent: "center" },
  boxName: { ...type.title, color: colors.text },
  boxAmount: { ...type.h3, color: colors.success },

  noteCard: { backgroundColor: colors.warningLight },
  note: { ...type.caption, color: colors.text },

  section: { padding: 0 },
  sectionHead: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    padding: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  step: { width: 22, height: 22, borderRadius: 11, backgroundColor: colors.tint, alignItems: "center", justifyContent: "center" },
  stepText: { ...type.caption, color: colors.onDark, fontWeight: "700" },
  sectionTitle: { ...type.title, color: colors.text },
  sectionBody: { padding: spacing.md, gap: spacing.sm },

  field: { gap: 4 },
  label: { ...type.caption, color: colors.textMuted, fontWeight: "600" },
  input: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: 10,
    color: colors.text,
    backgroundColor: colors.surface,
    fontSize: 15,
  },
  textarea: { minHeight: 70, textAlignVertical: "top" },
  pick: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  pickText: { ...type.body, color: colors.text, flex: 1 },
  pickPlaceholder: { ...type.body, color: colors.textFaint, flex: 1 },

  toggleRow: {
    flexDirection: "row",
    borderWidth: 1,
    borderColor: colors.borderStrong,
    borderRadius: radius.sm,
    overflow: "hidden",
  },
  toggle: { flex: 1, paddingVertical: 8, alignItems: "center" },
  toggleOn: { backgroundColor: colors.tint },
  toggleText: { ...type.caption, color: colors.textMuted, fontWeight: "700" },
  toggleTextOn: { color: colors.onDark },

  addItem: { flexDirection: "row", alignItems: "center", gap: 4 },
  addItemText: { ...type.caption, color: colors.tint, fontWeight: "700" },

  tripRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    padding: spacing.sm,
    marginBottom: spacing.xs,
  },
  tripRowPicked: { borderColor: colors.tint, backgroundColor: withAlpha(colors.tint, 0.06) },
  tripDc: { ...type.body, fontWeight: "700", color: colors.text },

  chips: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs, marginTop: spacing.xs },
  chip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    borderWidth: 1,
    borderColor: colors.tint,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: 4,
  },
  chipText: { ...type.caption, color: colors.tint, fontWeight: "700" },

  farmSummary: { marginTop: spacing.sm, gap: 2 },

  costingLine: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  bucketRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, marginTop: spacing.sm },
  bucket: {
    flexGrow: 1,
    flexBasis: "45%",
    alignItems: "center",
    gap: 2,
    paddingVertical: spacing.sm,
    borderRadius: radius.sm,
    backgroundColor: colors.surfaceAlt,
  },
  bucketLabel: { ...type.caption, color: colors.textMuted },
  bucketAmount: { ...type.body, fontWeight: "700", color: colors.text },
  grandTotal: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginTop: spacing.md,
    paddingTop: spacing.sm,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  grandTotalLabel: { ...type.body, fontWeight: "700", color: colors.text },
  grandTotalAmount: { ...type.h3, color: colors.success },

  line: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    padding: spacing.sm,
  },
  lineBlank: { borderStyle: "dashed", borderColor: colors.borderStrong, backgroundColor: colors.bg },
  lineOpen: {
    borderWidth: 1,
    borderColor: colors.tint,
    borderRadius: radius.sm,
    padding: spacing.sm,
    gap: spacing.sm,
    backgroundColor: colors.surface,
  },
  lineOpenHead: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  lineOpenTitle: { ...type.title, color: colors.text },
  lineTool: { padding: 2 },
  lineTitleBlank: { color: colors.textMuted, fontWeight: "400" },
  lineIcon: { width: 32, height: 32, borderRadius: radius.sm, alignItems: "center", justifyContent: "center" },
  lineTitle: { ...type.title, color: colors.text },
  lineAmount: { ...type.title, color: colors.text },

  previewBox: { backgroundColor: colors.surfaceAlt, borderRadius: radius.sm, padding: spacing.sm, gap: 4 },
  previewRow: { flexDirection: "row", justifyContent: "space-between", gap: spacing.sm },
  previewFarm: { ...type.caption, color: colors.text, flex: 1 },
  previewAmount: { ...type.caption, color: colors.textMuted, fontWeight: "600" },

  farmWiseBox: { gap: spacing.xs },
  farmAmountRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  farmAmountLabel: { ...type.caption, color: colors.text, flex: 1 },
  farmAmountInput: { flex: 1 },

  bills: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  billAdd: {
    width: 72,
    height: 62,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderStyle: "dashed",
    borderColor: colors.tint,
    alignItems: "center",
    justifyContent: "center",
    gap: 2,
  },
  billAddText: { ...type.caption, color: colors.tint },
  bill: { width: 72 },
  billFace: {
    width: 72,
    height: 62,
    borderRadius: radius.sm,
    overflow: "hidden",
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surfaceAlt,
    alignItems: "center",
    justifyContent: "center",
  },
  billImage: { width: "100%", height: "100%" },
  billName: { ...type.caption, color: colors.textMuted, fontSize: 10, marginTop: 2 },
  billX: {
    position: "absolute",
    top: -6,
    right: -6,
    width: 18,
    height: 18,
    borderRadius: 9,
    backgroundColor: colors.danger,
    alignItems: "center",
    justifyContent: "center",
  },

  problem: { flexDirection: "row", gap: spacing.sm, backgroundColor: colors.dangerLight },
  problemText: { ...type.caption, color: colors.text, flex: 1 },

  foot: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.xs,
    padding: spacing.sm,
    backgroundColor: colors.surface,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  footBtn: {
    flex: 1,
    paddingHorizontal: spacing.xs,
    paddingVertical: 10,
    borderRadius: radius.sm,
    alignItems: "center",
    justifyContent: "center",
  },
  cancelBtn: { borderWidth: 1, borderColor: colors.border, flex: 0.7 },
  cancelText: { ...type.caption, color: colors.textMuted, fontWeight: "700" },
  draftBtn: { borderWidth: 1, borderColor: colors.tint },
  draftText: { ...type.caption, color: colors.tint, fontWeight: "700" },
  submitBtn: { backgroundColor: colors.warning },
  submitText: { ...type.caption, color: colors.onDark, fontWeight: "700" },
  postBtn: { backgroundColor: colors.success },
  postText: { ...type.caption, color: colors.onDark, fontWeight: "700" },

  sheetHead: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    padding: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  sheetTitle: { ...type.h3, color: colors.text },
  sheetClose: { ...type.body, color: colors.tint, fontWeight: "700" },

  modal: { flex: 1, backgroundColor: colors.bg },
  option: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  optionText: { ...type.body, color: colors.text, flex: 1 },
}));
