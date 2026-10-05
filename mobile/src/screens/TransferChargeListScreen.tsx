/**
 * Transfer Charges — the register on the phone.
 *
 * The same register the browser shows: the figures first, then the filters
 * that narrow them, then the rows. Posting and cancelling go through the
 * row's own menu rather than the entry screen, same split Petty Expense
 * draws — a register is read far more often than it is corrected.
 *
 * There is no separate read-only detail screen: a Transfer Charge's detail
 * *is* its entry screen (its lines and allocations are exactly what editing
 * shows), the way Petty Expense's own entry screen doubles as its detail
 * view. Only the journal voucher this posts to gets its own detail screen
 * (`VoucherDetail`), because a voucher is a shared document other
 * transactions also raise.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import React, { useState } from "react";
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
  cancelTransferCharge,
  deleteTransferCharge,
  postTransferCharge,
  listTransferCharges,
  transferChargeMasters,
  TransferChargeRow,
} from "@/api/transferCharges";
import { confirm, notify } from "@/ui/confirm";
import { AppIcon, IconName } from "@/components/AppIcon";
import { DateField } from "@/components/DateField";
import { Badge, BadgeTone, Card, EmptyOrError, Loading, Screen, SearchBar } from "@/components/ui";
import {
  chargeIcon,
  EMPTY_STRIP,
  openingStrip,
  transferChargeMoney as money,
  transferChargeQuery,
  TransferChargeStrip,
  TransferChargeTile,
  transferChargeTileStrip,
} from "@/domain/transferCharge";
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

const STATUS_TONE: Record<TransferChargeRow["status"], BadgeTone> = {
  Draft: "warning",
  "Pending Approval": "warning",
  Posted: "success",
  Cancelled: "danger",
};

const STATUSES: Option[] = [
  { value: "Draft", label: "Draft" },
  { value: "Pending Approval", label: "Pending Approval" },
  { value: "Posted", label: "Posted" },
  { value: "Cancelled", label: "Cancelled" },
];

export function TransferChargeListScreen({ navigation }: { navigation: Nav }) {
  const styles = useStyles();
  const { colors } = useTheme();

  const [strip, setStrip] = useState<TransferChargeStrip>(() => openingStrip());
  const [tile, setTile] = useState<TransferChargeTile>("");
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState(false);

  const masters = useQuery({ queryKey: ["transfer-charge-masters"], queryFn: transferChargeMasters });
  const M = masters.data;

  const query = useQuery({
    queryKey: ["transfer-charges", strip, search],
    queryFn: () => listTransferCharges(transferChargeQuery(strip, search)),
  });

  const set = (patch: Partial<TransferChargeStrip>) => {
    setStrip((was) => ({ ...was, ...patch }));
    setTile("");
  };

  const press = (pressed: TransferChargeTile) => {
    setStrip((was) => transferChargeTileStrip(was, tile, pressed));
    setTile((was) => (was === pressed ? "" : pressed));
  };

  const clear = () => {
    setStrip(openingStrip());
    setSearch("");
    setTile("");
  };

  const chargeTypes: Option[] = (M?.charge_types ?? []).map((c) => ({
    value: String(c.id),
    label: c.name,
  }));
  const branches: Option[] = (M?.branches ?? []).map((b) => ({
    value: String(b.id),
    label: b.branch_name,
  }));
  const farms: Option[] = (M?.farms ?? [])
    .filter((f) => !strip.branch || String(f.branch_id) === strip.branch)
    .map((f) => ({ value: String(f.id), label: f.farm_name }));
  const scopes: Option[] = (M?.scopes ?? []).map((s) => ({ value: s, label: s }));
  const bankCashAccounts = M?.bank_cash_accounts ?? [];
  const payableAccounts = M?.payable_accounts ?? [];

  const can = usePermissionsStore((st) => st.canTabAction);
  const may = {
    add: can("transfer_charge_list", "add"),
    edit: can("transfer_charge_list", "edit"),
    delete: can("transfer_charge_list", "delete"),
  };

  const client = useQueryClient();
  const [acting, setActing] = useState<TransferChargeRow | null>(null);
  const [busy, setBusy] = useState(false);

  const reread = () => client.invalidateQueries({ queryKey: ["transfer-charges"] });

  async function post(row: TransferChargeRow, allowDuplicate = false) {
    setBusy(true);
    try {
      const done = await postTransferCharge(row.id, allowDuplicate);
      await reread();
      notify(`${row.charge_no} posted.`);
      void done;
    } catch (e) {
      const body = (e as { response?: { data?: { error?: Record<string, unknown> } } })?.response
        ?.data?.error as { message?: string; duplicate?: boolean } | undefined;
      if (body?.duplicate) {
        setBusy(false);
        const ok = await confirm({
          title: "Already charged",
          message: `${body.message}\n\nPost anyway?`,
          confirmLabel: "Post anyway",
          cancelLabel: "Not now",
        });
        if (ok) await post(row, true);
        return;
      }
      notify(refusal(e, "It could not be posted."));
    } finally {
      setBusy(false);
      setActing(null);
    }
  }

  async function cancel(row: TransferChargeRow) {
    const ok = await confirm({
      title: `Cancel ${row.charge_no}?`,
      message: "Its voucher is reversed. The charge stays on the record as cancelled.",
      confirmLabel: "Cancel it",
      cancelLabel: "Keep it",
      destructive: true,
    });
    if (!ok) return;
    setBusy(true);
    try {
      await cancelTransferCharge(row.id, "Cancelled from the phone");
      await reread();
      notify(`${row.charge_no} cancelled.`);
    } catch (e) {
      notify(refusal(e, "It could not be cancelled."));
    } finally {
      setBusy(false);
      setActing(null);
    }
  }

  async function remove(row: TransferChargeRow) {
    const ok = await confirm({
      title: `Delete ${row.charge_no}?`,
      message: "It is gone for good. Only a Draft can be deleted this way.",
      confirmLabel: "Delete",
      cancelLabel: "Keep",
      destructive: true,
    });
    if (!ok) return;
    setBusy(true);
    try {
      await deleteTransferCharge(row.id);
      await reread();
      notify(`${row.charge_no} deleted.`);
    } catch (e) {
      notify(refusal(e, "It could not be deleted."));
    } finally {
      setBusy(false);
      setActing(null);
    }
  }

  const rows = query.data ?? [];
  const totalExpense = rows
    .filter((r) => r.status === "Posted")
    .reduce((sum, r) => sum + Number(r.total_charges || 0), 0);
  const linkedFarms = new Set(rows.flatMap((r) => r.destination_farms.map((f) => f.farm_id))).size;
  const drafts = rows.filter((r) => r.status === "Draft").length;
  const pending = rows.filter((r) => r.status === "Pending Approval").length;

  return (
    <Screen edges={["left", "right", "bottom"]}>
      <ScrollView
        contentContainerStyle={styles.page}
        keyboardShouldPersistTaps="handled"
        refreshControl={
          <RefreshControl refreshing={query.isRefetching} onRefresh={() => query.refetch()} />
        }
      >
        <SearchBar value={search} onChangeText={setSearch} placeholder="DC No." />

        <View style={styles.tiles}>
          <Tile
            label="Total Expense"
            value={money(totalExpense)}
            caption="Posted, in this window"
            icon="cash-multiple"
            accent={colors.success}
            on={false}
            onPress={() => undefined}
          />
          <Tile
            label="Linked Farms"
            value={String(linkedFarms)}
            caption={`${rows.length} ${rows.length === 1 ? "entry" : "entries"}`}
            icon="barn"
            accent={colors.info}
            on={false}
            onPress={() => undefined}
          />
        </View>

        {drafts || pending ? (
          <View style={styles.statusChips}>
            {drafts ? (
              <Pressable
                style={[styles.statusChip, tile === "drafts" && styles.statusChipOn]}
                onPress={() => press("drafts")}
              >
                <Text style={styles.statusChipText}>{drafts} Draft{drafts === 1 ? "" : "s"}</Text>
              </Pressable>
            ) : null}
            {pending ? (
              <Pressable
                style={[styles.statusChip, tile === "pending" && styles.statusChipOn]}
                onPress={() => press("pending")}
              >
                <Text style={styles.statusChipText}>{pending} Pending Approval</Text>
              </Pressable>
            ) : null}
          </View>
        ) : null}

        <Card padded={false} style={styles.filterCard}>
          <Pressable style={styles.filterHead} onPress={() => setOpen((v) => !v)}>
            <AppIcon name="filter-variant" size={16} color={colors.tint} />
            <Text style={styles.filterTitle}>Quick Filters</Text>
            <View style={{ flex: 1 }} />
            <AppIcon name={open ? "chevron-up" : "chevron-down"} size={18} color={colors.textMuted} />
          </Pressable>

          {open ? (
            <View style={styles.filterBody}>
              <View>
                <Text style={styles.label}>Charge date between</Text>
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
                  label="Branch"
                  value={strip.branch}
                  options={branches}
                  onChange={(v) => set({ branch: v, farm: "" })}
                />
                <Pick label="Farm" value={strip.farm} options={farms} onChange={(v) => set({ farm: v })} />
              </View>

              <View style={styles.pair}>
                <Pick
                  label="Charge Type"
                  value={strip.chargeType}
                  options={chargeTypes}
                  onChange={(v) => set({ chargeType: v })}
                />
                <Pick
                  label="Scope"
                  value={strip.chargeScope}
                  options={scopes}
                  onChange={(v) => set({ chargeScope: v })}
                />
              </View>

              <Pick
                label="Status"
                value={strip.status}
                options={STATUSES}
                onChange={(v) => set({ status: v })}
              />

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
            message="Widen the dates, or add the first Transfer Charge."
            icon="truck"
          />
        ) : (
          rows.map((row) => (
            <Row
              key={row.id}
              row={row}
              paidFromLabel={accountLabel(row, bankCashAccounts, payableAccounts)}
              onView={() => navigation.navigate("TransferChargeForm", { id: row.id })}
              onEdit={() => navigation.navigate("TransferChargeForm", { id: row.id })}
              onMore={() => setActing(row)}
            />
          ))
        )}
      </ScrollView>

      <Pressable
        style={({ pressed }) => [styles.add, shadow(2), pressed && styles.addPressed]}
        onPress={() => navigation.navigate("TransferChargeForm", {})}
      >
        <AppIcon name="plus" size={20} color={colors.onDark} />
        <Text style={styles.addText}>Record New Transfer Charge</Text>
      </Pressable>

      {acting ? (
        <RowActions
          row={acting}
          may={may}
          busy={busy}
          onClose={() => setActing(null)}
          onOpen={() => {
            const id = acting.id;
            setActing(null);
            navigation.navigate("TransferChargeForm", { id });
          }}
          onPost={() => post(acting)}
          onCancel={() => cancel(acting)}
          onDelete={() => remove(acting)}
        />
      ) : null}
    </Screen>
  );
}

function refusal(error: unknown, fallback: string): string {
  const said = (error as { response?: { data?: { error?: { message?: string } } } })?.response?.data
    ?.error?.message;
  return said || fallback;
}

/** "Paid From" (Paid Now) or "Payable To" (Pay Later), by name — the row
 *  only carries the id, so this resolves it against the same masters the
 *  entry screen's own pickers use. */
