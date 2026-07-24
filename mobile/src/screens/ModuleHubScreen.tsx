import { NativeStackScreenProps } from "@react-navigation/native-stack";
import React from "react";
import { ScrollView, StyleSheet, Text, View } from "react-native";

import { ListItem, SectionHeader } from "@/components/ui";
import { MODULES, ModuleKey, RESOURCES } from "@/config/catalog";
import { ModuleStackParams } from "@/navigation/types";
import { colors, radius, shadow, spacing, type } from "@/theme";

type Props = NativeStackScreenProps<ModuleStackParams, "Hub"> & { moduleKey: ModuleKey };

/** Module landing page: branded header + a sectioned menu of its resources. */
export function ModuleHubScreen({ navigation, moduleKey }: Props) {
  const mod = MODULES[moduleKey];

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
          <View style={{ gap: spacing.sm }}>
            {section.resourceKeys.map((key) => {
              const r = RESOURCES[key];
              return (
                <ListItem
                  key={key}
                  icon={r.icon}
                  accent={r.accent}
                  title={r.title}
                  subtitle={r.singular}
                  onPress={() => navigation.navigate("List", { resourceKey: key })}
                />
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
});
