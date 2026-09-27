/**
 * Journal Vouchers — the register on the phone.
 *
 * The generic list gave this tab a read-only feed of vouchers with a Delete
 * button on rows that cannot be deleted, no way to post a draft, no way to
 * cancel anything, and no way to see what a voucher actually says. A voucher
 * without its lines is a number and a date.
 *
 * It now reads like the browser's register and the Petty Expense tab beside
 * it: the figures first, each one a filter; the filters the web strip asks,
 * in its order; then the rows, each opening what can be done with it. The two
 * endings stay apart, because they are not interchangeable -- a draft has
 * posted nothing and simply goes, a posted voucher is reversed and kept.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import React, { useMemo, useState } from "react";
import {
  ActivityIndicator,
  Modal,
  Pressable,
  RefreshControl,
  ScrollView,
  Text,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import {
  cancelVoucher,
  deleteVoucher,
  listVouchers,
  postVoucher,
  VoucherCards,
  voucherCards,
  VoucherRow,
} from "@/api/vouchers";
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
import { isoDate, lastSevenDays, pettyMoney as money } from "@/domain/pettyExpense";
import { ModuleStackParams } from "@/navigation/types";
import { usePermissionsStore } from "@/store/permissionsStore";
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

/** Which figure is pressed, if any. */
type Tile = "" | "today" | "month" | "drafts" | "cancelled";

interface Strip {
  from: string;
  to: string;
  type: string;
  status: string;
}

const STATUS_TONE: Record<VoucherRow["status"], BadgeTone> = {
  Posted: "success",
  Draft: "warning",
  Cancelled: "danger",
};

const STATUSES: Option[] = [
  { value: "Draft", label: "Draft" },
  { value: "Posted", label: "Posted" },
  { value: "Cancelled", label: "Cancelled" },
];

/** The voucher types the engine mints numbers for. */
const TYPES: Option[] = [
  { value: "Journal", label: "Journal" },
  { value: "Payment", label: "Payment" },
  { value: "Receipt", label: "Receipt" },
  { value: "Contra", label: "Contra" },
  { value: "Sales", label: "Sales" },
  { value: "Purchase", label: "Purchase" },
  { value: "Opening", label: "Opening" },
];

const TYPE_ICON: Record<string, IconName> = {
  Payment: "arrow-top-right",
  Receipt: "arrow-bottom-left",
  Contra: "swap-horizontal",
  Sales: "cart-outline",
  Purchase: "truck-outline",
  Opening: "flag-outline",
  Journal: "book-open-variant",
};

function openingStrip(): Strip {
  return { ...lastSevenDays(), type: "", status: "" };
}

