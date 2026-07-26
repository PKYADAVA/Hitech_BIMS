import { BottomTabScreenProps } from "@react-navigation/bottom-tabs";
import { useFocusEffect } from "@react-navigation/native";
import React, { useCallback } from "react";
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Badge, Card, Screen, SectionHeader, withAlpha } from "@/components/ui";
import { colors, radius, shadow, spacing, type } from "@/theme";
import { TabParams } from "@/navigation/types";
import { AuthUser } from "@/api/types";
import { Overview, useOverview } from "@/api/stats";
import { IndicatorCarousel, Indicator } from "@/components/IndicatorCarousel";
import { useAuthStore } from "@/store/authStore";
import { usePermissionsStore } from "@/store/permissionsStore";

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
      accent: colors.primary,
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

interface Tile {
  key: string;
  title: string;
  subtitle: string;
  icon: string;
  color: string;
  /** Route to navigate to — a bottom tab or a Root-presented module screen. */
  target?:
    | keyof TabParams
    | "AccountModule"
    | "InventoryModule"
    | "SalesModule"
    | "PurchaseModule"
    | "HrModule"
    | "UserModule";
}

const TILES: Tile[] = [
  { key: "account", title: "Accounts", subtitle: "Books, masters & vouchers", icon: "📒", color: colors.account, target: "AccountModule" },
  { key: "broiler", title: "Broiler", subtitle: "Farm operations", icon: "🐔", color: colors.broiler, target: "Broiler" },
  { key: "hatchery", title: "Hatchery", subtitle: "Egg to chick", icon: "🥚", color: colors.hatchery, target: "Hatchery" },
  { key: "hr", title: "HR", subtitle: "People & payroll", icon: "👥", color: colors.hr, target: "HrModule" },
  { key: "inventory", title: "Inventory", subtitle: "Items, stock & movements", icon: "📦", color: colors.inventory, target: "InventoryModule" },
  { key: "purchase", title: "Purchase", subtitle: "Suppliers & purchases", icon: "🛒", color: colors.purchase, target: "PurchaseModule" },
  { key: "sales", title: "Sales", subtitle: "Customers & invoices", icon: "💰", color: colors.sales, target: "SalesModule" },
  { key: "sms", title: "SMS", subtitle: "Templates & history", icon: "💬", color: colors.sms, target: "SMS" },
  { key: "user", title: "Users", subtitle: "Roles & permissions", icon: "👤", color: colors.user, target: "UserModule" },
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
 * brand green, then rounds off into the light page below — same onDark/white
 * language as the per-module stack headers, so the app reads as one system.
 */
function HomeHeader({ user, onProfile }: { user: AuthUser | null; onProfile: () => void }) {
  const insets = useSafeAreaInsets();
  const today = new Date().toLocaleDateString(undefined, {
    weekday: "long",
    day: "numeric",
    month: "long",
  });

  return (
    <View style={[styles.header, { paddingTop: insets.top + spacing.md }]}>
      {/* Brand row */}
      <View style={styles.brandRow}>
        <View style={styles.brand}>
          <View style={styles.logo}>
            <Text style={styles.logoGlyph}>🐔</Text>
          </View>
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
        Hi, {user?.full_name || user?.username || "there"} 👋
      </Text>
      {user?.role || user?.department ? (
        <View style={styles.rolePill}>
          <Text style={styles.roleText} numberOfLines={1}>
            {user?.role || "User"}
            {user?.department ? ` · ${user.department}` : ""}
          </Text>
        </View>
      ) : null}
    </View>
  );
}

export function HomeScreen({ navigation }: Props) {
  const user = useAuthStore((s) => s.user);
  const canModule = usePermissionsStore((s) => s.canModule);
  const permsLoaded = usePermissionsStore((s) => s.loaded);
  const { data: ov, refetch, isFetching } = useOverview();

  // Re-pull KPIs whenever Home regains focus (e.g. after sending an SMS on
  // another tab) — the tab isn't remounted, so a mount-only fetch goes stale.
  useFocusEffect(
    useCallback(() => {
      refetch();
    }, [refetch])
  );

  return (
    <Screen edges={["left", "right"]}>
      <ScrollView
        contentContainerStyle={styles.scroll}
        showsVerticalScrollIndicator={false}
        refreshControl={
          <RefreshControl refreshing={isFetching} onRefresh={refetch} tintColor={colors.primary} />
        }
      >
        <HomeHeader user={user} onProfile={() => navigation.navigate("Profile")} />

        <View style={styles.body}>
          <SectionHeader title="At a glance" />
        </View>
        <IndicatorCarousel indicators={buildIndicators(ov)} />

        <View style={styles.body}>
          <SectionHeader title="Modules" />
          <View style={styles.grid}>
            {TILES.filter((t) => !permsLoaded || canModule(t.key)).map((t) => {
              const active = !!t.target;
              return (
                // Outer view carries the shadow (no clipping); inner Card clips
                // the accent bar to the rounded corners. One view can't do both
                // on Android (elevation + overflow:hidden fight), hence the wrap.
                <View key={t.key} style={styles.tileShadow}>
                  <Card
                    padded={false}
                    style={styles.tile}
                    onPress={active ? () => navigation.navigate(t.target as any) : undefined}
                  >
                    <View style={styles.tileInner}>
                      <View style={[styles.tileIcon, { backgroundColor: withAlpha(t.color, 0.14) }]}>
                        <Text style={{ fontSize: 22 }}>{t.icon}</Text>
                      </View>
                      <Text style={styles.tileTitle}>{t.title}</Text>
                      <Text style={styles.tileSub}>{t.subtitle}</Text>
                      {!active ? (
                        <View style={styles.soon}>
                          <Badge label="Soon" tone="neutral" />
                        </View>
                      ) : null}
                    </View>
                    <View style={[styles.tileBar, { backgroundColor: t.color }]} />
                  </Card>
                </View>
              );
            })}
          </View>
        </View>
      </ScrollView>
    </Screen>
  );
}

const GAP = spacing.md;
const ON_DARK_SOFT = withAlpha(colors.onDark, 0.75);

const styles = StyleSheet.create({
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
  logo: {
    width: 40,
    height: 40,
    borderRadius: radius.md,
    backgroundColor: withAlpha(colors.onDark, 0.16),
    alignItems: "center",
    justifyContent: "center",
  },
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
});
