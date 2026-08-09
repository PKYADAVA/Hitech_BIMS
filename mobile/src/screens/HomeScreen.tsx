import { BottomTabScreenProps } from "@react-navigation/bottom-tabs";
import { useFocusEffect } from "@react-navigation/native";
import React, { useCallback } from "react";
import { Modal, Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { AlertBell } from "@/components/AlertBell";
import { SyncStatusChip } from "@/components/SyncStatusChip";
import { AppIcon } from "@/components/AppIcon";
import { Badge, Button, Card, Screen, SectionHeader, withAlpha } from "@/components/ui";
import { colors, makeStyles, radius, shadow, spacing, type, useTheme } from "@/theme";
import { TabParams } from "@/navigation/types";
import { AuthUser, Row } from "@/api/types";
import { Overview, useOverview } from "@/api/stats";
import { useTodayTrip } from "@/api/trips";
import { IndicatorCarousel, Indicator } from "@/components/IndicatorCarousel";
import { describeTodayTrip } from "@/domain/todayTrip";
import { useAuthStore } from "@/store/authStore";
import { RESOURCE_TABS } from "@/api/permissions";
import { usePermissionsStore } from "@/store/permissionsStore";

const kpi = (v?: number) => (v === undefined || v === null ? "–" : String(v));

/** The Mobile Access tab behind the trip register, taken from the one map that
 *  already pairs screens with tabs rather than spelled out a second time. */
const TRIP_RESOURCE = "hr-supervisor-trips";
const TRIP_TAB = RESOURCE_TABS[TRIP_RESOURCE];

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
  // First, because for the people who drive all day it is the only one they
  // open — see TodayTrip, which puts the same thing above the fold for them.
  { key: "trip", label: "Daily Trip", icon: "🚗", color: colors.hr,
    tab: "HrModule", resourceKey: "hr-supervisor-trips" },
  { key: "batch", label: "Batch Creation", icon: "📦", color: colors.broiler,
    tab: "Broiler", resourceKey: "broiler-batches" },
  // Opened the report until the phone grew the transaction itself; it now
  // lands on the register, which is where the web shortcut goes.
  { key: "placement", label: "Chicks Placement", icon: "🐥", color: colors.hatchery,
    tab: "Broiler", resourceKey: "broiler-chicks-placement" },
  // Named for the tab it opens. "Feed Transfer" described what the branches
  // mostly move, not the tab, and a shortcut that lands somewhere other than
  // its label reads as the wrong link.
  { key: "feed", label: "Stock Transfer", icon: "🚚", color: colors.inventory,
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

/** Which module governs an action, so permissions hide it with its module.
 *  Root-presented modules are named "<Module>Module"; the tab ones are not. */
const moduleOf = (a: QuickAction): string =>
  String(a.tab).replace(/Module$/, "").toLowerCase();

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

/**
 * Today's Trip — the first thing a driver sees, before the dashboard proper.
 *
 * Whoever spends the day on the road opens this app to do one thing, and
 * hunting for it through HR > Supervisor Daily Trip every morning is three
 * taps too many. So the day's own trip is pinned above everything else, in
 * whichever of its three states it is in, with the single action that state
 * needs: start it, close it, or nothing at all once it is closed.
 *
 * Shown only to a login that maps to an employee record — a back-office login
 * has no "my trip" to show — and only when Mobile Access grants the tab.
 */
function TodayTrip({
  trip,
  linked,
  loading,
  onStart,
  onEnd,
}: {
  trip: Row | null | undefined;
  linked: boolean;
  loading: boolean;
  onStart: () => void;
  onEnd: () => void;
}) {
  const styles = useStyles();
  const view = describeTodayTrip(trip, linked);

  return (
    <Card style={styles.tripCard}>
      <View style={styles.tripTop}>
        <View style={[styles.tripIcon, { backgroundColor: withAlpha(colors.hr, 0.14) }]}>
          <AppIcon name="car-side" size={22} color={colors.hr} />
        </View>
        <View style={styles.panelMain}>
          <Text style={styles.tripTitle} numberOfLines={1}>{view.title}</Text>
          {/* Two lines, because the not-linked explanation needs them and the
              other states never reach a second. */}
          <Text style={styles.panelMeta} numberOfLines={2}>{view.detail}</Text>
        </View>
        <Badge label={view.badge.label} tone={view.badge.tone} />
      </View>
      {loading || !view.action ? null : (
        <View style={styles.tripActions}>
          <Button
            title={view.action === "start" ? "Start Trip" : "End Trip"}
            onPress={view.action === "start" ? onStart : onEnd}
          />
        </View>
      )}
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
        {/* No hamburger. The Menu tab in the bar below opens the same side
            navigation, and a thumb is already there. */}
        <View style={styles.brand}>
          <View>
            <Text style={styles.brandName}>Hi Tech BIMS</Text>
            <Text style={styles.brandTag}>Farm management</Text>
          </View>
        </View>

        <View style={styles.headerActions}>
          {/* The dashboard is the screen the app opens on, and the one a
              supervisor checks before setting out — so it is where "have my
              entries gone?" is asked first. It sits outside the stack
              navigators, so it needs the chip placed by hand. */}
          <SyncStatusChip tint="#fff" />
          <AlertBell />
          {/* A bare circle of initials reads as a label, not a button. The
              ring and the caret are what say it opens something — the same
              two cues the ERP's own top-right avatar uses, so the habit
              carries between the desk and the phone. */}
          <Pressable
            onPress={onProfile}
            hitSlop={8}
            accessibilityRole="button"
            accessibilityLabel="Open profile"
            style={({ pressed }) => [styles.avatarBtn, pressed && styles.pressed]}
          >
            <View style={styles.avatar}>
              <Text style={styles.avatarText}>{initialsOf(user)}</Text>
            </View>
            <AppIcon name="chevron-down" size={14} color={colors.onDark} />
          </Pressable>
        </View>
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
  const canTab = usePermissionsStore((s) => s.canTab);
  const permsLoaded = usePermissionsStore((s) => s.loaded);
  const navOrder = usePermissionsStore((s) => s.navOrder);
  const refreshPerms = usePermissionsStore((s) => s.refresh);
  const [farm, setFarm] = React.useState("");
  const [branch, setBranch] = React.useState("");
  const [line, setLine] = React.useState("");
  const [supervisor, setSupervisor] = React.useState("");
  const [period, setPeriod] = React.useState<"today" | "week" | "month">("today");
  /** Which picker sheet is open, if any. */
  const [picking, setPicking] = React.useState<null | "farm" | "branch" | "line" | "supervisor">(null);
  const { data: ov, refetch, isFetching } =
    useOverview({ farm, branch, line, supervisor, period });

  // Whoever is granted the trip tab gets the card. Whether their login maps to
  // an employee decides what it *says* — not whether it appears at all: an
  // unlinked login used to see nothing, which looked like a broken dashboard
  // rather than a setup step nobody had done yet.
  const drives = canTab(TRIP_TAB);
  const linked = !!user?.employee;
  const { data: trip, isLoading: tripLoading, refetch: refetchTrip } =
    useTodayTrip(drives && linked);
  const openTrip = (params: { row?: Row; ending?: boolean }) =>
    navigation.navigate("HrModule" as any, { screen: "SupervisorTripForm", params });

  const nameFrom = (
    options: { id: number | string; name: string }[] | undefined,
    value: string,
    all: string
  ) => (value ? options?.find((o) => String(o.id) === value)?.name ?? all : all);

  const farmName = nameFrom(ov?.farm_options, farm, "All Farms");
  const branchName = nameFrom(ov?.branch_options, branch, "All Branches");
  const lineName = nameFrom(ov?.line_options, line, "All Lines");
  const supervisorName = nameFrom(ov?.supervisor_options, supervisor, "All Supervisors");
  const anyFilter = !!(farm || branch || line || supervisor) || period !== "today";
  const clearFilters = () => {
    setFarm(""); setBranch(""); setLine(""); setSupervisor(""); setPeriod("today");
  };
  const periodLabel = PERIODS.find((p) => p.key === period)?.label ?? "Today";
  // Three choices cycle faster than they pick from a sheet.
  // Today / This Week / This Month cycle faster than they pick from a sheet.
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
      // Coming back from starting or ending a trip lands here, so the card has
      // to re-read rather than show the state the driver just left behind.
      if (drives) refetchTrip();
    }, [refetch, refreshPerms, refetchTrip, drives])
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
        {/* Profile is a Root screen now, not a sibling tab, so the name bubbles
            up to the parent navigator — the same cast the module tiles below
            use for the same reason. */}
        <HomeHeader
          user={user}
          onProfile={() => navigation.navigate("Profile" as any)}
          filters={
            /* One row, in the ERP filter bar's order, scrolled rather than
               wrapped. Five dropdowns and two buttons do not fit across a
               phone at a readable size — laid out as a grid they would push
               the day's figures below the fold, which is the one thing the
               dashboard exists to show. Scrolling keeps it a single row and
               keeps the first two filters, the ones actually changed daily,
               where the thumb already is. */
            <ScrollView
              horizontal
              showsHorizontalScrollIndicator={false}
              contentContainerStyle={styles.filterRow}
              keyboardShouldPersistTaps="handled"
            >
              {/* The ERP's Date box, as the app already expresses it: Today,
                  This Week, This Month. The endpoint takes an explicit date as
                  well, for when a picker is added. */}
              <FilterChip label={periodLabel} onPress={nextPeriod} />
              <FilterChip label={branchName} onPress={() => setPicking("branch")} />
              <FilterChip label={lineName} onPress={() => setPicking("line")} />
              <FilterChip label={supervisorName} onPress={() => setPicking("supervisor")} />
              <FilterChip label={farmName} onPress={() => setPicking("farm")} />
              {anyFilter ? (
                <Pressable
                  onPress={clearFilters}
                  style={styles.filterReset}
                  accessibilityRole="button"
                  accessibilityLabel="Clear filters"
                >
                  <AppIcon name="refresh" size={16} color={colors.onDark} />
                </Pressable>
              ) : null}
            </ScrollView>
          }
        />

        {drives ? (
          <View style={styles.body}>
            <SectionHeader title="Today's Trip" subtitle="Your day on the road" />
            <TodayTrip
              trip={trip}
              linked={linked}
              loading={tripLoading}
              onStart={() => openTrip({})}
              onEnd={() => openTrip({ row: trip ?? undefined, ending: true })}
            />
          </View>
        ) : null}

        <View style={styles.body}>
          <SectionHeader title="At a glance" subtitle="Today's key numbers across your farm" />
        </View>
        <IndicatorCarousel indicators={buildIndicators(ov)} />

        <View style={styles.body}>
          <SectionHeader title="Today's Overview" subtitle="The day so far" />
          <TodayOverview ov={ov} />

          <SectionHeader title="Quick Access" subtitle="The dashboard's shortcuts" />
          <View style={styles.quickGrid}>
            {QUICK_ACTIONS.filter((a) => !permsLoaded
              // Daily Trip is one screen inside HR, so the module flag is too
              // coarse: it would show the shortcut to anyone with any HR
              // access at all, including those Mobile Access denies the tab.
              || (a.resourceKey === TRIP_RESOURCE
                ? canTab(TRIP_TAB)
                : canModule(moduleOf(a)))).map((a) => (
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

      {/* One sheet for whichever chip was tapped. The four lists differ only
          in their title, their options and where the choice lands, and four
          near-identical modals is four places for them to drift apart. */}
      {picking ? (() => {
        const sheet = {
          farm: { title: "Farm", all: "All Farms",
                  options: ov?.farm_options, value: farm, set: setFarm },
          branch: { title: "Branch", all: "All Branches",
                    options: ov?.branch_options, value: branch, set: setBranch },
          line: { title: "Line", all: "All Lines",
                  options: ov?.line_options, value: line, set: setLine },
          supervisor: { title: "Supervisor", all: "All Supervisors",
                        options: ov?.supervisor_options, value: supervisor,
                        set: setSupervisor },
        }[picking];
        return (
          <Modal visible animationType="slide" onRequestClose={() => setPicking(null)}>
            <Screen edges={["top", "left", "right"]}>
              <View style={styles.sheetHead}>
                <Text style={styles.sheetTitle}>{sheet.title}</Text>
                <Pressable onPress={() => setPicking(null)} hitSlop={8}>
                  <Text style={styles.sheetClose}>Close</Text>
                </Pressable>
              </View>
              <ScrollView>
                {/* "All" leads, because it is the default and the one somebody
                    comes back to. */}
                {[{ id: "", name: sheet.all }, ...(sheet.options ?? [])].map((o) => {
                  const value = o.id === "" ? "" : String(o.id);
                  return (
                    <Pressable
                      key={value || "all"}
                      style={styles.sheetRow}
                      onPress={() => { sheet.set(value); setPicking(null); }}
                    >
                      <Text style={styles.sheetRowText}>{o.name}</Text>
                      {sheet.value === value ? (
                        <AppIcon name="check" size={18} color={colors.tint} />
                      ) : null}
                    </Pressable>
                  );
                })}
              </ScrollView>
            </Screen>
          </Modal>
        );
      })() : null}
    </Screen>
  );
}

const GAP = spacing.md;
const ON_DARK_SOFT = withAlpha(colors.onDark, 0.75);

const useStyles = makeStyles((colors) => ({
  scroll: { paddingBottom: spacing.xxl },

  headerActions: { flexDirection: "row", alignItems: "center", gap: spacing.lg },
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

  // The pill around the avatar and its caret are the affordance: a circle of
  // initials on its own is read as a name badge, and people did not try
  // tapping it.
  avatarBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingLeft: 3,
    paddingRight: 7,
    paddingVertical: 3,
    borderRadius: 24,
    backgroundColor: withAlpha(colors.onDark, 0.12),
    borderWidth: 1,
    borderColor: withAlpha(colors.onDark, 0.28),
  },
  avatar: {
    width: 34,
    height: 34,
    borderRadius: 17,
    backgroundColor: withAlpha(colors.onDark, 0.22),
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
  // A scrolling row: paddingRight so the last chip clears the screen edge.
  filterRow: {
    flexDirection: "row", gap: spacing.sm, marginTop: spacing.md,
    paddingRight: spacing.md, alignItems: "center",
  },
  filterReset: {
    width: 34, height: 34, borderRadius: 17,
    alignItems: "center", justifyContent: "center",
    backgroundColor: "rgba(255,255,255,0.16)",
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
  tripCard: { marginBottom: spacing.sm, gap: spacing.sm },
  tripTop: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  tripIcon: {
    width: 44,
    height: 44,
    borderRadius: radius.md,
    alignItems: "center",
    justifyContent: "center",
  },
  tripTitle: { ...type.title, color: colors.text },
  // Full-width, because it is the one thing this card is for.
  tripActions: { marginTop: spacing.xs },
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