function accountLabel(
  row: TransferChargeRow,
  bankCashAccounts: { id: number; name: string }[],
  payableAccounts: { id: number; code: string; description: string }[]
): string {
  if (row.payment_mode === "Paid Now") {
    return bankCashAccounts.find((a) => a.id === row.paid_from)?.name || "";
  }
  const payable = payableAccounts.find((a) => a.id === row.payable_account);
  return payable ? `${payable.code} · ${payable.description}` : "";
}

/**
 * What a row offers, on the sheet its menu opens — gated the same way
 * Petty Expense gates its own: a Draft or Pending Approval record can still
 * be opened and corrected, only a Draft/Pending record can be posted, only
 * a Posted one can be cancelled, and only a Draft can be deleted (the web
 * API itself refuses deleting anything else).
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
  row: TransferChargeRow;
  may: { add: boolean; edit: boolean; delete: boolean };
  busy: boolean;
  onClose: () => void;
  onOpen: () => void;
  onPost: () => void;
  onCancel: () => void;
  onDelete: () => void;
}) {
  const styles = useStyles();
  const { colors } = useTheme();
  const editable = row.status === "Draft" || row.status === "Pending Approval";

  return (
    <Modal visible animationType="slide" transparent onRequestClose={onClose}>
      <Pressable style={styles.sheetBack} onPress={onClose}>
        <SafeAreaView style={styles.sheet} edges={["bottom"]}>
          <View style={styles.sheetHead}>
            <View>
              <Text style={styles.modalTitle}>{row.charge_no}</Text>
              <Text style={styles.rowMeta}>
                {row.charge_date} • {money(row.total_charges)} • {row.status}
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

          <Action
            icon={editable && may.edit ? "pencil" : "eye-outline"}
            label={!editable || !may.edit ? "View" : "Edit"}
            onPress={onOpen}
          />
          {editable && may.edit ? (
            <Action icon="check" label="Post" tone={colors.success} onPress={onPost} />
          ) : null}
          {row.status === "Posted" && may.delete ? (
            <Action
              icon="cancel"
              label="Cancel"
              note="Reverses its voucher and keeps the record"
              tone={colors.danger}
              onPress={onCancel}
            />
          ) : null}
          {row.status === "Draft" && may.delete ? (
            <Action icon="trash-can-outline" label="Delete" tone={colors.danger} onPress={onDelete} />
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
  const [modalOpen, setModalOpen] = useState(false);
  const chosen = options.find((o) => o.value === value)?.label;

  return (
    <View style={styles.half}>
      <Text style={styles.label}>{label}</Text>
      <Pressable style={styles.control} onPress={() => setModalOpen(true)}>
        <Text style={chosen ? styles.controlText : styles.controlBlank} numberOfLines={1}>
          {chosen ?? "All"}
        </Text>
        <AppIcon name="chevron-down" size={16} color={colors.textFaint} />
      </Pressable>

      <Modal visible={modalOpen} animationType="slide" onRequestClose={() => setModalOpen(false)}>
        <SafeAreaView style={styles.modal} edges={["top", "bottom"]}>
          <View style={styles.modalHead}>
            <Text style={styles.modalTitle}>{label}</Text>
            <Pressable onPress={() => setModalOpen(false)} hitSlop={12}>
              <Text style={styles.modalClose}>Close</Text>
            </Pressable>
          </View>
          <ScrollView contentContainerStyle={{ padding: spacing.md }}>
            <Pressable
              style={styles.option}
              onPress={() => {
                onChange("");
                setModalOpen(false);
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
                  setModalOpen(false);
                }}
              >
                <Text style={styles.optionText}>{o.label}</Text>
                {o.value === value ? <AppIcon name="check" size={16} color={colors.tint} /> : null}
              </Pressable>
            ))}
          </ScrollView>
        </SafeAreaView>
      </Modal>
    </View>
  );
}

/** The destination line: a named farm (plus its batch, when the trip
 *  carried one) for a single-farm charge, or a plain count for several —
 *  the row has no room to list every farm once the charge spans more than
 *  one, the way the Add screen's own trip summary can. */
