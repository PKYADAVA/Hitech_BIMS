/**
 * Petty Expenses — the register on the phone.
 *
 * The same register the browser shows, read the way a phone is read: the
 * figures first, then the filters that narrow them, then the day's rows. The
 * rows and the figures come from one call, because a total counted separately
 * from its list is a total that can disagree with it.
 *
 * The filter strip asks the ERP's questions, in the ERP's order, with the
 * ERP's defaults — the window opens on the last seven days, a figure narrows
 * to what it counts, and letting it go puts the window back. The common seven
 * are on show and the rarer six sit behind "More filters", which is the split
 * the web strip makes. Anything else would be one product answering the same
 * question two ways depending on which screen you happened to open.
 */
import { useQuery } from "@tanstack/react-query";
import React, { useMemo, useState } from "react";
import {
  Modal,
  Pressable,
  RefreshControl,
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import {
  CashBox,
  listPettyExpenses,
  PettyCards,
  pettyMasters,
  PettyRow,
} from "@/api/pettyExpenses";
import { AppIcon, IconName } from "@/components/AppIcon";
import { DateField } from "@/components/DateField";
import {
  Badge,
  BadgeTone,
  Card,
  EmptyOrError,
  Loading,
  Screen,
  SearchBar,
} from "@/components/ui";
import {
  MONTHS,
  openingStrip,
  pettyIcon,
  pettyMoney as money,
  pettyQuery,
  PettyStrip,
  PettyTile,
  pettyTileStrip,
} from "@/domain/pettyExpense";
import { ModuleStackParams } from "@/navigation/types";
import { makeStyles, radius, shadow, spacing, type, withAlpha } from "@/theme";
import { useTheme } from "@/theme/ThemeProvider";

type Nav = {
  navigate: <K extends keyof ModuleStackParams>(
    screen: K,
    params?: ModuleStackParams[K]
  ) => void;
};

interface Option {
  value: string;
  label: string;
}

const STATUS_TONE: Record<PettyRow["status"], BadgeTone> = {
  Posted: "success",
  Draft: "warning",
  Cancelled: "danger",
};

const STATUSES: Option[] = [
  { value: "Draft", label: "Draft" },
  { value: "Posted", label: "Posted" },
  { value: "Cancelled", label: "Cancelled" },
];

export function PettyExpenseListScreen({ navigation }: { navigation: Nav }) {
  const styles = useStyles();
  const { colors } = useTheme();

  const [strip, setStrip] = useState<PettyStrip>(() => openingStrip());
  const [tile, setTile] = useState<PettyTile>("");
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState(true);
  const [more, setMore] = useState(false);

  // The pickers' options: the same masters the entry screen fills itself
  // from, so the two screens offer the same branches and the same ledgers.
  const masters = useQuery({ queryKey: ["petty-masters"], queryFn: pettyMasters });
  const M = masters.data;

  const query = useQuery({
    queryKey: ["petty-expenses", strip, search],
    queryFn: () => listPettyExpenses(pettyQuery(strip, search)),
  });

  const set = (patch: Partial<PettyStrip>) => {
    setStrip((was) => ({ ...was, ...patch }));
    // A strip answered by hand is no longer a figure's answer.
    setTile("");
  };

  const press = (pressed: PettyTile) => {
    setStrip((was) => pettyTileStrip(was, tile, pressed));
    setTile((was) => (was === pressed ? "" : pressed));
  };

  const clear = () => {
    setStrip(openingStrip());
    setSearch("");
    setTile("");
  };

  const branches: Option[] = (M?.branches ?? []).map((b) => ({
    value: String(b.id),
    label: b.branch_name,
  }));
  const farms: Option[] = (M?.farms ?? [])
    .filter((f) => !strip.branch || String(f.branch_id) === strip.branch)
    .map((f) => ({ value: String(f.id), label: f.farm_name }));
  // Every sub category under its own heading, which is how the web strip
  // offers them: a spend is looked up by what it was, not by its group.
  const accounts: Option[] = (M?.categories ?? []).flatMap((c) =>
    c.items.map((i) => ({ value: String(i.id), label: `${i.name}  ·  ${c.name}` }))
  );
  const centres: Option[] = (M?.centres ?? []).map((c) => ({
    value: String(c.id),
    label: c.name,
  }));
  const boxes: Option[] = (M?.paid_from ?? []).map((a) => ({
    value: String(a.id),
    label: a.label,
  }));
  const modes: Option[] = (M?.modes ?? []).map((m) => ({
    value: String(m.id),
    label: m.name,
  }));
  const months: Option[] = MONTHS.map((name, i) => ({ value: String(i + 1), label: name }));
  const years: Option[] = (M?.years ?? []).map((y) => ({
    value: String(y),
    label: String(y),
  }));

  const cards: PettyCards | undefined = query.data?.cards;
  const rows = query.data?.rows ?? [];
  const cash: CashBox[] = cards?.cash ?? [];

  return (
    <Screen>
      <ScrollView
        contentContainerStyle={styles.page}
        keyboardShouldPersistTaps="handled"
        refreshControl={
          <RefreshControl refreshing={query.isRefetching} onRefresh={() => query.refetch()} />
        }
      >
        <View style={styles.tiles}>
          <Tile
            label="Today"
            value={money(cards?.today ?? 0)}
            caption="Posted today"
            icon="calendar-today"
            accent={colors.tint}
            on={tile === "today"}
            onPress={() => press("today")}
          />
          <Tile
            label="This Month"
            value={money(cards?.month ?? 0)}
            caption="Posted this month"
            icon="calendar-month"
            accent={colors.info}
            on={tile === "month"}
            onPress={() => press("month")}
          />
          {/* One tile per cash box, as the web register shows them: each
              balance is read from that box's own ledger. */}
          {cash.map((c) => (
            <Tile
              key={c.id}
              label={c.label.split(" - ").slice(-1)[0]}
              value={money(c.balance)}
              caption={
                c.low
                  ? c.top_up > 0
                    ? `Low — ${money(c.top_up)} short`
                    : "Low"
                  : "Balance on its ledger"
              }
              icon="cash"
              accent={c.low ? colors.danger : colors.success}
              on={tile === `box:${c.id}`}
              onPress={() => press(`box:${c.id}`)}
            />
          ))}
          <Tile
            label="Drafts"
            value={String(cards?.drafts ?? 0)}
            caption="Waiting to be posted"
            icon="file-document-edit-outline"
            accent={colors.warning}
            on={tile === "drafts"}
            onPress={() => press("drafts")}
          />
        </View>

        <Pressable
          style={({ pressed }) => [styles.add, shadow(2), pressed && styles.addPressed]}
          onPress={() => navigation.navigate("PettyExpenseForm", {})}
        >
          <AppIcon name="plus" size={20} color={colors.onDark} />
          <Text style={styles.addText}>Add Petty Expense</Text>
        </Pressable>

        <SearchBar
          value={search}
          onChangeText={setSearch}
          placeholder="Expense no, payee or description"
        />

        <Card padded={false} style={styles.filterCard}>
          <Pressable style={styles.filterHead} onPress={() => setOpen((v) => !v)}>
            <AppIcon name="filter-variant" size={16} color={colors.tint} />
            <Text style={styles.filterTitle}>Quick Filters</Text>
            <View style={{ flex: 1 }} />
            <AppIcon
              name={open ? "chevron-up" : "chevron-down"}
              size={18}
              color={colors.textMuted}
            />
          </Pressable>

          {open ? (
            <View style={styles.filterBody}>
              {/* The question the register is read by: a window, not a preset. */}
              <View>
                <Text style={styles.label}>Expense date between</Text>
                <View style={styles.pair}>
                  <DateField
                    value={strip.from}
                    placeholder="On or after"
                    clearable
                    onChange={(v) => set({ from: v })}
                  />
                  <Text style={styles.sep}>to</Text>
                  <DateField
                    value={strip.to}
                    placeholder="On or before"
                    clearable
                    onChange={(v) => set({ to: v })}
                  />
                </View>
              </View>

              <View style={styles.pair}>
                <Pick
                  label="Month"
                  value={strip.month}
                  options={months}
                  onChange={(v) => set({ month: v })}
                />
                <Pick
                  label="Year"
                  value={strip.year}
                  options={years}
                  onChange={(v) => set({ year: v })}
                />
              </View>

              <View style={styles.pair}>
                <Pick
                  label="Branch"
                  value={strip.branch}
                  options={branches}
                  onChange={(v) => set({ branch: v, farm: "" })}
                />
                <Pick
                  label="Farm"
                  value={strip.farm}
                  options={farms}
                  onChange={(v) => set({ farm: v })}
                />
              </View>

              <Pick
                label="Sub Category"
                value={strip.account}
                options={accounts}
                onChange={(v) => set({ account: v })}
              />

              <View style={styles.pair}>
                <Pick
                  label="Status"
                  value={strip.status}
                  options={STATUSES}
                  onChange={(v) => set({ status: v })}
                />
                <Pick
                  label="Paid From"
                  value={strip.paid_from}
                  options={boxes}
                  onChange={(v) => set({ paid_from: v })}
                />
              </View>

              {more ? (
                <>
                  <View style={styles.pair}>
                    <Pick
                      label="Cost Centre"
                      value={strip.centre}
                      options={centres}
                      onChange={(v) => set({ centre: v })}
                    />
                    <Pick
                      label="Payment Mode"
                      value={strip.mode}
                      options={modes}
                      onChange={(v) => set({ mode: v })}
                    />
                  </View>
                  <Field
                    label="Paid To"
                    value={strip.paid_to}
                    placeholder="Any payee"
                    onChange={(v) => set({ paid_to: v })}
                  />
                  <View>
                    <Text style={styles.label}>Amount between</Text>
                    <View style={styles.pair}>
                      <Field
                        value={strip.min}
                        placeholder="0"
                        numeric
                        onChange={(v) => set({ min: v })}
                      />
                      <Text style={styles.sep}>to</Text>
                      <Field
                        value={strip.max}
                        placeholder="Any"
                        numeric
                        onChange={(v) => set({ max: v })}
                      />
                    </View>
                  </View>
                </>
              ) : null}

              <View style={styles.stripActions}>
                <Pressable style={styles.stripBtn} onPress={() => setMore((v) => !v)}>
                  <AppIcon
                    name={more ? "chevron-up" : "tune-variant"}
                    size={14}
                    color={colors.tint}
                  />
                  <Text style={styles.stripBtnText}>
                    {more ? "Fewer filters" : "More filters"}
                  </Text>
                </Pressable>
                <Pressable style={styles.stripBtn} onPress={clear}>
                  <AppIcon name="restore" size={14} color={colors.tint} />
                  <Text style={styles.stripBtnText}>Clear</Text>
                </Pressable>
              </View>
            </View>
          ) : null}
        </Card>

        <Text style={styles.count}>
          {query.isLoading
            ? "Loading…"
            : `Total: ${rows.length} ${rows.length === 1 ? "entry" : "entries"}`}
        </Text>

        {query.isLoading ? (
          <Loading label="Reading the register" />
        ) : query.isError ? (
          <EmptyOrError
            title="The register could not be read"
            message="Check the connection and pull to refresh."
            icon="alert-circle-outline"
          />
        ) : rows.length === 0 ? (
          <EmptyOrError
            title="Nothing in this window"
            message="Widen the dates, or add the first expense."
            icon="receipt"
          />
        ) : (
          rows.map((row) => (
            <Row
              key={row.id}
              row={row}
              onPress={() => navigation.navigate("PettyExpenseForm", { id: row.id })}
            />
          ))
        )}
      </ScrollView>
    </Screen>
  );
}

/* ------------------------------------------------------------------ */

function Tile({
  label,
  value,
  caption,
  icon,
  accent,
  on,
  onPress,
}: {
  label: string;
  value: string;
  caption: string;
  icon: IconName;
  accent: string;
  on: boolean;
  onPress: () => void;
}) {
  const styles = useStyles();
  return (
    <Pressable
      style={[styles.tile, shadow(1), on && { borderColor: accent, borderWidth: 1.5 }]}
      onPress={onPress}
      accessibilityRole="button"
      accessibilityState={{ selected: on }}
    >
      <View style={[styles.tileIcon, { backgroundColor: withAlpha(accent, 0.14) }]}>
        <AppIcon name={icon} size={16} color={accent} />
      </View>
      <Text style={styles.tileLabel} numberOfLines={1}>
        {label}
      </Text>
      <Text style={styles.tileValue} numberOfLines={1}>
        {value}
      </Text>
      <Text style={styles.tileCaption} numberOfLines={1}>
        {caption}
      </Text>
    </Pressable>
  );
}

/** A labelled picker whose blank answer is "all", as every strip control's is. */
function Pick({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: Option[];
  onChange: (value: string) => void;
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
    <View style={styles.half}>
      <Text style={styles.label}>{label}</Text>
      <Pressable style={styles.control} onPress={() => setOpen(true)}>
        <Text style={chosen ? styles.controlText : styles.controlBlank} numberOfLines={1}>
          {chosen ?? "All"}
        </Text>
        <AppIcon name="chevron-down" size={16} color={colors.textFaint} />
      </Pressable>

      <Modal visible={open} animationType="slide" onRequestClose={() => setOpen(false)}>
        <SafeAreaView style={styles.modal} edges={["top", "bottom"]}>
          <View style={styles.modalHead}>
            <Text style={styles.modalTitle}>{label}</Text>
            <Pressable onPress={() => setOpen(false)} hitSlop={12}>
              <Text style={styles.modalClose}>Close</Text>
            </Pressable>
          </View>
          {options.length > 8 ? (
            <View style={{ paddingHorizontal: spacing.md }}>
              <SearchBar
                value={query}
                onChangeText={setQuery}
                placeholder={`Search ${label.toLowerCase()}`}
              />
            </View>
          ) : null}
          <ScrollView contentContainerStyle={{ padding: spacing.md }}>
            <Pressable
              style={styles.option}
              onPress={() => {
                onChange("");
                setOpen(false);
              }}
            >
              <Text style={styles.optionText}>All</Text>
            </Pressable>
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
          </ScrollView>
        </SafeAreaView>
      </Modal>
    </View>
  );
}

function Field({
  label,
  value,
  placeholder,
  numeric,
  onChange,
}: {
  label?: string;
  value: string;
  placeholder: string;
  numeric?: boolean;
  onChange: (value: string) => void;
}) {
  const styles = useStyles();
  const { colors } = useTheme();
  return (
    <View style={styles.half}>
      {label ? <Text style={styles.label}>{label}</Text> : null}
      <View style={styles.control}>
        <TextInput
          style={styles.controlInput}
          value={value}
          onChangeText={onChange}
          placeholder={placeholder}
          placeholderTextColor={colors.textFaint}
          keyboardType={numeric ? "decimal-pad" : "default"}
        />
      </View>
    </View>
  );
}

function Row({ row, onPress }: { row: PettyRow; onPress: () => void }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const place = [row.branch, row.batch || row.shed || row.farm].filter(Boolean).join(" • ");
  return (
    <Card padded={false} style={styles.row} onPress={onPress}>
      <View style={[styles.rowIcon, { backgroundColor: withAlpha(colors.tint, 0.1) }]}>
        <AppIcon
          name={pettyIcon(row.category, row.sub_category, row.description)}
          size={18}
          color={colors.tint}
        />
      </View>
      <View style={styles.rowBody}>
        <Text style={styles.rowNo} numberOfLines={1}>
          {row.expense_no}
        </Text>
        <Text style={styles.rowMeta} numberOfLines={1}>
          {row.date}
        </Text>
        {place ? (
          <Text style={styles.rowMeta} numberOfLines={1}>
            {place}
          </Text>
        ) : null}
        <Text style={styles.rowWhat} numberOfLines={1}>
          {row.description || row.sub_category || row.paid_to}
        </Text>
      </View>
      <View style={styles.rowRight}>
        <Text style={styles.rowAmount}>{money(row.amount)}</Text>
        <Badge label={row.status} tone={STATUS_TONE[row.status]} />
        {row.bills?.length ? (
          <View style={styles.bill}>
            <AppIcon name="paperclip" size={11} color={colors.textMuted} />
            <Text style={styles.billText}>{row.bills.length}</Text>
          </View>
        ) : null}
      </View>
    </Card>
  );
}

const useStyles = makeStyles((colors) => ({
  page: { padding: spacing.md, paddingBottom: spacing.xxl, gap: spacing.sm },

  tiles: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  tile: {
    flexGrow: 1,
    flexBasis: "47%",
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.sm,
    gap: 2,
  },
  tileIcon: {
    width: 30,
    height: 30,
    borderRadius: radius.sm,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 2,
  },
  tileLabel: { ...type.caption, color: colors.textMuted },
  tileValue: { ...type.h3, color: colors.text },
  tileCaption: { ...type.caption, color: colors.textFaint },

  add: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.sm,
    backgroundColor: colors.success,
    borderRadius: radius.md,
    paddingVertical: spacing.md,
  },
  addPressed: { opacity: 0.9 },
  addText: { ...type.body, fontWeight: "700", color: colors.onDark },

  filterCard: { padding: 0 },
  filterHead: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    padding: spacing.md,
  },
  filterTitle: { ...type.body, fontWeight: "700", color: colors.text },
  filterBody: {
    paddingHorizontal: spacing.md,
    paddingBottom: spacing.md,
    paddingTop: spacing.sm,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    gap: spacing.sm,
  },
  label: { ...type.caption, color: colors.textMuted, fontWeight: "600", marginBottom: 2 },
  half: { flex: 1, minWidth: 0 },
  pair: { flexDirection: "row", alignItems: "flex-end", gap: spacing.sm },
  sep: { ...type.caption, color: colors.textMuted, paddingHorizontal: 2,
    paddingBottom: 10 },
  control: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: 9,
    backgroundColor: colors.surface,
    minHeight: 38,
  },
  controlText: { ...type.caption, color: colors.text, flex: 1 },
  controlBlank: { ...type.caption, color: colors.textFaint, flex: 1 },
  controlInput: { flex: 1, color: colors.text, fontSize: 13, padding: 0 },
  stripActions: { flexDirection: "row", justifyContent: "flex-end", gap: spacing.md },
  stripBtn: { flexDirection: "row", alignItems: "center", gap: 4, paddingVertical: 4 },
  stripBtnText: { ...type.caption, color: colors.tint, fontWeight: "700" },

  count: { ...type.caption, color: colors.textMuted, marginTop: spacing.xs },

  row: { flexDirection: "row", alignItems: "center", gap: spacing.sm, padding: spacing.sm },
  rowIcon: {
    width: 40,
    height: 40,
    borderRadius: radius.sm,
    alignItems: "center",
    justifyContent: "center",
  },
  rowBody: { flex: 1, minWidth: 0 },
  rowNo: { ...type.body, fontWeight: "700", color: colors.text },
  rowMeta: { ...type.caption, color: colors.textMuted },
  rowWhat: { ...type.caption, color: colors.text },
  rowRight: { alignItems: "flex-end", gap: 4 },
  rowAmount: { ...type.body, fontWeight: "700", color: colors.text },
  bill: { flexDirection: "row", alignItems: "center", gap: 2 },
  billText: { ...type.caption, color: colors.textMuted },

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
