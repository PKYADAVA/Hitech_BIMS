/**
 * Petty Expenses — the register on the phone.
 *
 * The same register the browser shows, read the way a phone is read: the
 * figures first, then the filters that narrow them, then the day's rows. Both
 * come from one call, because a total counted separately from its list is a
 * total that can disagree with it.
 *
 * The figures are not decoration — each one is a filter. Pressing "Today"
 * takes the list to today; pressing it again lets it go. That is the same
 * behaviour as the web register, so the two screens teach each other.
 */
import { useQuery } from "@tanstack/react-query";
import React, { useMemo, useState } from "react";
import { Pressable, RefreshControl, ScrollView, Text, View } from "react-native";

import {
  CashBox,
  listPettyExpenses,
  PettyCards,
  PettyFilters,
  PettyRow,
} from "@/api/pettyExpenses";
import { AppIcon, IconName } from "@/components/AppIcon";
import { Badge, BadgeTone, Card, EmptyOrError, Loading, Screen } from "@/components/ui";
import {
  pettyIcon,
  pettyMoney as money,
  pettyRangeFilters,
  PettyTile,
  pettyTileFilters,
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

const STATUS_TONE: Record<PettyRow["status"], BadgeTone> = {
  Posted: "success",
  Draft: "warning",
  Cancelled: "danger",
};

export function PettyExpenseListScreen({ navigation }: { navigation: Nav }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const [tile, setTile] = useState<PettyTile>("");
  const [status, setStatus] = useState("");
  const [range, setRange] = useState<"all" | "today" | "week" | "month">("month");
  const [open, setOpen] = useState(true);

  const filters = useMemo<PettyFilters>(() => {
    const base = pettyRangeFilters(range);
    if (status) base.status = status;
    // A pressed figure is the narrower answer, so it wins over the strip.
    return { ...base, ...pettyTileFilters(tile) };
  }, [range, status, tile]);

  const query = useQuery({
    queryKey: ["petty-expenses", filters],
    queryFn: () => listPettyExpenses(filters),
  });

  const press = (next: PettyTile) => setTile((was) => (was === next ? "" : next));

  const cards: PettyCards | undefined = query.data?.cards;
  const rows = query.data?.rows ?? [];
  const box: CashBox | undefined = cards?.cash?.[0];

  return (
    <Screen>
      <ScrollView
        contentContainerStyle={styles.page}
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
          <Tile
            label={box ? box.label.split(" - ").slice(-1)[0] : "Petty Cash"}
            value={money(box?.balance ?? 0)}
            caption={box?.low ? "Below its float" : "Current balance"}
            icon="cash"
            accent={box?.low ? colors.danger : colors.success}
            on={!!box && tile === `box:${box.id}`}
            onPress={() => box && press(`box:${box.id}`)}
          />
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

        <Card padded={false} style={styles.filterCard}>
          <Pressable style={styles.filterHead} onPress={() => setOpen((v) => !v)}>
            <AppIcon name="filter-variant" size={16} color={colors.tint} />
            <Text style={styles.filterTitle}>Quick Filters</Text>
            <View style={{ flex: 1 }} />
            <AppIcon name={open ? "chevron-up" : "chevron-down"} size={18} color={colors.textMuted} />
          </Pressable>
          {open ? (
            <View style={styles.filterBody}>
              <Text style={styles.filterLabel}>Date Range</Text>
              <Chips
                value={range}
                onChange={(v) => setRange(v as typeof range)}
                options={[
                  { value: "today", label: "Today" },
                  { value: "week", label: "Last 7 days" },
                  { value: "month", label: "This month" },
                  { value: "all", label: "All" },
                ]}
              />
              <Text style={[styles.filterLabel, { marginTop: spacing.sm }]}>Status</Text>
              <Chips
                value={status}
                onChange={setStatus}
                options={[
                  { value: "", label: "All" },
                  { value: "Draft", label: "Draft" },
                  { value: "Posted", label: "Posted" },
                  { value: "Cancelled", label: "Cancelled" },
                ]}
              />
            </View>
          ) : null}
        </Card>

        <Text style={styles.count}>
          {query.isLoading ? "Loading…" : `Total: ${rows.length} ${rows.length === 1 ? "entry" : "entries"}`}
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

function Chips({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  const styles = useStyles();
  return (
    <View style={styles.chips}>
      {options.map((o) => {
        const on = o.value === value;
        return (
          <Pressable
            key={o.value || "all"}
            style={[styles.chip, on && styles.chipOn]}
            onPress={() => onChange(o.value)}
            accessibilityRole="button"
            accessibilityState={{ selected: on }}
          >
            <Text style={[styles.chipText, on && styles.chipTextOn]}>{o.label}</Text>
          </Pressable>
        );
      })}
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
    borderTopWidth: 1,
    borderTopColor: colors.border,
    paddingTop: spacing.sm,
  },
  filterLabel: { ...type.caption, color: colors.textMuted, marginBottom: 4 },

  chips: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs },
  chip: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.pill,
    paddingHorizontal: spacing.md,
    paddingVertical: 6,
    backgroundColor: colors.surface,
  },
  chipOn: { backgroundColor: colors.tint, borderColor: colors.tint },
  chipText: { ...type.caption, color: colors.textMuted },
  chipTextOn: { color: colors.onDark, fontWeight: "700" },

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
}));