function destinationLine(row: TransferChargeRow): string {
  if (row.destination_farms.length === 0) return "";
  if (row.destination_farms.length > 1) return `${row.destination_farms.length} Farms`;
  const [farm] = row.destination_farms;
  return farm.batches.length ? `${farm.farm_name} (${farm.batches.join(", ")})` : farm.farm_name;
}

/** "Transport: ₹1,200", "Transport + Unload: ₹1,850", or, once more than
 *  two buckets carry money, "Total Charges: ₹x" — mirroring the figures the
 *  Add screen's own Allocation & Total Summary groups into. */
function chargeBreakdownLine(row: TransferChargeRow): string {
  const buckets: [string, number][] = [
    ["Transport", row.total_transport],
    ["Loading", row.total_loading],
    ["Unload", row.total_unloading],
    ["Other", row.total_other],
  ].filter(([, amount]) => Number(amount) > 0) as [string, number][];
  if (buckets.length === 0 || buckets.length > 2) return `Total Charges: ${money(row.total_charges)}`;
  return `${buckets.map(([label]) => label).join(" + ")}: ${money(row.total_charges)}`;
}

function Row({
  row,
  paidFromLabel,
  onView,
  onEdit,
  onMore,
}: {
  row: TransferChargeRow;
  paidFromLabel: string;
  onView: () => void;
  onEdit: () => void;
  onMore: () => void;
}) {
  const styles = useStyles();
  const { colors } = useTheme();
  const editable = row.status === "Draft" || row.status === "Pending Approval";

  return (
    <Card padded={false} style={styles.row2}>
      <Pressable style={styles.row2Head} onPress={onView}>
        <Text style={styles.rowNo} numberOfLines={1}>
          {row.charge_no}
        </Text>
        <Text style={styles.rowMeta}>{row.charge_date}</Text>
      </Pressable>

      <Pressable onPress={onView}>
        <Text style={styles.rowMeta} numberOfLines={1}>
          {row.from_location || "—"} ➔ {row.farm_count} {row.farm_count === 1 ? "Farm" : "Farms"}
        </Text>
        <Text style={styles.rowWhat} numberOfLines={1}>
          {destinationLine(row)}
        </Text>
        <Text style={styles.rowMeta} numberOfLines={1}>
          DC: {row.dc_no}
          {row.charge_types.length ? ` • ${row.charge_types.join(", ")}` : ""}
        </Text>
      </Pressable>

      <View style={styles.row2Divider} />

      <View style={styles.row2Foot}>
        <View style={{ flex: 1, minWidth: 0 }}>
          <View style={styles.row2FootLine}>
            <Text style={styles.rowWhat} numberOfLines={1}>
              {chargeBreakdownLine(row)}
            </Text>
            <Badge label={row.payment_mode} tone="neutral" />
          </View>
          {paidFromLabel ? (
            <Text style={styles.rowMeta} numberOfLines={1}>
              {row.payment_mode === "Paid Now" ? "Paid From" : "Payable To"}: {paidFromLabel}
            </Text>
          ) : null}
        </View>
      </View>

      <View style={styles.row2Actions}>
        <Badge label={row.status} tone={STATUS_TONE[row.status]} />
        <View style={{ flex: 1 }} />
        <Pressable style={styles.row2Icon} onPress={onView} hitSlop={8} accessibilityLabel={`View ${row.charge_no}`}>
          <AppIcon name="eye-outline" size={18} color={colors.textMuted} />
        </Pressable>
        {editable ? (
          <Pressable style={styles.row2Icon} onPress={onEdit} hitSlop={8} accessibilityLabel={`Edit ${row.charge_no}`}>
            <AppIcon name="pencil-outline" size={18} color={colors.tint} />
          </Pressable>
        ) : null}
        <Pressable
          style={styles.row2Icon}
          onPress={onMore}
          hitSlop={8}
          accessibilityLabel={`More actions for ${row.charge_no}`}
        >
          <AppIcon name="dots-vertical" size={18} color={colors.textMuted} />
        </Pressable>
      </View>
    </Card>
  );
}

