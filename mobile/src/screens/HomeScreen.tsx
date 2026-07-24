import { BottomTabScreenProps } from "@react-navigation/bottom-tabs";
import React from "react";
import { ScrollView, StyleSheet, Text, View } from "react-native";

import { Badge, Card, Screen, SectionHeader } from "@/components/ui";
import { colors, radius, shadow, spacing, type, } from "@/theme";
import { withAlpha } from "@/components/ui";
import { TabParams } from "@/navigation/types";
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
  { key: "inventory", title: "Inventory", subtitle: "Coming soon", icon: "📦", color: "#0891b2" },
  { key: "sales", title: "Sales", subtitle: "Coming soon", icon: "💰", color: "#16a34a" },
  { key: "purchase", title: "Purchase", subtitle: "Coming soon", icon: "🛒", color: "#7c3aed" },
  { key: "hr", title: "HR", subtitle: "Coming soon", icon: "👥", color: "#db2777" },
];

export function HomeScreen({ navigation }: Props) {
  const user = useAuthStore((s) => s.user);
  const today = new Date().toLocaleDateString(undefined, {
    weekday: "long",
    day: "numeric",
    month: "long",
  });

  return (
    <Screen>
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        {/* Greeting */}
        <View>
          <Text style={styles.date}>{today}</Text>
          <Text style={styles.hello}>
            Hi, {user?.full_name || user?.username || "there"} 👋
          </Text>
          <Text style={styles.role}>
            {user?.role || "User"}
            {user?.department ? ` · ${user.department}` : ""}
          </Text>
        </View>

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
      </ScrollView>
    </Screen>
  );
}

const GAP = spacing.md;

const styles = StyleSheet.create({
  content: { padding: spacing.md, gap: spacing.sm, paddingBottom: spacing.xxl },
  date: { ...type.caption, color: colors.textMuted, textTransform: "uppercase", letterSpacing: 0.5 },
  hello: { ...type.h1, color: colors.text, marginTop: 2 },
  role: { ...type.body, color: colors.textMuted, marginTop: 2 },

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
