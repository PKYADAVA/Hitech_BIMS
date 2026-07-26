import { NativeStackScreenProps } from "@react-navigation/native-stack";
import React from "react";
import { ScrollView, StyleSheet, Text, useWindowDimensions, View } from "react-native";

import { RESOURCE_TABS } from "@/api/permissions";
import { Card, IconCircle, SectionHeader } from "@/components/ui";
import { MODULES, ModuleKey, RESOURCES } from "@/config/catalog";
import { ModuleStackParams } from "@/navigation/types";
import { usePermissionsStore } from "@/store/permissionsStore";
import { colors, shadow, spacing, type } from "@/theme";

type Props = NativeStackScreenProps<ModuleStackParams, "Hub"> & { moduleKey: ModuleKey };

const COLS = 3;

/** Module landing page: branded header + a sectioned grid of small resource tiles. */
export function ModuleHubScreen({ navigation, moduleKey }: Props) {
  const mod = MODULES[moduleKey];
  const { width } = useWindowDimensions();
  const tileW = (width - spacing.md * 2 - spacing.sm * (COLS - 1)) / COLS;
  const canTab = usePermissionsStore((s) => s.canTab);
  // A resource tile shows if it has no tab mapping (module-gated) or the user
  // can view its tab. Sections with no visible tiles are hidden entirely.
  const visibleKeys = (keys: string[]) =>
    [...keys]
      .filter((k) => !RESOURCE_TABS[k] || canTab(RESOURCE_TABS[k]))
      .sort((a, b) => RESOURCES[a].title.localeCompare(RESOURCES[b].title));

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      {/* Header already shows the module name — only its tagline adds context. */}
      <Text style={styles.tagline}>{mod.tagline}</Text>

      {mod.sections.map((section) => {
        const keys = visibleKeys(section.resourceKeys);
        if (keys.length === 0) return null;
        return (
        <View key={section.title}>
          <SectionHeader title={section.title} />
          <View style={styles.grid}>
            {keys.map((key) => {
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
        );
      })}

      {mod.reports && mod.reports.length > 0 ? (
        <View>
          <SectionHeader title="Reports" />
          <View style={styles.grid}>
            {mod.reports.map((rep) => (
              <Card
                key={rep.key}
                padded={false}
                style={{ ...styles.tile, width: tileW }}
                onPress={() => navigation.navigate("Report", { title: rep.title, path: rep.path })}
              >
                <IconCircle icon={rep.icon} color={mod.color} size={40} />
                <Text style={styles.tileTitle} numberOfLines={2}>
                  {rep.title}
                </Text>
              </Card>
            ))}
          </View>
        </View>
      ) : null}

      {mod.tools && mod.tools.length > 0 ? (
        <View>
          <SectionHeader title="Tools" />
          <View style={styles.grid}>
            {mod.tools.map((tool) => (
              <Card
                key={tool.key}
                padded={false}
                style={{ ...styles.tile, width: tileW }}
                onPress={() => navigation.navigate(tool.screen)}
              >
                <IconCircle icon={tool.icon} color={mod.color} size={40} />
                <Text style={styles.tileTitle} numberOfLines={2}>
                  {tool.title}
                </Text>
              </Card>
            ))}
          </View>
        </View>
      ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.bg },
  content: { padding: spacing.md, paddingBottom: spacing.xxl },
  tagline: { ...type.caption, color: colors.textMuted, marginBottom: spacing.xs, paddingHorizontal: spacing.xs },

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
