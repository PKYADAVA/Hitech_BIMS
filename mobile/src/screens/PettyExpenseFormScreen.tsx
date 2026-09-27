/**
 * Add Petty Expense — the entry screen on the phone.
 *
 * The same four steps the browser asks in the same order — where and what it
 * is, who was paid and out of what, the lines, then the bill and the sentence
 * — because the two screens are filled in by the same people and one of them
 * teaching a different order is how a register ends up with two habits.
 *
 * What is different is the shape, not the questions. A phone has no room for
 * a grid, so the lines stack: the one being worked on is open with its fields
 * under it and the rest sit collapsed, which is the same row, folded. A line
 * has no Save of its own, as a grid row has none -- what is typed is what the
 * line says. A phone has a camera, so the bill is photographed at the counter
 * rather than found on a disk later. The cash box
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
  attachPettyBills,
  detachPettyBill,
  getPettyExpense,
  PettyRow,
  PettyExpenseInput,
  PettyItemInput,
  PettyMasters,
  pettyMasters,
  savePettyExpense,
} from "@/api/pettyExpenses";
import { capturePhoto, CapturedImage, CapturePermissionError, pickPhoto } from "@/capture";
import { confirm, notify } from "@/ui/confirm";
import {
  isoDate,
  lineAmount as amountOf,
  billUrl,
  pettyIcon,
  pettyMoney as money,
} from "@/domain/pettyExpense";
import { AppIcon, IconName } from "@/components/AppIcon";
import { DateField } from "@/components/DateField";
import { Card, Screen, SearchBar } from "@/components/ui";
import { makeStyles, radius, shadow, spacing, type, withAlpha } from "@/theme";
import { useTheme } from "@/theme/ThemeProvider";

interface Props {
  route?: { params?: { id?: number; copy?: number } };
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
  // A copy takes the spend and nothing that identifies the document:
  // its number, its date, its bill number and its bills stay with the
  // original, because the same spend happening again is not the same
  // document.
  const copyOf = route?.params?.copy;

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
  // Line 1 exists before anybody asks, as it does in the ERP's grid: an
  // expense is at least one thing bought, and an empty section with a
  // button on it says the opposite.
  const [lines, setLines] = useState<Line[]>([{ ...BLANK }]);
  const [bills, setBills] = useState<CapturedImage[]>([]);
  // Two kinds on one shelf: pictures taken in this sitting and not yet
  // sent, and the bills the expense already carries.
  const [saved, setSaved] = useState<PettyRow["bills"]>([]);
  const [narration, setNarration] = useState("");
  const [narrationTouched, setTouched] = useState(false);
  // Which line is open. Line 1 opens with the screen, as the ERP's grid
  // row does: there is no "open this row" step on a grid, you type into it.
  const [openLine, setOpenLine] = useState<number | null>(0);
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
    const from = id ?? copyOf;
    if (!from || !M) return;
    const asCopy = !id;
    let alive = true;
    getPettyExpense(from).then((d) => {
      if (!alive) return;
      const data = d as Record<string, any>;
      // Today's date on a copy, and its own number when it is saved.
      if (!asCopy) setDate(String(data.expense_date ?? isoDate(new Date())));
      setBranch(data.branch ? String(data.branch) : "");
      setFarm(data.farm ? String(data.farm) : "");
      setUnitKind(data.batch ? "batch" : "shed");
      setUnit(data.batch ? String(data.batch) : data.shed ? String(data.shed) : "");
      setCentre(data.cost_centre ? String(data.cost_centre) : "");
      setReference(asCopy ? "" : String(data.reference ?? ""));
      setMode(data.payment_mode ? String(data.payment_mode) : "");
      setPaidFrom(data.paid_from ? String(data.paid_from) : "");
      setPaidTo(String(data.paid_to_name ?? ""));
      // A copy writes its own sentence from what it now says.
      if (!asCopy) {
        setSaved(asCopy ? [] : ((data.attachments ?? []) as PettyRow["bills"]));
      setNarration(String(data.narration ?? ""));
        setTouched(true);
      }
      setReadOnly(!asCopy && !data.editable);
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
  }, [id, copyOf, M]);

  /* -- a branch that is the only one is not a question ---------------- */

  useEffect(() => {
    if (!M || id || copyOf) return;
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

  async function dropSaved(bill: PettyRow["bills"][number]) {
    if (!id) return;
    const ok = await confirm({
      title: `Remove ${bill.name}?`,
      message: "The picture is deleted. The expense keeps everything else.",
      confirmLabel: "Remove",
      cancelLabel: "Keep",
      destructive: true,
    });
    if (!ok) return;
    try {
      await detachPettyBill(id, bill.id);
      setSaved((was) => was.filter((b) => b.id !== bill.id));
    } catch (e) {
      // A posted expense keeps its evidence, and says so in its own words.
      const said = (e as { response?: { data?: { error?: { message?: string } } } })
        ?.response?.data?.error?.message;
      notify(said || "It could not be removed.");
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
      // The line that is drawn before anybody asks is a prompt, not an
      // answer: an untouched one is not sent, so the server is never asked
      // to refuse a line the user never typed.
      items: lines
        .filter((l) => l.account || l.description.trim())
        .map((l) => ({
          account: l.account,
          description: l.description,
          quantity: l.quantity,
          uom: l.uom,
          rate: l.rate,
        })),
      post,
    };
  }

  // Leaving with something typed is asked about once, as the web form asks:
  // nothing here is saved until a button says so, and a back gesture that
  // silently threw away a filled sheet would be the worse surprise.
  const typed = () =>
    !!paidTo.trim() ||
    !!reference.trim() ||
    bills.length > 0 ||
    lines.some((l) => l.account || l.description.trim() || Number(l.rate) > 0);

  async function leave() {
    if (!typed()) {
      navigation.goBack();
      return;
    }
    const ok = await confirm({
      title: id ? "Leave without saving your changes?" : "Leave without saving this expense?",
      message: "Anything typed here will be lost. Nothing has been saved yet.",
      confirmLabel: "Leave",
      cancelLabel: "Stay",
      destructive: true,
    });
    if (ok) navigation.goBack();
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
              <Pressable
                style={styles.addItem}
                onPress={() => {
                  setLines((was) => [...was, { ...BLANK }]);
                  setOpenLine(lines.length);
                }}
              >
                <AppIcon name="plus" size={14} color={colors.tint} />
                <Text style={styles.addItemText}>Add Item</Text>
              </Pressable>
            )
          }
        >
          {lines.length === 0 ? (
            <Text style={styles.muted}>Nothing on it yet. Add what was bought.</Text>
          ) : (
            lines.map((line, index) =>
              index === openLine && !readOnly ? (
                <LineFields
                  key={index}
                  masters={M}
                  line={line}
                  index={index}
                  canRemove={lines.length > 1}
                  onChange={(next) =>
                    setLines((was) => was.map((l, i) => (i === index ? next : l)))
                  }
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
                  index={index}
                  onPress={() => !readOnly && setOpenLine(index)}
                />
              )
            )
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
            {/* On file already: the photograph itself where there is one, a
                document mark where there is not. */}
            {saved.map((bill) => (
              <View key={`saved-${bill.id}`} style={styles.bill}>
                <Pressable
                  style={styles.billFace}
                  onPress={() => Linking.openURL(billUrl(bill.url)).catch(() => undefined)}
                  accessibilityLabel={`Open ${bill.name}`}
                >
                  {/^image/.test(bill.type || "") ? (
                    <Image source={{ uri: billUrl(bill.url) }} style={styles.billImage} />
                  ) : (
                    <AppIcon name="file-pdf-box" size={22} color={colors.danger} />
                  )}
                </Pressable>
                <Text style={styles.billName} numberOfLines={1}>
                  {bill.name}
                </Text>
                {!readOnly ? (
                  <Pressable style={styles.billX} onPress={() => dropSaved(bill)}>
                    <AppIcon name="close" size={10} color={colors.onDark} />
                  </Pressable>
                ) : null}
              </View>
            ))}
            {/* Taken here, not sent yet: they go up with the save. */}
            {bills.map((bill, index) => (
              <View key={bill.uri} style={styles.bill}>
                <View style={styles.billFace}>
                  <Image source={{ uri: bill.uri }} style={styles.billImage} />
                </View>
                <Text style={styles.billName} numberOfLines={1}>
                  {bill.name}
                </Text>
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
          <Pressable style={[styles.footBtn, styles.cancelBtn]} disabled={saving} onPress={leave}>
            <Text style={styles.cancelText}>Cancel</Text>
          </Pressable>
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

    </Screen>
  );
}

/* ------------------------------------------------------------------ */
/* One line                                                            */
/* ------------------------------------------------------------------ */

/** A line at rest: what it is, what it came to, and how that was reached. */
function LineCard({
  line,
  index,
  onPress,
}: {
  line: Line;
  index: number;
  onPress: () => void;
}) {
  const styles = useStyles();
  const { colors } = useTheme();
  // A line nobody has filled in yet says what it is for and where to press,
  // instead of pretending to hold a figure.
  const blank = !line.account && !line.description.trim();
  return (
    <Pressable style={[styles.line, blank && styles.lineBlank]} onPress={onPress}>
      <Text style={styles.lineNo}>{index + 1}</Text>
      <View
        style={[
          styles.lineIcon,
          { backgroundColor: blank ? colors.surfaceAlt : withAlpha(colors.tint, 0.1) },
        ]}
      >
        <AppIcon
          name={blank ? "plus" : pettyIcon(line.categoryLabel, line.subLabel, line.description)}
          size={16}
          color={blank ? colors.textMuted : colors.tint}
        />
      </View>
      <View style={{ flex: 1, minWidth: 0 }}>
        <Text style={[styles.lineTitle, blank && styles.lineTitleBlank]} numberOfLines={1}>
          {blank
            ? "Category, description, qty and rate"
            : line.subLabel || line.categoryLabel || "Not classified"}
        </Text>
        <Text style={styles.muted} numberOfLines={1}>
          {blank ? "Press to fill this line" : line.description || "\u2014"}
        </Text>
      </View>
      <View style={{ alignItems: "flex-end" }}>
        <Text style={[styles.lineAmount, blank && styles.lineTitleBlank]}>
          {money(amountOf(line))}
        </Text>
        {!blank ? (
          <Text style={styles.muted}>
            {line.quantity} × {Number(line.rate || 0).toFixed(2)}
          </Text>
        ) : null}
      </View>
    </Pressable>
  );
}

/**
 * A line, open.
 *
 * Typed into directly, with no Save of its own: a grid row has no such
 * button, and one here would leave a line that looks filled but is not.
 */
function LineFields({
  masters,
  line,
  index,
  canRemove,
  onChange,
  onRemove,
  onCollapse,
}: {
  masters?: PettyMasters;
  line: Line;
  index: number;
  /** The last line stays, as the ERP's grid keeps row 1. */
  canRemove: boolean;
  onChange: (line: Line) => void;
  onRemove: () => void;
  onCollapse: () => void;
}) {
  const styles = useStyles();
  const { colors } = useTheme();
  const groups = masters?.categories ?? [];

  // Either column first: the sub categories of one group when a group is
  // named, all of them under their own headings when none is.
  const group = groups.find((c) => c.name === line.categoryLabel);
  const subs: Option[] = useMemo(() => {
    return group
      ? group.items.map((i) => ({ value: String(i.id), label: i.name }))
      : groups.flatMap((c) =>
          c.items.map((i) => ({ value: String(i.id), label: `${i.name}  \u00b7  ${c.name}` }))
        );
  }, [group, groups]);

  const categories: Option[] = groups.map((c) => ({ value: c.name, label: c.name }));
  const uoms: Option[] = (masters?.uoms ?? []).map((u) => ({
    value: String(u.id),
    label: u.name,
  }));

  function pickSub(value: string) {
    // Naming the sub category names its category too: it is not a second
    // question, it is already known.
    const owner = groups.find((c) => c.items.some((i) => String(i.id) === value));
    const leaf = owner?.items.find((i) => String(i.id) === value);
    onChange({
      ...line,
      account: value,
      subLabel: leaf?.name ?? "",
      categoryLabel: owner?.name ?? line.categoryLabel,
    });
  }

  return (
    <View style={styles.lineOpen}>
      <View style={styles.lineOpenHead}>
        <Text style={styles.lineNo}>{index + 1}</Text>
        <Text style={styles.lineOpenTitle}>
          {line.subLabel || "This line"}
        </Text>
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

      <Field label="Category">
        <Picker
          title="Category"
          value={line.categoryLabel}
          options={categories}
          allowEmpty
          emptyLabel="All categories"
          onChange={(v) =>
            onChange({
              ...line,
              categoryLabel: v,
              // A sub category from another group is not this group's answer,
              // so it is let go rather than left wrong.
              account: v && group?.name !== v ? "" : line.account,
              subLabel: v && group?.name !== v ? "" : line.subLabel,
            })
          }
        />
      </Field>
      <Field label="Sub Category" required>
        <Picker title="Sub Category" value={line.account} options={subs} onChange={pickSub} />
      </Field>
      <Field label="Description" required>
        <TextInput
          style={styles.input}
          value={line.description}
          onChangeText={(v) => onChange({ ...line, description: v })}
          placeholder="What it was for"
          placeholderTextColor={colors.textFaint}
        />
      </Field>
      <View style={styles.pair}>
        <Field label="Qty" style={{ flex: 1 }}>
          <TextInput
            style={styles.input}
            value={line.quantity}
            onChangeText={(v) => onChange({ ...line, quantity: v })}
            keyboardType="decimal-pad"
          />
        </Field>
        <Field label="Unit" style={{ flex: 1 }}>
          <Picker
            title="Unit"
            value={line.uom ?? ""}
            options={uoms}
            allowEmpty
            emptyLabel="—"
            onChange={(v) => onChange({ ...line, uom: v })}
          />
        </Field>
      </View>
      <View style={styles.pair}>
        <Field label="Rate" style={{ flex: 1 }} required>
          <TextInput
            style={styles.input}
            value={line.rate}
            onChangeText={(v) => onChange({ ...line, rate: v })}
            keyboardType="decimal-pad"
            placeholder="0.00"
            placeholderTextColor={colors.textFaint}
          />
        </Field>
        <Field label="Amount" style={{ flex: 1 }}>
          {/* Computed, never typed: an amount that disagrees with its own
              qty and rate is a line nobody can check. */}
          <View style={[styles.input, styles.amountBox]}>
            <Text style={styles.amountText}>{money(amountOf(line))}</Text>
          </View>
        </Field>
      </View>
    </View>
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
  lineBlank: { borderStyle: "dashed", borderColor: colors.borderStrong,
    backgroundColor: colors.bg },
  lineOpen: { borderWidth: 1, borderColor: colors.tint, borderRadius: radius.sm,
    padding: spacing.sm, gap: spacing.sm, backgroundColor: colors.surface },
  lineOpenHead: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  lineOpenTitle: { ...type.title, color: colors.text },
  lineTool: { padding: 2 },
  lineTitleBlank: { color: colors.textMuted, fontWeight: "400" },
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
  bill: { width: 72 },
  billFace: { width: 72, height: 62, borderRadius: radius.sm, overflow: "hidden",
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceAlt,
    alignItems: "center", justifyContent: "center" },
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
    padding: spacing.md,
    backgroundColor: colors.surface,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  total: { ...type.h3, color: colors.success },
  footBtn: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 10,
    borderRadius: radius.sm,
    alignItems: "center",
    justifyContent: "center",
  },
  cancelBtn: { borderWidth: 1, borderColor: colors.border },
  cancelText: { ...type.caption, color: colors.textMuted, fontWeight: "700" },
  draftBtn: { borderWidth: 1, borderColor: colors.tint },
  draftText: { ...type.caption, color: colors.tint, fontWeight: "700" },
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
