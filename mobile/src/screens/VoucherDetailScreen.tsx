/**
 * One journal voucher, with the lines that make it balance.
 *
 * The generic detail screen listed the model's fields — narration, auto
 * narration, narration source, system generated — and left out the only part
 * anybody opens a voucher to read: what it charged, and to which accounts.
 * A voucher without its lines is a number and a date.
 *
 * The lines are shown as the ledger writes them, debit column and credit
 * column, with the two totals underneath: a voucher that does not balance is
 * not a voucher, and the screen should make that visible rather than assert it.
 */
import { useQuery } from "@tanstack/react-query";
import React from "react";
import { Pressable, ScrollView, Text, View } from "react-native";

import { getVoucher, VoucherLine } from "@/api/vouchers";
import { AppIcon } from "@/components/AppIcon";
import { Badge, BadgeTone, Card, EmptyOrError, Loading, Screen } from "@/components/ui";
import { pettyMoney as money } from "@/domain/pettyExpense";
import { makeStyles, radius, spacing, type, withAlpha } from "@/theme";
import { useTheme } from "@/theme/ThemeProvider";

const STATUS_TONE: Record<string, BadgeTone> = {
  Posted: "success",
  Draft: "warning",
  Cancelled: "danger",
};

export function VoucherDetailScreen({
  route,
}: {
  route: { params: { id: number } };
}) {
  const styles = useStyles();
  const { colors } = useTheme();
  const id = route.params.id;

  const query = useQuery({
    queryKey: ["voucher", id],
    queryFn: () => getVoucher(id),
  });

  if (query.isLoading) {
    return (
      <Screen edges={["left", "right"]}>
        <Loading label="Reading the voucher" />
      </Screen>
    );
  }
  if (query.isError || !query.data) {
    return (
      <Screen edges={["left", "right"]}>
        <EmptyOrError
          title="The voucher could not be read"
          message="Check the connection and try again."
          icon="alert-circle-outline"
        />
      </Screen>
    );
  }

  const voucher = query.data;
  const lines: VoucherLine[] = voucher.lines ?? [];
  const debit = lines.reduce((sum, l) => sum + Number(l.debit || 0), 0);
  const credit = lines.reduce((sum, l) => sum + Number(l.credit || 0), 0);
  const balanced = Math.abs(debit - credit) < 0.005;

  return (
    <Screen edges={["left", "right"]}>
      <ScrollView contentContainerStyle={styles.page}>
        <Card style={styles.head}>
          <View style={styles.headTop}>
            <View style={{ flex: 1, minWidth: 0 }}>
              <Text style={styles.no}>{voucher.voucher_no}</Text>
              <Text style={styles.meta}>
                {voucher.voucher_type} {"·"} {voucher.date}
                {voucher.financial_year ? ` ${"·"} ${voucher.financial_year}` : ""}
              </Text>
            </View>
            <Badge
              label={voucher.status}
              tone={STATUS_TONE[voucher.status] ?? "neutral"}
            />
          </View>
          <Text style={styles.amount}>{money(voucher.total_debit)}</Text>
          {voucher.system_generated ? (
            <View style={styles.auto}>
              <AppIcon name="robot-outline" size={13} color={colors.textMuted} />
              <Text style={styles.meta}>
                Raised by the engine for another document
              </Text>
            </View>
          ) : null}
        </Card>

        <Card padded={false} style={styles.card}>
          <View style={styles.cardHead}>
            <Text style={styles.cardTitle}>Lines</Text>
            <View style={{ flex: 1 }} />
            <Text style={styles.meta}>
              {lines.length} {lines.length === 1 ? "line" : "lines"}
            </Text>
          </View>

          <View style={styles.lineHead}>
            <Text style={[styles.colLabel, { flex: 1 }]}>ACCOUNT</Text>
            <Text style={[styles.colLabel, styles.num]}>DEBIT</Text>
            <Text style={[styles.colLabel, styles.num]}>CREDIT</Text>
          </View>

          {lines.map((line) => (
            <View key={line.id} style={styles.line}>
              <View style={{ flex: 1, minWidth: 0 }}>
                <Text style={styles.account} numberOfLines={2}>
                  {line.account_name || `Account ${line.account}`}
                </Text>
                <Text style={styles.meta} numberOfLines={1}>
                  {line.account_code}
                  {line.cost_center_name ? ` · ${line.cost_center_name}` : ""}
                </Text>
                {line.narration ? (
                  <Text style={styles.meta} numberOfLines={2}>
                    {line.narration}
                  </Text>
                ) : null}
              </View>
              <Text style={[styles.figure, styles.num]}>
                {Number(line.debit) ? money(line.debit) : "—"}
              </Text>
              <Text style={[styles.figure, styles.num]}>
                {Number(line.credit) ? money(line.credit) : "—"}
              </Text>
            </View>
          ))}

          {/* The two totals, side by side: a voucher that does not balance
              should be visible as one, not asserted to be one. */}
          <View style={[styles.line, styles.totals]}>
            <Text style={[styles.totalLabel, { flex: 1 }]}>TOTAL</Text>
            <Text style={[styles.total, styles.num]}>{money(debit)}</Text>
            <Text style={[styles.total, styles.num]}>{money(credit)}</Text>
          </View>
          {!balanced ? (
            <View style={styles.unbalanced}>
              <AppIcon name="alert-circle-outline" size={14} color={colors.danger} />
              <Text style={styles.unbalancedText}>
                The two sides differ by {money(Math.abs(debit - credit))}.
              </Text>
            </View>
          ) : null}
        </Card>

        <Card padded={false} style={styles.card}>
          <View style={styles.cardHead}>
            <Text style={styles.cardTitle}>What it says</Text>
          </View>
          <View style={styles.body}>
            <Field label="Narration" value={voucher.narration || "—"} />
            {voucher.reference ? (
              <Field label="Reference" value={voucher.reference} />
            ) : null}
            {voucher.sector_name ? (
              <Field label="Sector" value={voucher.sector_name} />
            ) : null}
            {voucher.narration_source === "MANUAL" && voucher.auto_narration ? (
              // Both, where they differ: the engine's sentence is the audit
              // trail behind the one somebody wrote over it.
              <Field label="The engine's own wording" value={voucher.auto_narration} />
            ) : null}
            {voucher.cancelled_reason ? (
              <Field label="Cancelled because" value={voucher.cancelled_reason} />
            ) : null}
            {voucher.created_by ? (
              <Field label="Entered by" value={voucher.created_by} />
            ) : null}
          </View>
        </Card>
      </ScrollView>
    </Screen>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  const styles = useStyles();
  return (
    <View style={styles.field}>
      <Text style={styles.colLabel}>{label.toUpperCase()}</Text>
      <Text style={styles.fieldValue}>{value}</Text>
    </View>
  );
}

const useStyles = makeStyles((colors) => ({
  page: { padding: spacing.md, paddingBottom: spacing.xxl, gap: spacing.sm },

  head: { gap: 4 },
  headTop: { flexDirection: "row", alignItems: "flex-start", gap: spacing.sm },
  no: { ...type.h3, color: colors.text },
  meta: { ...type.caption, color: colors.textMuted },
  amount: { ...type.h1, color: colors.text, marginTop: 2 },
  auto: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 4 },

  card: { padding: 0 },
  cardHead: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    padding: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  cardTitle: { ...type.title, color: colors.text },
  body: { padding: spacing.md, gap: spacing.md },

  lineHead: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingHorizontal: spacing.md,
    paddingTop: spacing.sm,
    paddingBottom: 4,
  },
  colLabel: { ...type.caption, color: colors.textFaint, fontSize: 10, letterSpacing: 0.4 },
  num: { width: 92, textAlign: "right" },
  line: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  account: { ...type.body, color: colors.text, fontWeight: "600" },
  figure: { ...type.body, color: colors.text, fontVariant: ["tabular-nums"] },
  totals: { backgroundColor: colors.surfaceAlt },
  totalLabel: { ...type.caption, color: colors.textMuted, fontWeight: "700" },
  total: { ...type.body, color: colors.text, fontWeight: "700" },
  unbalanced: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    padding: spacing.md,
    backgroundColor: withAlpha(colors.danger, 0.08),
  },
  unbalancedText: { ...type.caption, color: colors.danger, flex: 1 },

  field: { gap: 2 },
  fieldValue: { ...type.body, color: colors.text },
}));
