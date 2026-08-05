/**
 * Reports & Analytics — every report the user may open, in one place.
 *
 * The reference gives reports a module of their own rather than leaving them
 * scattered one hub at a time, which is how someone looking for "the mortality
 * one" actually thinks about them. The list is assembled from the module
 * catalog at runtime, so a report added to a module appears here without being
 * registered twice.
 *
 * Grouped by module, and filtered by the same rule the hubs use: a report with
 * no tab mapping is module-gated, otherwise it needs its own tab. A module
 * whose reports are all hidden does not appear.
 */
import { NativeStackScreenProps } from "@react-navigation/native-stack";
import React from "react";
import { Pressable, ScrollView, Text, View } from "react-native";

import { REPORT_TABS } from "@/api/permissions";
import { AppIcon } from "@/components/AppIcon";
import { Card, SectionHeader } from "@/components/ui";
import { MODULES, ModuleKey } from "@/config/catalog";
import { usePermissionsStore } from "@/store/permissionsStore";
import { makeStyles, radius, spacing, type, withAlpha } from "@/theme";

/** Declared here rather than in navigation/types so this screen owns its own
 *  route shape; it is a two-screen stack and nothing else needs to know it. */
export type ReportsStackParams = {
  ReportsHub: undefined;
  Report: { title: string; path: string };
};

type Props = NativeStackScreenProps<ReportsStackParams, "ReportsHub">;

export function ReportsHubScreen({ navigation }: Props) {
  const styles = useStyles();
  const canTab = usePermissionsStore((s) => s.canTab);
  const canModule = usePermissionsStore((s) => s.canModule);
  const permsLoaded = usePermissionsStore((s) => s.loaded);
  const navOrder = usePermissionsStore((s) => s.navOrder);

  const groups = React.useMemo(() => {
    const keys = (navOrder.length ? navOrder : Object.keys(MODULES)) as ModuleKey[];
    return keys
      .map((key) => MODULES[key])
      .filter(Boolean)
      .filter((mod) => !permsLoaded || canModule(mod.key))
      .map((mod) => ({
        mod,
        reports: (mod.reports ?? []).filter(
          (rep) => !REPORT_TABS[rep.key] || canTab(REPORT_TABS[rep.key])
        ),
      }))
      .filter((g) => g.reports.length > 0);
  }, [navOrder, permsLoaded, canModule, canTab]);

  if (!groups.length) {
    return (
      <View style={styles.empty}>
        <Text style={styles.emptyText}>No reports available to you.</Text>
      </View>
    );
  }

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      {groups.map(({ mod, reports }) => (
        <View key={mod.key}>
          <SectionHeader title={`${mod.title} Reports`} />
          <Card padded={false} style={styles.group}>
            {reports.map((rep, i) => (
              <Pressable
                key={rep.key}
                style={[styles.row, i > 0 && styles.rowDivider]}
                onPress={() =>
                  navigation.navigate("Report", { title: rep.title, path: rep.path })
                }
                accessibilityRole="button"
              >
                <View style={[styles.icon, { backgroundColor: withAlpha(mod.color, 0.14) }]}>
                  <AppIcon emoji={rep.icon} size={18} color={mod.color} />
                </View>
                <Text style={styles.title} numberOfLines={1}>{rep.title}</Text>
                <AppIcon name="chevron-right" size={20} />
              </Pressable>
            ))}
          </Card>
        </View>
      ))}
      <View style={{ height: spacing.xxl }} />
    </ScrollView>
  );
}

const useStyles = makeStyles((colors) => ({
  screen: { flex: 1, backgroundColor: colors.bg },
  content: { padding: spacing.md },
  group: { marginBottom: spacing.md, overflow: "hidden" },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.md,
  },
  rowDivider: { borderTopWidth: 1, borderTopColor: colors.border },
  icon: {
    width: 34, height: 34, borderRadius: radius.sm,
    alignItems: "center", justifyContent: "center",
  },
  title: { ...type.body, color: colors.text, flex: 1 },
  empty: { flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.xl },
  emptyText: { ...type.body, color: colors.textMuted },
}));
