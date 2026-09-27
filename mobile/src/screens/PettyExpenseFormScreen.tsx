/**
 * Add Petty Expense — the entry screen on the phone.
 *
 * The same four steps the browser asks in the same order — where and what it
 * is, who was paid and out of what, the lines, then the bill and the sentence
 * — because the two screens are filled in by the same people and one of them
 * teaching a different order is how a register ends up with two habits.
 *
 * What is different is the shape, not the questions. A phone has no grid, so a
 * line is a card that opens in a sheet; a phone has a camera, so the bill is
 * photographed at the counter rather than found on a disk later. The cash box
 * and what it holds sit at the top, because the answer to "can I pay this out
 * of petty cash" is the first thing anybody standing at a counter needs.
 *
 * Nothing here decides anything: the save goes to the web module's own view,
 * which runs the same validation, the same cash check and the same posting.
 */
import { useQuery } from "@tanstack/react-query";
import React, { useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Image,
  Modal,
  Pressable,
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import {
  attachPettyBills,
  getPettyExpense,
  PettyExpenseInput,
  PettyItemInput,
  PettyMasters,
  pettyMasters,
  savePettyExpense,
} from "@/api/pettyExpenses";
import { capturePhoto, CapturedImage, CapturePermissionError, pickPhoto } from "@/capture";
import {
  isoDate,
  lineAmount as amountOf,
  pettyIcon,
  pettyMoney as money,
} from "@/domain/pettyExpense";
import { AppIcon, IconName } from "@/components/AppIcon";
import { DateField } from "@/components/DateField";
import { Card, Screen, SearchBar } from "@/components/ui";
import { makeStyles, radius, shadow, spacing, type, withAlpha } from "@/theme";
import { useTheme } from "@/theme/ThemeProvider";

interface Props {
  route?: { params?: { id?: number } };
  navigation: { goBack: () => void };
}

interface Option {
  value: string;
  label: string;
}

/** A line being typed, before it is worth sending. */
interface Line extends PettyItemInput {
  /** What the pickers show, so a card reads without looking anything up. */
  categoryLabel: string;
  subLabel: string;
}

const BLANK: Line = {
  account: "",
  description: "",
  quantity: "1",
  uom: "",
  rate: "",
  categoryLabel: "",
  subLabel: "",
};

export function PettyExpenseFormScreen({ route, navigation }: Props) {
  const styles = useStyles();
  const { colors } = useTheme();
  const id = route?.params?.id;

  const masters = useQuery({ queryKey: ["petty-masters"], queryFn: pettyMasters });
  const M = masters.data;

  const [date, setDate] = useState(isoDate(new Date()));
  const [branch, setBranch] = useState("");
  const [farm, setFarm] = useState("");
  const [unitKind, setUnitKind] = useState<"shed" | "batch">("shed");
  const [unit, setUnit] = useState("");
  const [centre, setCentre] = useState("");
  const [reference, setReference] = useState("");
  const [mode, setMode] = useState("");
  const [paidFrom, setPaidFrom] = useState("");
  const [paidTo, setPaidTo] = useState("");
  const [lines, setLines] = useState<Line[]>([]);
  const [bills, setBills] = useState<CapturedImage[]>([]);
  const [narration, setNarration] = useState("");
  const [narrationTouched, setTouched] = useState(false);
  const [editing, setEditing] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [readOnly, setReadOnly] = useState(false);
  const [problem, setProblem] = useState("");

  /* -- what the pickers hold ----------------------------------------- */

  const branches: Option[] = useMemo(
    () => (M?.branches ?? []).map((b) => ({ value: String(b.id), label: b.branch_name })),
    [M]
  );
  const farms: Option[] = useMemo(
    () =>
      (M?.farms ?? [])
        .filter((f) => !branch || String(f.branch_id) === branch)
        .map((f) => ({ value: String(f.id), label: f.farm_name })),
    [M, branch]
  );
  // Sheds and open batches are two answers to one question, so the switch
  // says which is being given rather than the list being read to find out.
  const units: Option[] = useMemo(() => {
    if (!farm) return [];
    const rows =
      unitKind === "shed"
        ? (M?.sheds ?? []).filter((s) => String(s.farm_id) === farm)
        : (M?.batches ?? []).filter((b) => String(b.farm_id) === farm);
    return rows.map((r) => ({ value: String(r.id), label: r.label }));
  }, [M, farm, unitKind]);
  const centres: Option[] = useMemo(
    () => (M?.centres ?? []).map((c) => ({ value: String(c.id), label: c.name })),
    [M]
  );
  const modes: Option[] = useMemo(
    () => (M?.modes ?? []).map((m) => ({ value: String(m.id), label: m.name })),
    [M]
  );
  const accounts: Option[] = useMemo(
    () => (M?.paid_from ?? []).map((a) => ({ value: String(a.id), label: a.label })),
    [M]
  );
  const box = (M?.paid_from ?? []).find((a) => String(a.id) === paidFrom);

  const subtotal = lines.reduce((sum, line) => sum + amountOf(line), 0);

  /* -- opening a saved expense --------------------------------------- */

  useEffect(() => {
    if (!id || !M) return;
    let alive = true;
    getPettyExpense(id).then((d) => {
      if (!alive) return;
      const data = d as Record<string, any>;
      setDate(String(data.expense_date ?? isoDate(new Date())));
      setBranch(data.branch ? String(data.branch) : "");
      setFarm(data.farm ? String(data.farm) : "");
      setUnitKind(data.batch ? "batch" : "shed");
      setUnit(data.batch ? String(data.batch) : data.shed ? String(data.shed) : "");
      setCentre(data.cost_centre ? String(data.cost_centre) : "");
      setReference(String(data.reference ?? ""));
      setMode(data.payment_mode ? String(data.payment_mode) : "");
      setPaidFrom(data.paid_from ? String(data.paid_from) : "");
      setPaidTo(String(data.paid_to_name ?? ""));
      setNarration(String(data.narration ?? ""));
      setTouched(true);
      setReadOnly(!data.editable);
      const groups = M.categories;
      setLines(
        (data.items ?? []).map((item: Record<string, any>) => {
          const group = groups.find((c) => c.items.some((i) => i.id === item.account));
          const leaf = group?.items.find((i) => i.id === item.account);
          return {
            account: String(item.account ?? ""),
            description: String(item.description ?? ""),
            quantity: String(item.quantity ?? "1"),
            uom: item.uom ? String(item.uom) : "",
            rate: String(item.rate ?? "0"),
            categoryLabel: group?.name ?? "",
            subLabel: leaf?.name ?? "",
          };
        })
      );
    });
    return () => {
      alive = false;
    };
  }, [id, M]);

  /* -- a branch that is the only one is not a question ---------------- */

  useEffect(() => {
    if (!M || id) return;
    if (!branch && M.branches.length === 1) setBranch(String(M.branches[0].id));
    if (!mode && M.modes.length === 1) setMode(String(M.modes[0].id));
    const cash = M.paid_from.filter((a) => a.is_cash);
    if (!paidFrom && cash.length === 1) setPaidFrom(String(cash[0].id));
  }, [M, id, branch, mode, paidFrom]);

  /* -- the branch carries its centre ---------------------------------- */

  useEffect(() => {
    if (!M || !branch) return;
    const own = M.centres.find((c) => String(c.branch_id) === branch);
    setCentre((was) => (was ? was : own ? String(own.id) : ""));
  }, [M, branch]);

  /* -- the sentence, until somebody writes their own ------------------- */

  useEffect(() => {
    if (narrationTouched) return;
    const what = lines.length === 1 ? lines[0].description : `${lines.length} items`;
    const where =
      farms.find((f) => f.value === farm)?.label ||
      branches.find((b) => b.value === branch)?.label ||
      "";
    const named = units.find((u) => u.value === unit)?.label;
    const place = where ? ` at ${where}${named ? `, ${named.split(" · ")[0]}` : ""}` : "";
    const payee = paidTo.trim() ? ` to ${paidTo.trim()}` : "";
    const from = box ? `, paid through ${box.label}` : "";
    setNarration(
      `Petty expense for ${what || "sundry items"}${place}${payee}${from}.`
    );
  }, [lines, farm, branch, unit, paidTo, box, narrationTouched, farms, branches, units]);

  /* -- the bill, photographed at the counter --------------------------- */

  async function addBill(from: "camera" | "library") {
    try {
      const picked = from === "camera" ? await capturePhoto() : await pickPhoto();
      if (picked) setBills((was) => [...was, picked]);
    } catch (e) {
      if (e instanceof CapturePermissionError) {
        Alert.alert(
          "Permission needed",
          from === "camera"
            ? "Allow the camera to photograph a bill."
            : "Allow photo access to attach a bill."
        );
        return;
      }
      Alert.alert("That did not work", "The picture could not be added.");
    }
  }

  /* -- saving ---------------------------------------------------------- */

  function body(post: boolean): PettyExpenseInput {
    return {
      expense_date: date,
      branch,
      farm,
      shed: unitKind === "shed" ? unit : "",
      batch: unitKind === "batch" ? unit : "",
      cost_centre: centre,
      paid_to_name: paidTo,
      payment_mode: mode,
      paid_from: paidFrom,
      reference,
      narration,
      items: lines.map((l) => ({
        account: l.account,
        description: l.description,
        quantity: l.quantity,
        uom: l.uom,
        rate: l.rate,
      })),
      post,
    };
  }

  async function save(post: boolean) {
    setProblem("");
    setSaving(true);
    try {
      const saved = await savePettyExpense(body(post), id);
      // A new expense has nothing to attach a bill to until it exists.
      if (bills.length) {
        const form = new FormData();
        bills.forEach((b) =>
          form.append("files", {
            uri: b.uri,
            name: b.name,
            type: b.mimeType,
          } as unknown as Blob)
        );
        try {
          await attachPettyBills(saved.id, form);
        } catch {
          Alert.alert("Saved, without its bills", "The expense saved; its pictures did not.");
        }
      }
      Alert.alert(
        post ? "Posted" : "Draft saved",
        post
          ? `${saved.expense_no} posted as ${saved.voucher_no}.`
          : `${saved.expense_no} saved. It is not on the books until it is posted.`
      );
      navigation.goBack();
    } catch (e) {
      // The web view's own refusal, in its own words.
      const detail = (e as { response?: { data?: { error?: { message?: string } } } })
        ?.response?.data?.error?.message;
      setProblem(detail || "It could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  if (masters.isLoading) {
    return (
      <Screen>
        <View style={styles.centre}>
          <ActivityIndicator />
          <Text style={styles.muted}>Reading the masters</Text>
        </View>
      </Screen>
    );
  }

  return (
    <Screen>
      <ScrollView contentContainerStyle={styles.page} keyboardShouldPersistTaps="handled">
        {/* The box, and what it holds: the first thing anybody at a counter
            needs to know is whether this can come out of petty cash. */}
        <Card style={styles.box}>
          <View style={[styles.boxIcon, { backgroundColor: withAlpha(colors.success, 0.14) }]}>
            <AppIcon name="cash" size={18} color={colors.success} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.boxName} numberOfLines={1}>
              {box?.label ?? "Choose the account below"}
            </Text>
            <Text style={styles.muted}>Available balance</Text>
          </View>
          <Text style={[styles.boxAmount, subtotal > (box?.balance ?? 0) && { color: colors.danger }]}>
            {money(box?.balance ?? 0)}
          </Text>
        </Card>

        {readOnly ? (
          <Card style={styles.noteCard}>
            <Text style={styles.note}>
              This one is posted or cancelled, so it is shown as it stands.
            </Text>
          </Card>
        ) : null}

        <Section step={1} title="Expense Information">
          <Field label="Date" required>
            {/* No future date: a petty expense is written when the money
                leaves, and tomorrow has not happened. */}
            <DateField value={date} maximumDate={new Date()} onChange={setDate} />
          </Field>
          <Field label="Branch" required>
            <Picker
              title="Branch"
              value={branch}
              options={branches}
              onChange={(v) => {
                setBranch(v);
                setFarm("");
                setUnit("");
              }}
            />
          </Field>
          <Field label="Farm / Location" hint="Leave it empty to keep the expense on the branch itself.">
            <Picker
              title="Farm"
              value={farm}
              options={farms}
              allowEmpty
              emptyLabel="–"
              disabled={!branch}
              onChange={(v) => {
                setFarm(v);
                setUnit("");
              }}
            />
          </Field>
          <Field label="Shed / Unit">
            <View style={styles.kinds}>
              {(["shed", "batch"] as const).map((kind) => (
                <Pressable
                  key={kind}
                  style={[styles.kind, unitKind === kind && styles.kindOn]}
                  disabled={!farm}
                  onPress={() => {
                    setUnitKind(kind);
                    setUnit("");
                  }}
                >
                  <Text style={[styles.kindText, unitKind === kind && styles.kindTextOn]}>
                    {kind === "shed" ? "Shed" : "Batch"}
                  </Text>
                </Pressable>
              ))}
            </View>
            <Picker
              title={unitKind === "shed" ? "Shed / Unit" : "Active batch"}
              value={unit}
              options={units}
              allowEmpty
              emptyLabel="–"
              disabled={!farm || units.length === 0}
              onChange={setUnit}
            />
          </Field>
          <Field label="Cost Centre">
            <Picker title="Cost Centre" value={centre} options={centres} allowEmpty onChange={setCentre} />
          </Field>
          <Field label="Reference No.">
            <TextInput
              style={styles.input}
              value={reference}
              onChangeText={setReference}
              placeholder="Bill / voucher no."
              placeholderTextColor={colors.textFaint}
            />
          </Field>
        </Section>

        <Section step={2} title="Payment Information">
          <Field label="Payment Mode" required>
            <Picker title="Payment Mode" value={mode} options={modes} onChange={setMode} />
          </Field>
          <Field label="Paid From" required>
            <Picker title="Paid From" value={paidFrom} options={accounts} onChange={setPaidFrom} />
          </Field>
          <Field label="Paid To" required>
            <TextInput
              style={styles.input}
              value={paidTo}
              onChangeText={setPaidTo}
              placeholder="Name on the voucher"
              placeholderTextColor={colors.textFaint}
            />
          </Field>
        </Section>

        <Section
          step={3}
          title="Expense Items"
          action={
            readOnly ? undefined : (
              <Pressable style={styles.addItem} onPress={() => setEditing(lines.length)}>
                <AppIcon name="plus" size={14} color={colors.tint} />
                <Text style={styles.addItemText}>Add Item</Text>
              </Pressable>
            )
          }
        >
          {lines.length === 0 ? (
            <Text style={styles.muted}>Nothing on it yet. Add what was bought.</Text>
          ) : (
            lines.map((line, index) => (
              <Pressable
                key={index}
                style={styles.line}
                onPress={() => !readOnly && setEditing(index)}
              >
                <Text style={styles.lineNo}>{index + 1}</Text>
                <View style={[styles.lineIcon, { backgroundColor: withAlpha(colors.tint, 0.1) }]}>
                  <AppIcon name={pettyIcon(line.categoryLabel, line.subLabel, line.description)} size={16} color={colors.tint} />
                </View>
                <View style={{ flex: 1, minWidth: 0 }}>
                  <Text style={styles.lineTitle} numberOfLines={1}>
                    {line.subLabel || line.categoryLabel || "Not classified"}
                  </Text>
                  <Text style={styles.muted} numberOfLines={1}>
                    {line.description || "—"}
                  </Text>
                </View>
                <View style={{ alignItems: "flex-end" }}>
                  <Text style={styles.lineAmount}>{money(amountOf(line))}</Text>
                  <Text style={styles.muted}>
                    {line.quantity} × {Number(line.rate || 0).toFixed(2)}
                  </Text>
                </View>
              </Pressable>
            ))
          )}
        </Section>

        <Section step={4} title="Attachments & Notes">
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
              </>
            ) : null}
            {bills.map((bill, index) => (
              <View key={bill.uri} style={styles.bill}>
                <Image source={{ uri: bill.uri }} style={styles.billImage} />
                <Pressable
                  style={styles.billX}
                  onPress={() => setBills((was) => was.filter((_, i) => i !== index))}
                >
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
          <View style={{ flex: 1 }}>
            <Text style={styles.muted}>Total expense</Text>
            <Text style={styles.total}>{money(subtotal)}</Text>
          </View>
          <Pressable
            style={[styles.footBtn, styles.draftBtn]}
            disabled={saving}
            onPress={() => save(false)}
          >
            <Text style={styles.draftText}>Save Draft</Text>
          </Pressable>
          <Pressable
            style={[styles.footBtn, styles.postBtn]}
            disabled={saving}
            onPress={() => save(true)}
          >
            {saving ? (
              <ActivityIndicator color={colors.onDark} />
            ) : (
              <Text style={styles.postText}>Save &amp; Post</Text>
            )}
          </Pressable>
        </View>
      ) : null}

      {editing !== null && M ? (
        <LineEditor
          masters={M}
          line={lines[editing] ?? BLANK}
          isNew={editing >= lines.length}
          onClose={() => setEditing(null)}
          onRemove={() => {
            setLines((was) => was.filter((_, i) => i !== editing));
            setEditing(null);
          }}
          onSave={(line) => {
            setLines((was) => {
              const next = [...was];
              next[editing] = line;
              return next;
            });
            setEditing(null);
          }}
        />
      ) : null}
    </Screen>
  );
}

/* ------------------------------------------------------------------ */
/* One line, edited in a sheet                                         */
/* ------------------------------------------------------------------ */

function LineEditor({
  masters,
  line,
  isNew,
  onSave,
  onRemove,
  onClose,
}: {
  masters: PettyMasters;
  line: Line;
  isNew: boolean;
  onSave: (line: Line) => void;
  onRemove: () => void;
  onClose: () => void;
}) {
  const styles = useStyles();
  const { colors } = useTheme();
  const [draft, setDraft] = useState<Line>(line);

  // Either column first: the sub categories of one group when a group is
  // named, all of them under their own headings when none is.
  const group = masters.categories.find((c) => c.name === draft.categoryLabel);
  const subs: Option[] = useMemo(() => {
    const rows = group
      ? group.items.map((i) => ({ value: String(i.id), label: i.name }))
      : masters.categories.flatMap((c) =>
          c.items.map((i) => ({ value: String(i.id), label: `${i.name}  ·  ${c.name}` }))
        );
    return rows;
  }, [group, masters]);

  const categories: Option[] = masters.categories.map((c) => ({
    value: c.name,
    label: c.name,
  }));
  const uoms: Option[] = masters.uoms.map((u) => ({ value: String(u.id), label: u.name }));

  function pickSub(value: string) {
    // Naming the sub category names its category too: it is not a second
    // question, it is already known.
    const owner = masters.categories.find((c) =>
      c.items.some((i) => String(i.id) === value)
    );
    const leaf = owner?.items.find((i) => String(i.id) === value);
    setDraft((d) => ({
      ...d,
      account: value,
      subLabel: leaf?.name ?? "",
      categoryLabel: owner?.name ?? d.categoryLabel,
    }));
  }

  const amount = amountOf(draft);
  const ready = !!draft.account && !!draft.description.trim() && amount > 0;

  return (
    <Modal visible animationType="slide" onRequestClose={onClose} transparent>
      <View style={styles.sheetBack}>
        <SafeAreaView style={styles.sheet} edges={["bottom"]}>
          <View style={styles.sheetHead}>
            <Text style={styles.sheetTitle}>{isNew ? "Add item" : "Edit item"}</Text>
            <Pressable onPress={onClose} hitSlop={12}>
              <Text style={styles.sheetClose}>Close</Text>
            </Pressable>
          </View>
          <ScrollView contentContainerStyle={styles.sheetBody} keyboardShouldPersistTaps="handled">
            <Field label="Category">
              <Picker
                title="Category"
                value={draft.categoryLabel}
                options={categories}
                allowEmpty
                emptyLabel="All categories"
                onChange={(v) =>
                  setDraft((d) => ({
                    ...d,
                    categoryLabel: v,
                    // A sub category from another group is not this group's
                    // answer, so it is let go rather than left wrong.
                    account: v && group?.name !== v ? "" : d.account,
                    subLabel: v && group?.name !== v ? "" : d.subLabel,
                  }))
                }
              />
            </Field>
            <Field label="Sub Category" required>
              <Picker title="Sub Category" value={draft.account} options={subs} onChange={pickSub} />
            </Field>
            <Field label="Description" required>
              <TextInput
                style={styles.input}
                value={draft.description}
                onChangeText={(v) => setDraft((d) => ({ ...d, description: v }))}
                placeholder="What it was for"
                placeholderTextColor={colors.textFaint}
              />
            </Field>
            <View style={styles.pair}>
              <Field label="Qty" style={{ flex: 1 }}>
                <TextInput
                  style={styles.input}
                  value={draft.quantity}
                  onChangeText={(v) => setDraft((d) => ({ ...d, quantity: v }))}
                  keyboardType="decimal-pad"
                />
              </Field>
              <Field label="Unit" style={{ flex: 1 }}>
                <Picker
                  title="Unit"
                  value={draft.uom ?? ""}
                  options={uoms}
                  allowEmpty
                  emptyLabel="—"
                  onChange={(v) => setDraft((d) => ({ ...d, uom: v }))}
                />
              </Field>
            </View>
            <View style={styles.pair}>
              <Field label="Rate" style={{ flex: 1 }} required>
                <TextInput
                  style={styles.input}
                  value={draft.rate}
                  onChangeText={(v) => setDraft((d) => ({ ...d, rate: v }))}
                  keyboardType="decimal-pad"
                  placeholder="0.00"
                  placeholderTextColor={colors.textFaint}
                />
              </Field>
              <Field label="Amount" style={{ flex: 1 }}>
                {/* Computed, never typed: an amount that disagrees with its
                    own qty and rate is a line nobody can check. */}
                <View style={[styles.input, styles.amountBox]}>
                  <Text style={styles.amountText}>{money(amount)}</Text>
                </View>
              </Field>
            </View>
          </ScrollView>
          <View style={styles.sheetFoot}>
            {!isNew ? (
              <Pressable style={[styles.footBtn, styles.removeBtn]} onPress={onRemove}>
                <Text style={styles.removeText}>Remove</Text>
              </Pressable>
            ) : null}
            <Pressable
              style={[styles.footBtn, styles.postBtn, !ready && styles.disabled]}
              disabled={!ready}
              onPress={() => onSave(draft)}
            >
              <Text style={styles.postText}>{isNew ? "Add" : "Save"}</Text>
            </Pressable>
          </View>
        </SafeAreaView>
      </View>
    </Modal>
  );
}

/* ------------------------------------------------------------------ */
/* Small pieces                                                        */
/* ------------------------------------------------------------------ */

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
  hint,
  style,
  children,
}: {
  label: string;
  required?: boolean;
  hint?: string;
  style?: object;
  children: React.ReactNode;
}) {
  const styles = useStyles();
  const { colors } = useTheme();
  return (
    <View style={[styles.field, style]}>
      <Text style={styles.label}>
        {label}
        {required ? <Text style={{ color: colors.danger }}> *</Text> : null}
      </Text>
      {children}
      {hint ? <Text style={styles.hint}>{hint}</Text> : null}
    </View>
  );
}

