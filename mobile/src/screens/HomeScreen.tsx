import { BottomTabScreenProps } from "@react-navigation/bottom-tabs";
import { useFocusEffect } from "@react-navigation/native";
import React, { useCallback } from "react";
import { Modal, Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { AppIcon } from "@/components/AppIcon";
import { Badge, Card, Screen, SectionHeader, withAlpha } from "@/components/ui";
import { colors, makeStyles, radius, shadow, spacing, type, useTheme } from "@/theme";
import { TabParams } from "@/navigation/types";
import { AuthUser } from "@/api/types";
import { Overview, useOverview } from "@/api/stats";
import { IndicatorCarousel, Indicator } from "@/components/IndicatorCarousel";
import { useAuthStore } from "@/store/authStore";
import { usePermissionsStore } from "@/store/permissionsStore";
import { useSideNav } from "@/store/sideNavStore";

const kpi = (v?: number) => (v === undefined || v === null ? "–" : String(v));

/** Cross-module headline indicators for the Home carousel. */
function buildIndicators(ov?: Overview): Indicator[] {
  return [
    {
      key: "mortality",
      label: "Mortality",
      value: kpi(ov?.broiler.mortality_today),
      caption: "birds today · 7-day trend",
      icon: "⚠️",
      accent: colors.danger,
      trend: ov?.broiler.mortality_7d,
    },
    {
      key: "entries",
      label: "Daily Entries",
      value: kpi(ov?.broiler.entries_today),
      caption: "logged today",
      icon: "📋",
      accent: colors.broiler,
    },
    {
      key: "batches",
      label: "Active Batches",
      value: kpi(ov?.broiler.active_batches),
      caption: "in production",
      icon: "📦",
      accent: colors.tint,
    },
    {
      key: "eggs",
      label: "Egg Purchases",
      value: kpi(ov?.hatchery.egg_purchases_today),
      caption: "today",
      icon: "🥚",
      accent: colors.hatchery,
    },
    {
      key: "chicks",
      label: "Chicks Hatched",
      value: kpi(ov?.hatchery.chicks_today),
      caption: "today",
      icon: "🐥",
      accent: colors.hatchery,
    },
    {
      key: "sms",
      label: "SMS Sent",
      value: kpi(ov?.sms.sent_today),
      caption: `${kpi(ov?.sms.failed_today)} failed today`,
      icon: "💬",
      accent: colors.sms,
    },
    {
      key: "items",
      label: "Inventory Items",
      value: kpi(ov?.inventory?.items),
      caption: `${kpi(ov?.inventory?.transfers_today)} transfers today`,
      icon: "📦",
      accent: colors.inventory,
    },
    {
      key: "vouchers",
      label: "Vouchers",
      value: kpi(ov?.account?.vouchers_today),
      caption: "posted today",
      icon: "📒",
      accent: colors.account,
    },
  ];
}

type Props = BottomTabScreenProps<TabParams, "Home">;

/** A route the sidebar and the quick actions can both reach. */
type NavTarget =
  | keyof TabParams
  | "AccountModule" | "InventoryModule" | "SalesModule"
  | "PurchaseModule" | "HrModule" | "UserModule";

/**
 * The ERP dashboard's Quick Action row, on the phone.
 *
 * Deliberately the same seven in the same order as `user/templates/home.html`
 * rather than a mobile-only selection: someone who works both screens should
 * not have to learn two sets of shortcuts. Each opens that resource's list,
 * which is where the web links land too.
 *
 * Chicks Placement is the exception — the phone has no placement *transaction*
 * list, only the register — so it opens the report of the same name.
 */
interface QuickAction {
  key: string;
  label: string;
  icon: string;
  color: string;
  tab: NavTarget;
  resourceKey?: string;
  report?: { title: string; path: string };
}

const QUICK_ACTIONS: QuickAction[] = [
  { key: "batch", label: "Batch Creation", icon: "📦", color: colors.broiler,
    tab: "Broiler", resourceKey: "broiler-batches" },
  { key: "placement", label: "Chicks Placement", icon: "🐥", color: colors.hatchery,
    tab: "Broiler", report: { title: "Chicks Placement", path: "/reports/chicks-placement" } },
  { key: "feed", label: "Feed Transfer", icon: "🚚", color: colors.inventory,
    tab: "InventoryModule", resourceKey: "inventory-stock-transfers" },
  { key: "daily", label: "Daily Entry", icon: "📋", color: colors.broiler,
    tab: "Broiler", resourceKey: "broiler-daily-entries" },
  { key: "medicine", label: "Medicine & Vaccine", icon: "💉", color: colors.danger,
    tab: "Broiler", resourceKey: "broiler-medicine-vaccine" },
  { key: "sale", label: "Bird Sale", icon: "🐔", color: colors.sales,
    tab: "Broiler", resourceKey: "broiler-bird-sales" },
  { key: "receipt", label: "Bird Receipt", icon: "🧾", color: colors.account,
    tab: "Broiler", resourceKey: "broiler-sale-receipts" },
];

/** Which module governs an action, so permissions hide it with its module. */
const moduleOf = (a: QuickAction): string =>
  a.tab === "InventoryModule" ? "inventory" : String(a.tab).toLowerCase();

const num = (v?: number, dp = 0) =>
  v === undefined || v === null ? "–" : v.toLocaleString(undefined, {
    minimumFractionDigits: dp, maximumFractionDigits: dp,
  });

/** Today's Overview — the day's four headline figures, as one short list. */
function TodayOverview({ ov }: { ov?: Overview }) {
  const styles = useStyles();
  const b = ov?.broiler;
  const rows: [string, string][] = [
    ["Birds Placed Today", num(b?.birds_placed_today)],
    ["Feed Consumption (kg)", num(b?.feed_kg_today)],
    ["Mortality Today (%)", b?.mortality_pct_today === undefined
      ? "–" : `${num(b.mortality_pct_today, 2)}%`],
    // null means nothing weighed or sold yet — a dash, not a number.
    ["FCR (Current Avg.)", b?.fcr == null ? "–" : num(b.fcr, 3)],
  ];
  return (
    <Card style={styles.panel}>
      {rows.map(([label, value]) => (
        <View key={label} style={styles.panelRow}>
          <Text style={styles.panelLabel}>{label}</Text>
          <Text style={styles.panelValue}>{value}</Text>
        </View>
      ))}
    </Card>
  );
}

/** Recent Alerts and Farm Visit Today, side by side in the reference and
 *  stacked here — a phone column cannot carry two lists abreast. */
function ListPanel({
  rows,
  empty,
}: {
  rows: { key: string; title: string; meta: string; tone?: string }[];
  empty: string;
}) {
  const styles = useStyles();
  if (!rows.length) return <Card style={styles.panel}><Text style={styles.panelEmpty}>{empty}</Text></Card>;
  return (
    <Card style={styles.panel}>
      {rows.map((r) => (
        <View key={r.key} style={styles.panelRow}>
          <View style={styles.panelMain}>
            <Text style={styles.panelTitle} numberOfLines={1}>{r.title}</Text>
            {r.meta ? <Text style={styles.panelMeta}>{r.meta}</Text> : null}
          </View>
          {r.tone ? <Badge label={r.tone} tone={r.tone === "Done" ? "success" : "neutral"} /> : null}
        </View>
      ))}
    </Card>
  );
}

/** The System Summary strip: five counts of what exists, not of what happened. */
function SystemSummary({ ov }: { ov?: Overview }) {
  const styles = useStyles();
  const s = ov?.system;
  const cells: [string, string][] = [
    ["Users", num(s?.users)],
    ["Farms", num(s?.farms)],
    ["Stores", num(s?.stores)],
    ["Items", num(s?.items)],
    ["Batches", num(s?.batches)],
  ];
  return (
    <Card style={styles.panel}>
      <View style={styles.summaryRow}>
        {cells.map(([label, value]) => (
          <View key={label} style={styles.summaryCell}>
            <Text style={styles.summaryValue}>{value}</Text>
            <Text style={styles.summaryLabel}>{label}</Text>
          </View>
        ))}
      </View>
    </Card>
  );
}

/** One filter chip that cycles through, or opens, its choices. */
function FilterChip({
  label,
  onPress,
}: {
  label: string;
  onPress: () => void;
}) {
  const styles = useStyles();
  return (
    <Pressable style={styles.chip} onPress={onPress} accessibilityRole="button">
      <Text style={styles.chipText} numberOfLines={1}>{label}</Text>
      <AppIcon name="chevron-down" size={16} color={colors.onDark} />
    </Pressable>
  );
}

const PERIODS: { key: "today" | "week" | "month"; label: string }[] = [
  { key: "today", label: "Today" },
  { key: "week", label: "This Week" },
  { key: "month", label: "This Month" },
];

function initialsOf(user: AuthUser | null): string {
  return (user?.full_name || user?.username || "?")
    .split(" ")
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

/**
 * Branded top app bar for Home. Bleeds into the status-bar safe area with the
 * brand charcoal, then rounds off into the light page below — same onDark/white
 * language as the per-module stack headers, so the app reads as one system.
 */
/** "Good morning/afternoon/evening" for the current local hour. */
function greetingFor(date = new Date()): string {
  const h = date.getHours();
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

function HomeHeader({
  user,
  onProfile,
  filters,
}: {
  user: AuthUser | null;
  onProfile: () => void;
  filters?: React.ReactNode;
}) {
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const today = new Date().toLocaleDateString(undefined, {
    weekday: "long",
    day: "numeric",
    month: "long",
  });
  const firstName = (user?.full_name || user?.username || "there").split(" ")[0];

  return (
    <View style={[styles.header, { paddingTop: insets.top + spacing.md }]}>
      {/* Brand row */}
      <View style={styles.brandRow}>
        <View style={styles.brand}>
          <Pressable
            onPress={() => useSideNav.getState().openNav("dashboard")}
            hitSlop={12}
            accessibilityRole="button"
            accessibilityLabel="Open menu"
            style={styles.menuButton}
          >
            <AppIcon name="menu" size={22} color={colors.onDark} />
          </Pressable>
          <View>
            <Text style={styles.brandName}>Hi Tech BIMS</Text>
            <Text style={styles.brandTag}>Farm management</Text>
          </View>
        </View>

        <Pressable
          onPress={onProfile}
          hitSlop={8}
          accessibilityRole="button"
          accessibilityLabel="Open profile"
          style={({ pressed }) => [styles.avatar, pressed && styles.pressed]}
        >
          <Text style={styles.avatarText}>{initialsOf(user)}</Text>
        </Pressable>
      </View>

      {/* Greeting */}
      <Text style={styles.date}>{today}</Text>
      <Text style={styles.hello} numberOfLines={1}>
        {greetingFor()}, {firstName} 👋
      </Text>
      {user?.role || user?.department ? (
        <View style={styles.rolePill}>
          <Text style={styles.roleText} numberOfLines={1}>
            {user?.role || "User"}
            {user?.department ? ` · ${user.department}` : ""}
          </Text>
        </View>
      ) : null}
      {filters}
    </View>
  );
}

export function HomeScreen({ navigation }: Props) {
  const styles = useStyles();
  const { colors: theme } = useTheme();
  const user = useAuthStore((s) => s.user);
  const canModule = usePermissionsStore((s) => s.canModule);
  const permsLoaded = usePermissionsStore((s) => s.loaded);
  const navOrder = usePermissionsStore((s) => s.navOrder);
  const refreshPerms = usePermissionsStore((s) => s.refresh);
  const [farm, setFarm] = React.useState("");
  const [period, setPeriod] = React.useState<"today" | "week" | "month">("today");
  const [pickFarm, setPickFarm] = React.useState(false);
  const { data: ov, refetch, isFetching } = useOverview({ farm, period });

  const farmName = farm
    ? ov?.farm_options?.find((f) => String(f.id) === farm)?.name ?? "Farm"
    : "All Farms";
  const periodLabel = PERIODS.find((p) => p.key === period)?.label ?? "Today";
  // Three choices cycle faster than they pick from a sheet.
  const nextPeriod = () =>
    setPeriod(PERIODS[(PERIODS.findIndex((p) => p.key === period) + 1) % PERIODS.length].key);

  // Re-pull KPIs whenever Home regains focus (e.g. after sending an SMS on
  // another tab) — the tab isn't remounted, so a mount-only fetch goes stale.
  // Permissions ride along: an access change made on the web should apply on
  // the next glance at the app, not on the next login.
  useFocusEffect(
    useCallback(() => {
      refetch();
      refreshPerms();
    }, [refetch, refreshPerms])
  );

  return (
    <Screen edges={["left", "right"]}>
      <ScrollView
        contentContainerStyle={styles.scroll}
        showsVerticalScrollIndicator={false}
        refreshControl={
          <RefreshControl refreshing={isFetching} onRefresh={refetch} tintColor={theme.primary} />
        }
      >
        <HomeHeader
          user={user}
          onProfile={() => navigation.navigate("Profile")}
          filters={
            <View style={styles.filterRow}>
              <FilterChip label={farmName} onPress={() => setPickFarm(true)} />
              <FilterChip label={periodLabel} onPress={nextPeriod} />
            </View>
          }
        />

        <View style={styles.body}>
          <SectionHeader title="At a glance" subtitle="Today's key numbers across your farm" />
        </View>
        <IndicatorCarousel indicators={buildIndicators(ov)} />

        <View style={styles.body}>
          <SectionHeader title="Today's Overview" subtitle="The day so far" />
          <TodayOverview ov={ov} />

          <SectionHeader title="Quick Access" subtitle="The dashboard's shortcuts" />
          <View style={styles.quickGrid}>
            {QUICK_ACTIONS.filter((a) => !permsLoaded || canModule(moduleOf(a))).map((a) => (
              <Pressable
                key={a.key}
                style={styles.quickCard}
                onPress={() =>
                  a.report
                    ? navigation.navigate(a.tab as any, { screen: "Report", params: a.report })
                    : navigation.navigate(a.tab as any, {
                        screen: "List", params: { resourceKey: a.resourceKey },
                      })
                }
                accessibilityRole="button"
                accessibilityLabel={a.label}
              >
                <View style={[styles.quickIcon, { backgroundColor: withAlpha(a.color, 0.14) }]}>
                  <AppIcon emoji={a.icon} size={20} color={a.color} />
                </View>
                <Text style={styles.quickLabel} numberOfLines={2}>{a.label}</Text>
              </Pressable>
            ))}
          </View>

          <SectionHeader title="Recent Alerts" subtitle={`${ov?.alerts?.pending ?? 0} unread`} />
          <ListPanel
            empty="Nothing unread."
            rows={(ov?.alerts?.rows ?? []).map((a, i) => ({
              key: `a${i}`, title: a.title, meta: a.at, tone: a.severity,
            }))}
          />

          <SectionHeader
            title="Farm Visit Today"
            subtitle={`${ov?.visits?.completed ?? 0} of ${ov?.visits?.today ?? 0} done`}
          />
          <ListPanel
            empty="No visits logged today."
            rows={(ov?.visits?.rows ?? []).map((v, i) => ({
              key: `v${i}`, title: v.farm, meta: [v.purpose, v.at].filter(Boolean).join(" · "),
              tone: v.done ? "Done" : "Open",
            }))}
          />

          <SectionHeader title="System Summary" subtitle="What is on the books" />
          <SystemSummary ov={ov} />
        </View>
      </ScrollView>

      {/* Farm picker. "All Farms" leads, because it is the default and the one
          someone returns to. */}
      <Modal visible={pickFarm} animationType="slide" onRequestClose={() => setPickFarm(false)}>
        <Screen edges={["top", "left", "right"]}>
          <View style={styles.sheetHead}>
            <Text style={styles.sheetTitle}>Farm</Text>
            <Pressable onPress={() => setPickFarm(false)} hitSlop={8}>
              <Text style={styles.sheetClose}>Close</Text>
            </Pressable>
          </View>
          <ScrollView>
            {[{ id: 0, name: "All Farms" }, ...(ov?.farm_options ?? [])].map((f) => {
              const value = f.id ? String(f.id) : "";
              return (
                <Pressable
                  key={f.id}
                  style={styles.sheetRow}
                  onPress={() => { setFarm(value); setPickFarm(false); }}
                >
                  <Text style={styles.sheetRowText}>{f.name}</Text>
                  {farm === value ? (
                    <AppIcon name="check" size={18} color={colors.tint} />
                  ) : null}
                </Pressable>
              );
            })}
          </ScrollView>
        </Screen>
      </Modal>
    </Screen>
  );
}

const GAP = spacing.md;
const ON_DARK_SOFT = withAlpha(colors.onDark, 0.75);

const useStyles = makeStyles((colors) => ({
  scroll: { paddingBottom: spacing.xxl },

  header: {
    backgroundColor: colors.primary,
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.xl,
    borderBottomLeftRadius: radius.xl,
    borderBottomRightRadius: radius.xl,
    ...shadow(2),
  },
  brandRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: spacing.lg,
  },
  brand: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  logoGlyph: { fontSize: 22 },
  brandName: { ...type.h3, color: colors.onDark },
  brandTag: { ...type.caption, color: ON_DARK_SOFT },

  avatar: {
    width: 42,
    height: 42,
    borderRadius: 21,
    backgroundColor: withAlpha(colors.onDark, 0.16),
    borderWidth: 1,
    borderColor: withAlpha(colors.onDark, 0.3),
    alignItems: "center",
    justifyContent: "center",
  },
  avatarText: { ...type.label, color: colors.onDark, fontWeight: "800" },
  pressed: { opacity: 0.85, transform: [{ scale: 0.97 }] },

  date: { ...type.caption, color: ON_DARK_SOFT, textTransform: "uppercase", letterSpacing: 0.5 },
  hello: { ...type.h1, color: colors.onDark, marginTop: 2 },
  rolePill: {
    alignSelf: "flex-start",
    marginTop: spacing.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: 4,
    borderRadius: radius.pill,
    backgroundColor: withAlpha(colors.onDark, 0.16),
  },
  roleText: { ...type.caption, color: colors.onDark, fontWeight: "600" },

  body: { padding: spacing.md, gap: spacing.sm },
  kpiRow: { flexDirection: "row", gap: spacing.sm },
  chartCard: { marginTop: spacing.sm },
  chartTitle: { ...type.label, color: colors.textMuted, marginBottom: spacing.md },

  grid: { flexDirection: "row", flexWrap: "wrap", justifyContent: "space-between", rowGap: GAP },
  menuButton: { paddingRight: spacing.xs },
  filterRow: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.md },
  sheetHead: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    padding: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  sheetTitle: { ...type.h3, color: colors.text },
  sheetClose: { ...type.title, color: colors.tint },
  sheetRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  sheetRowText: { ...type.body, color: colors.text },
  chip: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.xs,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
    borderRadius: radius.pill ?? 999,
    backgroundColor: "rgba(255,255,255,0.16)",
    maxWidth: "48%",
  },
  chipText: { ...type.label, color: colors.onDark },
  panel: { marginBottom: spacing.lg, paddingVertical: spacing.xs },
  panelRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: spacing.sm,
    gap: spacing.sm,
  },
  panelMain: { flex: 1 },
  panelLabel: { ...type.body, color: colors.textMuted },
  panelValue: { ...type.title, color: colors.text },
  panelTitle: { ...type.body, color: colors.text },
  panelMeta: { ...type.caption, color: colors.textMuted, marginTop: 1 },
  panelEmpty: { ...type.body, color: colors.textFaint, paddingVertical: spacing.sm },
  summaryRow: { flexDirection: "row", justifyContent: "space-between", paddingVertical: spacing.xs },
  summaryCell: { alignItems: "center", flex: 1 },
  summaryValue: { ...type.h3, color: colors.text },
  summaryLabel: { ...type.caption, color: colors.textMuted, marginTop: 2 },
  quickGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.sm,
    marginBottom: spacing.lg,
  },
  quickCard: {
    // Four to a row on a phone, so seven actions read as two tidy lines.
    width: "22.7%",
    alignItems: "center",
    paddingVertical: spacing.sm,
    gap: spacing.xs,
  },
  quickIcon: {
    width: 44,
    height: 44,
    borderRadius: radius.md,
    alignItems: "center",
    justifyContent: "center",
  },
  quickLabel: { ...type.caption, color: colors.text, textAlign: "center" },
  tileShadow: {
    width: "48%",
    borderRadius: radius.lg,
    backgroundColor: colors.surface,
    ...shadow(1),
  },
  // flex:1 fills the (row-stretched) wrapper so no wrapper background shows
  // below the accent bar; tileInner then grows to keep the bar at the bottom.
  tile: { flex: 1, overflow: "hidden" },
  tileInner: { flex: 1, padding: spacing.md, gap: 2, minHeight: 96, justifyContent: "flex-start" },
  tileIcon: {
    width: 40,
    height: 40,
    borderRadius: radius.md,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: spacing.xs,
  },
  tileTitle: { ...type.title, color: colors.text },
  tileSub: { ...type.caption, color: colors.textMuted },
  soon: { position: "absolute", top: spacing.sm, right: spacing.sm },
  tileBar: { height: 4, width: "100%" },
}));