export function VoucherListScreen({ navigation }: { navigation: Nav }) {
  const styles = useStyles();
  const { colors } = useTheme();

  const [strip, setStrip] = useState<Strip>(() => openingStrip());
  const [tile, setTile] = useState<Tile>("");
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState(false);
  const [acting, setActing] = useState<VoucherRow | null>(null);
  const [busy, setBusy] = useState(false);

  const can = usePermissionsStore((st) => st.canTabAction);
  const may = {
    edit: can("vouchers", "edit"),
    delete: can("vouchers", "delete"),
  };

  const client = useQueryClient();
  const reread = () =>
    Promise.all([
      client.invalidateQueries({ queryKey: ["vouchers"] }),
      client.invalidateQueries({ queryKey: ["voucher-cards"] }),
    ]);

  const cards = useQuery({ queryKey: ["voucher-cards"], queryFn: voucherCards });
  const query = useQuery({
    queryKey: ["vouchers", strip, search],
    queryFn: () =>
      listVouchers({
        date_from: strip.from || undefined,
        date_to: strip.to || undefined,
        type: strip.type || undefined,
        status: strip.status || undefined,
        q: search.trim() || undefined,
      }),
  });

  const set = (patch: Partial<Strip>) => {
    setStrip((was) => ({ ...was, ...patch }));
    setTile("");
  };

  /**
   * What pressing a figure asks for — the web register's own rules: Today and
   * This Month narrow to posted rows in their window, Drafts carries no dates
   * because a draft can be any age, and pressing again restores the window.
   */
  const press = (pressed: Tile) => {
    const figures: VoucherCards | undefined = cards.data;
    if (tile === pressed) {
      setStrip(openingStrip());
      setTile("");
      return;
    }
    const today = new Date();
    const blank: Strip = { from: "", to: "", type: strip.type, status: "" };
    if (pressed === "today") {
      setStrip({ ...blank, from: figures?.today_date ?? isoDate(today),
        to: figures?.today_date ?? isoDate(today), status: "Posted" });
    } else if (pressed === "month") {
      setStrip({ ...blank, from: figures?.month_from ?? isoDate(today),
        to: figures?.today_date ?? isoDate(today), status: "Posted" });
    } else if (pressed === "drafts") {
      setStrip({ ...blank, status: "Draft" });
    } else if (pressed === "cancelled") {
      setStrip({ ...blank, from: figures?.month_from ?? "",
        to: figures?.today_date ?? "", status: "Cancelled" });
    }
    setTile(pressed);
  };

  const clear = () => {
    setStrip(openingStrip());
    setSearch("");
    setTile("");
  };

  async function act(
    what: "post" | "cancel" | "delete",
    row: VoucherRow,
    run: () => Promise<unknown>,
    said: string
  ) {
    setBusy(true);
    try {
      await run();
      await reread();
      notifyDone(said);
    } catch (e) {
      notifyDone(refusal(e, `It could not be ${what}ed.`));
    } finally {
      setBusy(false);
      setActing(null);
    }
  }

  const rows = query.data?.results ?? [];
  const figures = cards.data;

  return (
    <Screen edges={["left", "right"]}>
      <ScrollView
        contentContainerStyle={styles.page}
        keyboardShouldPersistTaps="handled"
        refreshControl={
          <RefreshControl
            refreshing={query.isRefetching}
            onRefresh={() => {
              query.refetch();
              cards.refetch();
            }}
          />
        }
      >
        <View style={styles.tiles}>
          <Tile
            label="Posted today"
            value={money(figures?.today ?? 0)}
            caption="Vouchers dated today"
            icon="calendar-today"
            accent={colors.tint}
            on={tile === "today"}
            onPress={() => press("today")}
          />
          <Tile
            label="This month"
            value={money(figures?.month ?? 0)}
            caption={`${figures?.month_count ?? 0} ${
              figures?.month_count === 1 ? "voucher" : "vouchers"
            }`}
            icon="calendar-month"
            accent={colors.info}
            on={tile === "month"}
            onPress={() => press("month")}
          />
          <Tile
            label="Drafts"
            value={String(figures?.drafts ?? 0)}
            caption="Waiting to be posted"
            icon="file-document-edit-outline"
            accent={colors.warning}
            on={tile === "drafts"}
            onPress={() => press("drafts")}
          />
          <Tile
            label="Cancelled"
            value={String(figures?.cancelled ?? 0)}
            caption="Reversed this month"
            icon="cancel"
            accent={colors.danger}
            on={tile === "cancelled"}
            onPress={() => press("cancelled")}
          />
        </View>

        <SearchBar
          value={search}
          onChangeText={setSearch}
          placeholder="Voucher no, reference or narration"
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
              <View>
                <Text style={styles.label}>Voucher date between</Text>
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
                  label="Type"
                  value={strip.type}
                  options={TYPES}
                  onChange={(v) => set({ type: v })}
                />
                <Pick
                  label="Status"
                  value={strip.status}
                  options={STATUSES}
                  onChange={(v) => set({ status: v })}
                />
              </View>
              <View style={styles.stripActions}>
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
            : `Total: ${rows.length} ${rows.length === 1 ? "voucher" : "vouchers"}`}
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
            message="Widen the dates, or clear the filters."
            icon="book-open-variant"
          />
        ) : (
          rows.map((row) => (
            <Row key={row.id} row={row} onPress={() => setActing(row)} />
          ))
        )}
      </ScrollView>

      {acting ? (
        <RowActions
          row={acting}
          may={may}
          busy={busy}
          onClose={() => setActing(null)}
          onOpen={() => {
            const id = acting.id;
            setActing(null);
            navigation.navigate("VoucherDetail", { id });
          }}
          onPost={() =>
            act("post", acting, () => postVoucher(acting.id),
              `${acting.voucher_no} posted.`)
          }
          onCancel={() =>
            act("cancel", acting,
              () => cancelVoucher(acting.id, "Cancelled from the phone"),
              `${acting.voucher_no} cancelled.`)
          }
          onDelete={() =>
            act("delete", acting, () => deleteVoucher(acting.id),
              `${acting.voucher_no} deleted.`)
          }
        />
      ) : null}
    </Screen>
  );
}

/* ------------------------------------------------------------------ */

function notifyDone(message: string) {
  const { notify } = require("@/ui/confirm") as typeof import("@/ui/confirm");
  notify(message);
}

/** A server's refusal, in its own words where it gave any. */
function refusal(error: unknown, fallback: string): string {
  const said = (error as { response?: { data?: { error?: { message?: string } } } })
    ?.response?.data?.error?.message;
  return said || fallback;
}

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
          <View style={styles.sheetHead}>
            <Text style={styles.modalTitle}>{label}</Text>
            <Pressable onPress={() => setOpen(false)} hitSlop={12}>
              <Text style={styles.modalClose}>Close</Text>
            </Pressable>
          </View>
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