function Picker({
  title,
  value,
  options,
  onChange,
  allowEmpty,
  emptyLabel = "None",
  disabled,
}: {
  title: string;
  value: string;
  options: Option[];
  onChange: (value: string) => void;
  allowEmpty?: boolean;
  emptyLabel?: string;
  disabled?: boolean;
}) {
  const styles = useStyles();
  const { colors } = useTheme();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? options.filter((o) => o.label.toLowerCase().includes(q)) : options;
  }, [options, query]);

  const label = options.find((o) => o.value === value)?.label;

  return (
    <>
      <Pressable
        style={[styles.input, styles.pick, disabled && styles.disabled]}
        disabled={disabled}
        onPress={() => setOpen(true)}
      >
        <Text style={label ? styles.pickText : styles.pickPlaceholder} numberOfLines={1}>
          {label ?? (allowEmpty ? emptyLabel : `Select ${title.toLowerCase()}`)}
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
          {options.length > 8 ? (
            <View style={{ paddingHorizontal: spacing.md }}>
              <SearchBar value={query} onChangeText={setQuery} placeholder={`Search ${title.toLowerCase()}`} />
            </View>
          ) : null}
          <ScrollView contentContainerStyle={{ padding: spacing.md }}>
            {allowEmpty ? (
              <Pressable
                style={styles.option}
                onPress={() => {
                  onChange("");
                  setOpen(false);
                }}
              >
                <Text style={styles.optionText}>{emptyLabel}</Text>
              </Pressable>
            ) : null}
            {shown.map((o) => (
              <Pressable
                key={o.value}
                style={styles.option}
                onPress={() => {
                  onChange(o.value);
                  setOpen(false);
                }}
              >
                <Text style={styles.optionText}>{o.label}</Text>
                {o.value === value ? (
                  <AppIcon name="check" size={16} color={colors.tint} />
                ) : null}
              </Pressable>
            ))}
            {shown.length === 0 ? <Text style={styles.hint}>Nothing to choose from.</Text> : null}
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

  box: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  boxIcon: {
    width: 36,
    height: 36,
    borderRadius: radius.sm,
    alignItems: "center",
    justifyContent: "center",
  },
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
  step: {
    width: 22,
    height: 22,
    borderRadius: 11,
    backgroundColor: colors.tint,
    alignItems: "center",
    justifyContent: "center",
  },
  stepText: { ...type.caption, color: colors.onDark, fontWeight: "700" },
  sectionTitle: { ...type.title, color: colors.text },
  sectionBody: { padding: spacing.md, gap: spacing.sm },

  field: { gap: 4 },
  label: { ...type.caption, color: colors.textMuted, fontWeight: "600" },
  hint: { ...type.caption, color: colors.textFaint },
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
  textarea: { minHeight: 84, textAlignVertical: "top" },
  pick: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  pickText: { ...type.body, color: colors.text, flex: 1 },
  pickPlaceholder: { ...type.body, color: colors.textFaint, flex: 1 },
  disabled: { opacity: 0.5 },

  kinds: {
    flexDirection: "row",
    alignSelf: "flex-start",
    borderWidth: 1,
    borderColor: colors.borderStrong,
    borderRadius: radius.sm,
    overflow: "hidden",
    marginBottom: 4,
  },
  kind: { paddingHorizontal: spacing.md, paddingVertical: 4 },
  kindOn: { backgroundColor: colors.tint },
  kindText: { ...type.caption, color: colors.textMuted, fontWeight: "700" },
  kindTextOn: { color: colors.onDark },

  addItem: { flexDirection: "row", alignItems: "center", gap: 4 },
  addItemText: { ...type.caption, color: colors.tint, fontWeight: "700" },

  line: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    padding: spacing.sm,
  },
  lineNo: { ...type.caption, color: colors.textFaint, width: 12 },
  lineIcon: {
    width: 32,
    height: 32,
    borderRadius: radius.sm,
    alignItems: "center",
    justifyContent: "center",
  },
  lineTitle: { ...type.title, color: colors.text },
  lineAmount: { ...type.title, color: colors.text },

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
  bill: { width: 72, height: 62 },
  billImage: { width: 72, height: 62, borderRadius: radius.sm },
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
    gap: spacing.sm,
    padding: spacing.md,
    backgroundColor: colors.surface,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  total: { ...type.h3, color: colors.success },
  footBtn: {
    paddingHorizontal: spacing.md,
    paddingVertical: 10,
    borderRadius: radius.sm,
    alignItems: "center",
    justifyContent: "center",
  },
  draftBtn: { borderWidth: 1, borderColor: colors.tint },
  draftText: { ...type.caption, color: colors.tint, fontWeight: "700" },
  postBtn: { backgroundColor: colors.success },
  postText: { ...type.caption, color: colors.onDark, fontWeight: "700" },
  removeBtn: { borderWidth: 1, borderColor: colors.danger },
  removeText: { ...type.caption, color: colors.danger, fontWeight: "700" },

  sheetBack: { flex: 1, backgroundColor: "rgba(15,23,42,0.4)", justifyContent: "flex-end" },
  sheet: {
    backgroundColor: colors.bg,
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    maxHeight: "88%",
  },
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
  sheetBody: { padding: spacing.md, gap: spacing.sm },
  sheetFoot: {
    flexDirection: "row",
    justifyContent: "flex-end",
    gap: spacing.sm,
    padding: spacing.md,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  pair: { flexDirection: "row", gap: spacing.sm },
  amountBox: { justifyContent: "center", backgroundColor: colors.successLight },
  amountText: { ...type.body, color: colors.success, fontWeight: "700" },

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
