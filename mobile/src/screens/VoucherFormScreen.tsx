/**
 * New Journal Voucher — writing an entry on the phone.
 *
 * A voucher is its lines, and the one thing it must do is balance. The screen
 * is built around that: every line says which account and which side, the two
 * totals sit under them with the difference between, and the difference is
 * something you can act on rather than only read — "Balance" puts what is
 * left on the line being typed, which is what the browser's form does with
 * Alt+B and what anybody doing this on paper does by subtraction.
 *
 * Each line is one side, because that is what a ledger line is: a debit or a
 * credit, never both. The web grid offers two columns and a blank in one of
 * them; a phone has no room for a column nobody fills, so the side is a
 * switch and the amount is one field.
 *
 * Nothing here decides anything. The engine refuses an unbalanced voucher, a
 * group account, an inactive one and a locked year; the screen's job is to
 * ask clearly and to show the refusal in the engine's own words.
 */
import { useQuery } from "@tanstack/react-query";
import React, { useMemo, useState } from "react";
import {
  ActivityIndicator,
  Modal,
  Pressable,
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import {
  getVoucher,
  saveVoucher,
  VoucherInput,
  VoucherMasters,
  voucherMasters,
} from "@/api/vouchers";
import { AppIcon, IconName } from "@/components/AppIcon";
import { DateField } from "@/components/DateField";
import { Card, Screen, SearchBar } from "@/components/ui";
import { isoDate, pettyMoney as money } from "@/domain/pettyExpense";
import { confirm } from "@/ui/confirm";
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

/** A line being typed: one account, one side, one amount. */
interface Line {
  account: string;
  accountLabel: string;
  side: "debit" | "credit";
  amount: string;
  narration: string;
}

const BLANK: Line = {
  account: "",
  accountLabel: "",
  side: "debit",
  amount: "",
  narration: "",
};

const amountOf = (line: Line) => Number(line.amount) || 0;

export function VoucherFormScreen({ route, navigation }: Props) {
  const styles = useStyles();
  const { colors } = useTheme();
  const id = route?.params?.id;

  const masters = useQuery({ queryKey: ["voucher-masters"], queryFn: voucherMasters });
  const M: VoucherMasters | undefined = masters.data;

  const [date, setDate] = useState(isoDate(new Date()));
  const [voucherType, setVoucherType] = useState("Journal");
  const [reference, setReference] = useState("");
  const [sector, setSector] = useState("");
  const [narration, setNarration] = useState("");
  // Two lines from the start: the smallest honest entry is one debit and one
  // credit, and a screen that opens on one is asking for half a voucher.
  const [lines, setLines] = useState<Line[]>([
    { ...BLANK, side: "debit" },
    { ...BLANK, side: "credit" },
  ]);
  const [openLine, setOpenLine] = useState<number | null>(0);
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState("");
  const [readOnly, setReadOnly] = useState(false);

  const accounts: Option[] = useMemo(
    () =>
      (M?.accounts ?? []).map((a) => ({
        value: String(a.id),
        label: `${a.code}  ·  ${a.name}`,
      })),
    [M]
  );
  const types: Option[] = (M?.types ?? []).map((t) => ({ value: t.value, label: t.label }));
  const sectors: Option[] = (M?.sectors ?? []).map((w) => ({
    value: String(w.id),
    label: w.name,
  }));

  /* -- opening a saved draft ------------------------------------------- */

  React.useEffect(() => {
    if (!id || !M) return;
    let alive = true;
    getVoucher(id).then((v) => {
      if (!alive) return;
      setDate(v.date);
      setVoucherType(v.voucher_type);
      setReference(v.reference ?? "");
      setSector(v.sector ? String(v.sector) : "");
      setNarration(v.narration ?? "");
      // Only a draft can be rewritten; anything else opens to be read.
      setReadOnly(v.status !== "Draft");
      setLines(
        (v.lines ?? []).map((line) => ({
          account: String(line.account),
          accountLabel: `${line.account_code}  ·  ${line.account_name}`,
          side: Number(line.debit) ? "debit" : "credit",
          amount: String(Number(line.debit) || Number(line.credit) || ""),
          narration: line.narration ?? "",
        }))
      );
      setOpenLine(null);
    });
    return () => {
      alive = false;
    };
  }, [id, M]);

  /* -- the two totals, and what is between them ------------------------ */

  const debit = lines
    .filter((l) => l.side === "debit")
    .reduce((sum, l) => sum + amountOf(l), 0);
  const credit = lines
    .filter((l) => l.side === "credit")
    .reduce((sum, l) => sum + amountOf(l), 0);
  const difference = Math.round((debit - credit) * 100) / 100;
  const balanced = difference === 0 && debit > 0;

  const setLine = (index: number, patch: Partial<Line>) =>
    setLines((was) => was.map((l, i) => (i === index ? { ...l, ...patch } : l)));

  /**
   * Put what is left on this line.
   *
   * The side follows the difference, not the line's current setting: if the
   * debits are short, the amount that completes the entry is a debit, and
   * making somebody work that out is making them do arithmetic the screen
   * has already done.
   */
  function balanceHere(index: number) {
    const line = lines[index];
    const without =
      (line.side === "debit" ? debit : credit) - amountOf(line);
    const otherSide = line.side === "debit" ? credit : debit;
    const needed = Math.round((otherSide - without) * 100) / 100;
    if (needed > 0) {
      setLine(index, { amount: needed.toFixed(2) });
      return;
    }
    // This side already carries more than the other: the shortfall belongs
    // on the opposite side, so the line changes sides to take it.
    const flipped = Math.round((without - otherSide + amountOf(line)) * 100) / 100;
    if (flipped > 0) {
      setLine(index, {
        side: line.side === "debit" ? "credit" : "debit",
        amount: flipped.toFixed(2),
      });
    }
  }

  /* -- leaving, and saving --------------------------------------------- */

  const typed = () =>
    !!narration.trim() ||
    !!reference.trim() ||
    lines.some((l) => l.account || amountOf(l) > 0);

  async function leave() {
    if (!typed()) {
      navigation.goBack();
      return;
    }
    const ok = await confirm({
      title: id ? "Leave without saving your changes?" : "Leave without saving this voucher?",
      message: "Anything typed here will be lost. Nothing has been saved yet.",
      confirmLabel: "Leave",
      cancelLabel: "Stay",
      destructive: true,
    });
    if (ok) navigation.goBack();
  }

  function body(post: boolean): VoucherInput {
    return {
      date,
      voucher_type: voucherType,
      narration: narration.trim(),
      reference: reference.trim(),
      sector: sector ? Number(sector) : null,
      // A line with no account is a line nobody typed, so it is not sent.
      lines: lines
        .filter((l) => l.account && amountOf(l) > 0)
        .map((l) => ({
          account: l.account,
          debit: l.side === "debit" ? l.amount : "0",
          credit: l.side === "credit" ? l.amount : "0",
          narration: l.narration.trim(),
        })),
      post,
    };
  }

  async function save(post: boolean) {
    setProblem("");
    setSaving(true);
    try {
      const saved = await saveVoucher(body(post), id);
      await confirmDone(
        post ? "Posted" : "Draft saved",
        post
          ? `${saved.voucher_no} posted.`
          : "Saved as a draft. It is not on the books until it is posted."
      );
      navigation.goBack();
    } catch (e) {
      // The engine's own refusal: unbalanced, a group account, a locked year.
      const said = (e as { response?: { data?: { error?: { message?: string } } } })
        ?.response?.data?.error?.message;
      setProblem(said || "It could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  if (masters.isLoading) {
    return (
      <Screen edges={["left", "right"]}>
        <View style={styles.centre}>
          <ActivityIndicator />
          <Text style={styles.muted}>Reading the chart of accounts</Text>
        </View>
      </Screen>
    );
  }

  return (
    <Screen edges={["left", "right"]}>
      <ScrollView contentContainerStyle={styles.page} keyboardShouldPersistTaps="handled">
        {/* What the entry must do, said at the top where it is read first. */}
        <Card style={balanced ? styles.balanceOk : styles.balance}>
          <View style={{ flex: 1 }}>
            <Text style={styles.muted}>Debit {money(debit)} · Credit {money(credit)}</Text>
            <Text style={[styles.balanceText, balanced && { color: colors.success }]}>
              {balanced
                ? "The entry balances"
                : difference === 0
                ? "Nothing entered yet"
                : `${money(Math.abs(difference))} ${
                    difference > 0 ? "more credit needed" : "more debit needed"
                  }`}
            </Text>
          </View>
          <AppIcon
            name={balanced ? "scale-balance" : "alert-circle-outline"}
            size={22}
            color={balanced ? colors.success : colors.warning}
          />
        </Card>

        {readOnly ? (
          <Card style={styles.noteCard}>
            <Text style={styles.note}>
              This one is posted or cancelled, so it is shown as it stands.
            </Text>
          </Card>
        ) : null}

        <Section step={1} title="Voucher">
          <Field label="Date" required>
            <DateField value={date} maximumDate={new Date()} onChange={setDate} />
          </Field>
          <View style={styles.pair}>
            <Field label="Type" required style={{ flex: 1 }}>
              <Pick title="Type" value={voucherType} options={types} onChange={setVoucherType} />
            </Field>
            <Field label="Sector" style={{ flex: 1 }}>
              <Pick title="Sector" value={sector} options={sectors} allowEmpty
                onChange={setSector} />
            </Field>
          </View>
          <Field label="Reference">
            <TextInput
              style={styles.input}
              value={reference}
              onChangeText={setReference}
              placeholder="Bill / cheque no."
              placeholderTextColor={colors.textFaint}
              editable={!readOnly}
            />
          </Field>
        </Section>

        <Section
          step={2}
          title="Lines"
          action={
            readOnly ? undefined : (
              <Pressable
                style={styles.addLine}
                onPress={() => {
                  setLines((was) => [...was, { ...BLANK }]);
                  setOpenLine(lines.length);
                }}
              >
                <AppIcon name="plus" size={14} color={colors.tint} />
                <Text style={styles.addLineText}>Add Line</Text>
              </Pressable>
            )
          }
        >
          {lines.map((line, index) =>
            index === openLine && !readOnly ? (
              <LineFields
                key={index}
                line={line}
                index={index}
                accounts={accounts}
                canRemove={lines.length > 2}
                onChange={(patch) => setLine(index, patch)}
                onRemove={() => {
                  setLines((was) => was.filter((_, i) => i !== index));
                  setOpenLine(null);
                }}
                onBalance={() => balanceHere(index)}
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
          )}

          <View style={styles.totals}>
            <Text style={[styles.totalLabel, { flex: 1 }]}>TOTAL</Text>
            <Text style={styles.total}>{money(debit)}</Text>
            <Text style={styles.total}>{money(credit)}</Text>
          </View>
        </Section>

        <Section step={3} title="Narration">
          <TextInput
            style={[styles.input, styles.textarea]}
            value={narration}
            onChangeText={setNarration}
            multiline
            placeholder="What this entry is for, as it should read in the ledger"
            placeholderTextColor={colors.textFaint}
            editable={!readOnly}
          />
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
            <Text style={styles.muted}>Entry</Text>
            <Text style={[styles.footTotal, !balanced && { color: colors.textMuted }]}>
              {money(debit)}
            </Text>
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
            style={[styles.footBtn, styles.postBtn, !balanced && styles.disabled]}
            disabled={saving || !balanced}
            onPress={() => save(true)}
          >
            {saving ? (
              <ActivityIndicator color={colors.onDark} />
            ) : (
              <Text style={styles.postText}>Post</Text>
            )}
          </Pressable>
        </View>
      ) : null}
    </Screen>
  );
}

/* ------------------------------------------------------------------ */

async function confirmDone(title: string, message: string) {
  const { notify } = require("@/ui/confirm") as typeof import("@/ui/confirm");
  notify(title, message);
}

/** A line at rest: the account, the side and the amount. */
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
  const blank = !line.account;
  return (
    <Pressable style={[styles.line, blank && styles.lineBlank]} onPress={onPress}>
      <Text style={styles.lineNo}>{index + 1}</Text>
      <View
        style={[
          styles.sideMark,
          {
            backgroundColor: blank
              ? colors.surfaceAlt
              : withAlpha(line.side === "debit" ? colors.tint : colors.accent, 0.14),
          },
        ]}
      >
        <Text
          style={[
            styles.sideMarkText,
            { color: blank ? colors.textMuted : line.side === "debit" ? colors.tint : colors.accent },
          ]}
        >
          {line.side === "debit" ? "Dr" : "Cr"}
        </Text>
      </View>
      <View style={{ flex: 1, minWidth: 0 }}>
        <Text style={[styles.lineTitle, blank && styles.lineBlankText]} numberOfLines={1}>
          {line.accountLabel || "Choose the account"}
        </Text>
        {line.narration ? (
          <Text style={styles.muted} numberOfLines={1}>
            {line.narration}
          </Text>
        ) : null}
      </View>
      <Text style={[styles.lineAmount, blank && styles.lineBlankText]}>
        {money(amountOf(line))}
      </Text>
    </Pressable>
  );
}

/** A line, open: typed into directly, as a grid row is. */
function LineFields({
  line,
  index,
  accounts,
  canRemove,
  onChange,
  onRemove,
  onBalance,
  onCollapse,
}: {
  line: Line;
  index: number;
  accounts: Option[];
  /** A voucher needs two sides, so the last pair stays. */
  canRemove: boolean;
  onChange: (patch: Partial<Line>) => void;
  onRemove: () => void;
  onBalance: () => void;
  onCollapse: () => void;
}) {
  const styles = useStyles();
  const { colors } = useTheme();
  return (
    <View style={styles.lineOpen}>
      <View style={styles.lineOpenHead}>
        <Text style={styles.lineNo}>{index + 1}</Text>
        <Text style={styles.lineOpenTitle}>This line</Text>
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

      <Field label="Account" required>
        <Pick
          title="Account"
          value={line.account}
          options={accounts}
          onChange={(value) =>
            onChange({
              account: value,
              accountLabel: accounts.find((a) => a.value === value)?.label ?? "",
            })
          }
        />
      </Field>

      <View style={styles.pair}>
        <Field label="Side" required style={{ flex: 1 }}>
          {/* One side per line, because that is what a ledger line is. */}
          <View style={styles.sides}>
            {(["debit", "credit"] as const).map((side) => (
              <Pressable
                key={side}
                style={[styles.side, line.side === side && styles.sideOn]}
                onPress={() => onChange({ side })}
              >
                <Text style={[styles.sideText, line.side === side && styles.sideTextOn]}>
                  {side === "debit" ? "Debit" : "Credit"}
                </Text>
              </Pressable>
            ))}
          </View>
        </Field>
        <Field label="Amount" required style={{ flex: 1 }}>
          <TextInput
            style={styles.input}
            value={line.amount}
            onChangeText={(v) => onChange({ amount: v })}
            keyboardType="decimal-pad"
            placeholder="0.00"
            placeholderTextColor={colors.textFaint}
          />
        </Field>
      </View>

      <Pressable style={styles.balanceBtn} onPress={onBalance}>
        <AppIcon name="scale-balance" size={14} color={colors.tint} />
        <Text style={styles.balanceBtnText}>Put what is left on this line</Text>
      </Pressable>

      <Field label="Line narration">
        <TextInput
          style={styles.input}
          value={line.narration}
          onChangeText={(v) => onChange({ narration: v })}
          placeholder="Optional"
          placeholderTextColor={colors.textFaint}
        />
      </Field>
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
  style,
  children,
}: {
  label: string;
  required?: boolean;
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
    </View>
  );
}

function Pick({
  title,
  value,
  options,
  onChange,
  allowEmpty,
}: {
  title: string;
  value: string;
  options: Option[];
  onChange: (value: string) => void;
  allowEmpty?: boolean;
}) {
  const styles = useStyles();
  const { colors } = useTheme();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? options.filter((o) => o.label.toLowerCase().includes(q)) : options;
  }, [options, query]);

  const chosen = options.find((o) => o.value === value)?.label;

  return (
    <>
      <Pressable style={[styles.input, styles.pick]} onPress={() => setOpen(true)}>
        <Text style={chosen ? styles.pickText : styles.pickBlank} numberOfLines={1}>
          {chosen ?? (allowEmpty ? "None" : `Select ${title.toLowerCase()}`)}
        </Text>
        <AppIcon name="chevron-down" size={18} color={colors.textFaint} />
      </Pressable>

      <Modal visible={open} animationType="slide" onRequestClose={() => setOpen(false)}>
        <SafeAreaView style={styles.modal} edges={["top", "bottom"]}>
          <View style={styles.modalHead}>
            <Text style={styles.modalTitle}>{title}</Text>
            <Pressable onPress={() => setOpen(false)} hitSlop={12}>
              <Text style={styles.modalClose}>Close</Text>
            </Pressable>
          </View>
          {options.length > 8 ? (
            <View style={{ paddingHorizontal: spacing.md }}>
              <SearchBar
                value={query}
                onChangeText={setQuery}
                placeholder={`Search ${title.toLowerCase()}`}
              />
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
                <Text style={styles.optionText}>None</Text>
              </Pressable>
            ) : null}
            {shown.map((o) => (
              <Pressable
                key={o.value}
                style={styles.option}
                onPress={() => {
                  onChange(o.value);
                  setOpen(false);
                  setQuery("");
                }}
              >
                <Text style={styles.optionText}>{o.label}</Text>
                {o.value === value ? (
                  <AppIcon name="check" size={16} color={colors.tint} />
                ) : null}
              </Pressable>
            ))}
            {shown.length === 0 ? (
              <Text style={styles.muted}>Nothing to choose from.</Text>
            ) : null}
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

  balance: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  // The same card, wearing the answer: a whole style rather than a pair,
  // because Card takes one.
  balanceOk: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    borderColor: colors.success,
    borderWidth: 1,
  },
  balanceText: { ...type.title, color: colors.warning },

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
  pair: { flexDirection: "row", gap: spacing.sm },
  input: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: 10,
    color: colors.text,
    backgroundColor: colors.surface,
    fontSize: 15,
    minHeight: 40,
  },
  textarea: { minHeight: 84, textAlignVertical: "top" },
  pick: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  pickText: { ...type.body, color: colors.text, flex: 1 },
  pickBlank: { ...type.body, color: colors.textFaint, flex: 1 },
  disabled: { opacity: 0.5 },

  addLine: { flexDirection: "row", alignItems: "center", gap: 4 },
  addLineText: { ...type.caption, color: colors.tint, fontWeight: "700" },

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
  lineBlankText: { color: colors.textMuted, fontWeight: "400" },
  lineNo: { ...type.caption, color: colors.textFaint, width: 12 },
  sideMark: {
    width: 34,
    height: 30,
    borderRadius: radius.sm,
    alignItems: "center",
    justifyContent: "center",
  },
  sideMarkText: { ...type.caption, fontWeight: "700" },
  lineTitle: { ...type.body, color: colors.text, fontWeight: "600" },
  lineAmount: { ...type.body, color: colors.text, fontWeight: "700" },

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

  sides: {
    flexDirection: "row",
    borderWidth: 1,
    borderColor: colors.borderStrong,
    borderRadius: radius.sm,
    overflow: "hidden",
    minHeight: 40,
  },
  side: { flex: 1, alignItems: "center", justifyContent: "center", paddingVertical: 8 },
  sideOn: { backgroundColor: colors.tint },
  sideText: { ...type.caption, color: colors.textMuted, fontWeight: "700" },
  sideTextOn: { color: colors.onDark },

  balanceBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    alignSelf: "flex-start",
    paddingVertical: 4,
  },
  balanceBtnText: { ...type.caption, color: colors.tint, fontWeight: "700" },

  totals: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingTop: spacing.sm,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  totalLabel: { ...type.caption, color: colors.textMuted, fontWeight: "700" },
  total: { ...type.body, color: colors.text, fontWeight: "700", width: 96, textAlign: "right" },

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
  footTotal: { ...type.h3, color: colors.success },
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

  modal: { flex: 1, backgroundColor: colors.bg },
  modalHead: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    padding: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  modalTitle: { ...type.h3, color: colors.text },
  modalClose: { ...type.body, color: colors.tint, fontWeight: "700" },
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
