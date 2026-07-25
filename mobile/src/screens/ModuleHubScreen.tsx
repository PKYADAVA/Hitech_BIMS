import { NativeStackScreenProps } from "@react-navigation/native-stack";
import React from "react";
import { ScrollView, StyleSheet, Text, useWindowDimensions, View } from "react-native";

import { Card, IconCircle, SectionHeader } from "@/components/ui";
import { MODULES, ModuleKey, RESOURCES } from "@/config/catalog";
import { ModuleStackParams } from "@/navigation/types";
import { colors, radius, shadow, spacing, type } from "@/theme";

type Props = NativeStackScreenProps<ModuleStackParams, "Hub"> & { moduleKey: ModuleKey };

const COLS = 3;

/** Module landing page: branded header + a sectioned grid of small resource tiles. */
export function ModuleHubScreen({ navigation, moduleKey }: Props) {
  const mod = MODULES[moduleKey];
  const { width } = useWindowDimensions();
  const tileW = (width - spacing.md * 2 - spacing.sm * (COLS - 1)) / COLS;

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      {/* Branded header banner */}
      <View style={[styles.banner, { backgroundColor: mod.color }, shadow(2)]}>
        <Text style={styles.bannerIcon}>{mod.icon}</Text>
        <View style={{ flex: 1 }}>
          <Text style={styles.bannerTitle}>{mod.title}</Text>
          <Text style={styles.bannerTagline}>{mod.tagline}</Text>
        </View>
      </View>

      {mod.sections.map((section) => (
        <View key={section.title}>
          <SectionHeader title={section.title} />
          <View style={styles.grid}>
            {section.resourceKeys.map((key) => {
              const r = RESOURCES[key];
              return (
                <Card
                  key={key}
                  padded={false}
                  style={{ ...styles.tile, width: tileW }}
                  onPress={() => navigation.navigate("List", { resourceKey: key })}
                >
                  <IconCircle icon={r.icon} color={r.accent} size={40} />
                  <Text style={styles.tileTitle} numberOfLines={2}>
                    {r.title}
                  </Text>
                </Card>
              );
            })}
          </View>
        </View>
      ))}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.bg },
  content: { padding: spacing.md, paddingBottom: spacing.xxl },
  banner: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    borderRadius: radius.xl,
    padding: spacing.lg,
  },
  bannerIcon: { fontSize: 40 },
  bannerTitle: { ...type.h1, color: colors.onDark },
  bannerTagline: { ...type.body, color: "rgba(255,255,255,0.85)", marginTop: 2 },

  grid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  tile: {
    minHeight: 104,
    alignItems: "center",
    justifyContent: "center",
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.xs,
    gap: spacing.sm,
    ...shadow(1),
  },
  tileTitle: {
    ...type.caption,
    fontWeight: "700",
    color: colors.text,
    textAlign: "center",
  },
});