const useStyles = makeStyles((colors) => ({
  page: { padding: spacing.md, paddingBottom: spacing.xxl, gap: spacing.sm },

  tiles: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  tile: {
    flexGrow: 1,
    flexBasis: "30%",
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
    marginHorizontal: spacing.md,
    marginBottom: spacing.sm,
  },
  addPressed: { opacity: 0.9 },
  addText: { ...type.body, fontWeight: "700", color: colors.onDark },

  filterCard: { padding: 0 },
  filterHead: { flexDirection: "row", alignItems: "center", gap: spacing.sm, padding: spacing.md },
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
  stripActions: { flexDirection: "row", justifyContent: "flex-end", gap: spacing.md },
  stripBtn: { flexDirection: "row", alignItems: "center", gap: 4, paddingVertical: 4 },
  stripBtnText: { ...type.caption, color: colors.tint, fontWeight: "700" },

  count: { ...type.caption, color: colors.textMuted, marginTop: spacing.xs },

  row: { flexDirection: "row", alignItems: "center", gap: spacing.sm, padding: spacing.sm },
  rowIcon: { width: 40, height: 40, borderRadius: radius.sm, alignItems: "center", justifyContent: "center" },
  rowBody: { flex: 1, minWidth: 0 },
  rowNo: { ...type.body, fontWeight: "700", color: colors.text },
  rowMeta: { ...type.caption, color: colors.textMuted },
  rowWhat: { ...type.caption, color: colors.text },
  rowRight: { alignItems: "flex-end", gap: 4 },
  rowAmount: { ...type.body, fontWeight: "700", color: colors.text },

  statusChips: { flexDirection: "row", gap: spacing.sm },
  statusChip: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.pill,
    paddingHorizontal: spacing.sm,
    paddingVertical: 6,
    backgroundColor: colors.surface,
  },
  statusChipOn: { borderColor: colors.tint, backgroundColor: withAlpha(colors.tint, 0.1) },
  statusChipText: { ...type.caption, color: colors.text, fontWeight: "600" },

  row2: { padding: spacing.sm, gap: 4 },
  row2Head: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  row2Divider: { height: 1, backgroundColor: colors.border, marginVertical: spacing.xs },
  row2Foot: { flexDirection: "row", alignItems: "center" },
  row2FootLine: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.sm },
  row2Actions: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginTop: spacing.xs },
  row2Icon: { padding: 4 },

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
