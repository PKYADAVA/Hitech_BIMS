import { BottomTabScreenProps } from "@react-navigation/bottom-tabs";
import React from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Badge, Card, Screen, SectionHeader, withAlpha } from "@/components/ui";
import { colors, radius, shadow, spacing, type } from "@/theme";
import { TabParams } from "@/navigation/types";
import { AuthUser } from "@/api/types";
import { useAuthStore } from "@/store/authStore";

type Props = BottomTabScreenProps<TabParams, "Home">;

interface Tile {
  key: string;
  title: string;
  subtitle: string;
  icon: string;
  color: string;
  target?: keyof TabParams;
}

const TILES: Tile[] = [
  { key: "broiler", title: "Broiler", subtitle: "Farm operations", icon: "🐔", color: colors.broiler, target: "Broiler" },
  { key: "hatchery", title: "Hatchery", subtitle: "Egg to chick", icon: "🥚", color: colors.hatchery, target: "Hatchery" },
  { key: "sms", title: "SMS", subtitle: "Templates & history", icon: "💬", color: colors.sms, target: "SMS" },
  { key: "inventory", title: "Inventory", subtitle: "Coming soon", icon: "📦", color: "#0891b2" },
  { key: "sales", title: "Sales", subtitle: "Coming soon", icon: "💰", color: "#16a34a" },
  { key: "purchase", title: "Purchase", subtitle: "Coming soon", icon: "🛒", color: "#7c3aed" },
  { key: "hr", title: "HR", subtitle: "Coming soon", icon: "👥", color: "#db2777" },
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

  return (
    <Screen edges={["left", "right"]}>
      <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator={false}>
        <HomeHeader user={user} onProfile={() => navigation.navigate("Profile")} />

        <View style={styles.body}>
          <SectionHeader title="Modules" />
          <View style={styles.grid}>
            {TILES.map((t) => {
              const active = !!t.target;
              return (
                <Card
                  key={t.key}
                  padded={false}
                  style={styles.tile}
                  onPress={active ? () => navigation.navigate(t.target as any) : undefined}
                >
                  <View style={styles.tileInner}>
                    <View style={[styles.tileIcon, { backgroundColor: withAlpha(t.color, 0.14) }]}>
                      <Text style={{ fontSize: 26 }}>{t.icon}</Text>
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

  grid: { flexDirection: "row", flexWrap: "wrap", gap: GAP },
  tile: {
    width: "47.8%",
    overflow: "hidden",
    ...shadow(1),
  },
  tileInner: { padding: spacing.lg, gap: spacing.xs, minHeight: 128, justifyContent: "flex-start" },
  tileIcon: {
    width: 52,
    height: 52,
    borderRadius: radius.lg,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: spacing.sm,
  },
  tileTitle: { ...type.h3, color: colors.text },
  tileSub: { ...type.caption, color: colors.textMuted },
  soon: { position: "absolute", top: spacing.md, right: spacing.md },
  tileBar: { height: 4, width: "100%" },
});