function Row({ row, onPress }: { row: VoucherRow; onPress: () => void }) {
  const styles = useStyles();
  const { colors } = useTheme();
  return (
    <Card padded={false} style={styles.row} onPress={onPress}>
      <View style={[styles.rowIcon, { backgroundColor: withAlpha(colors.tint, 0.1) }]}>
        <AppIcon
          name={TYPE_ICON[row.voucher_type] ?? "book-open-variant"}
          size={18}
          color={colors.tint}
        />
      </View>
      <View style={styles.rowBody}>
        <Text style={styles.rowNo} numberOfLines={1}>
          {row.voucher_no}
          {row.system_generated ? "  ·  auto" : ""}
        </Text>
        <Text style={styles.rowMeta} numberOfLines={1}>
          {row.voucher_type} · {row.date}
          {row.reference ? ` · ${row.reference}` : ""}
        </Text>
        <Text style={styles.rowWhat} numberOfLines={2}>
          {row.narration}
        </Text>
      </View>
      <View style={styles.rowRight}>
        <Text style={styles.rowAmount}>{money(row.total_debit)}</Text>
        <Badge label={row.status} tone={STATUS_TONE[row.status]} />
      </View>
      <View style={styles.rowMenu}>
        <AppIcon name="dots-vertical" size={18} color={colors.textMuted} />
      </View>
    </Card>
  );
}

/**
 * What a row offers.
 *
 * A voucher the engine raised for another document is not edited or deleted
 * from here: it belongs to the expense, sale or transfer that made it, and
 * correcting that is what changes this. Only a draft can be posted; only a
 * posted voucher can be cancelled; only a draft can be deleted.
 */
function RowActions({
  row,
  may,
  busy,
  onClose,
  onOpen,
  onPost,
  onCancel,
  onDelete,
}: {
  row: VoucherRow;
  may: { edit: boolean; delete: boolean };
  busy: boolean;
  onClose: () => void;
  onOpen: () => void;
  onPost: () => void;
  onCancel: () => void;
  onDelete: () => void;
}) {
  const styles = useStyles();
  const { colors } = useTheme();
  const ownedElsewhere = row.system_generated;

  return (
    <Modal visible animationType="slide" transparent onRequestClose={onClose}>
      <Pressable style={styles.sheetBack} onPress={onClose}>
        <SafeAreaView style={styles.sheet} edges={["bottom"]}>
          <View style={styles.sheetHead}>
            <View>
              <Text style={styles.modalTitle}>{row.voucher_no}</Text>
              <Text style={styles.rowMeta}>
                {row.voucher_type} • {row.date} • {money(row.total_debit)} •{" "}
                {row.status}
              </Text>
            </View>
            <Pressable onPress={onClose} hitSlop={12}>
              <Text style={styles.modalClose}>Close</Text>
            </Pressable>
          </View>

          {busy ? (
            <View style={styles.sheetBusy}>
              <ActivityIndicator />
            </View>
          ) : null}

          <Action icon="eye-outline" label="View" note="Its lines, and what they charge"
            onPress={onOpen} />

          {row.status === "Draft" && may.edit && !ownedElsewhere ? (
            <Action icon="check" label="Post" tone={colors.success}
              note="Numbers it and puts it on the books" onPress={onPost} />
          ) : null}

          {row.status === "Posted" && may.delete && !ownedElsewhere ? (
            <Action icon="cancel" label="Cancel" tone={colors.danger}
              note="Reverses it and keeps the record" onPress={onCancel} />
          ) : null}

          {row.status === "Draft" && may.delete && !ownedElsewhere ? (
            <Action icon="trash-can-outline" label="Delete" tone={colors.danger}
              note="It has posted nothing, so it simply goes" onPress={onDelete} />
          ) : null}

          {ownedElsewhere ? (
            <Text style={styles.sheetNote}>
              The engine raised this one for another document. Correct that document
              and this follows.
            </Text>
          ) : null}
        </SafeAreaView>
      </Pressable>
    </Modal>
  );
}

function Action({
  icon,
  label,
  note,
  tone,
  onPress,
}: {
  icon: IconName;
  label: string;
  note?: string;
  tone?: string;
  onPress: () => void;
}) {
  const styles = useStyles();
  const { colors } = useTheme();
  return (
    <Pressable style={styles.action} onPress={onPress}>
      <AppIcon name={icon} size={18} color={tone ?? colors.text} />
      <View style={{ flex: 1, minWidth: 0 }}>
        <Text style={[styles.actionLabel, tone ? { color: tone } : null]}>{label}</Text>
        {note ? <Text style={styles.rowMeta}>{note}</Text> : null}
      </View>
    </Pressable>
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
  sep: { ...type.caption, color: colors.textMuted, paddingHorizontal: 2, paddingBottom: 10 },
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
  stripActions: { flexDirection: "row", justifyContent: "flex-end" },
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
  rowMenu: { paddingHorizontal: 2, paddingVertical: spacing.sm },

  sheetBack: { flex: 1, backgroundColor: "rgba(15,23,42,0.4)", justifyContent: "flex-end" },
  sheet: {
    backgroundColor: colors.bg,
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    paddingBottom: spacing.sm,
  },
  sheetHead: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    padding: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  sheetBusy: { paddingVertical: spacing.sm },
  sheetNote: { ...type.caption, color: colors.textMuted, padding: spacing.md },
  action: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  actionLabel: { ...type.body, color: colors.text, fontWeight: "600" },

  modal: { flex: 1, backgroundColor: colors.bg },
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
