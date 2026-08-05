import { NativeStackScreenProps } from "@react-navigation/native-stack";
import React from "react";
import { ScrollView, Text, useWindowDimensions, View } from "react-native";

import { REPORT_TABS, RESOURCE_TABS } from "@/api/permissions";
import { Card, IconCircle, SectionHeader } from "@/components/ui";
import { MODULES, ModuleKey, RESOURCES } from "@/config/catalog";
import { ModuleStackParams } from "@/navigation/types";
import { Overview, useOverview } from "@/api/stats";
import { usePermissionsStore } from "@/store/permissionsStore";
import { makeStyles, shadow, spacing, type } from "@/theme";

type Props = NativeStackScreenProps<ModuleStackParams, "Hub"> & { moduleKey: ModuleKey };

const COLS = 3;

const n = (v?: number | null, dp = 0) =>
  v === undefined || v === null ? "–" : v.toLocaleString(undefined, {
    minimumFractionDigits: dp, maximumFractionDigits: dp,
  });

/**
 * The strip of headline numbers the reference puts under each module's header.
 *
 * Only what /stats/overview already reports — a module with nothing to say
 * shows nothing, rather than a row of dashes pretending to be a KPI. The
 * figures are the signed-in user's, because the endpoint scopes them.
 */
function moduleKpis(moduleKey: ModuleKey, ov?: Overview): [string, string][] {
  switch (moduleKey) {
    case "broiler":
      return [
        ["Active Batches", n(ov?.broiler.active_batches)],
        ["Live Birds", n(ov?.broiler.live_birds)],
        ["FCR", ov?.broiler.fcr == null ? "–" : n(ov.broiler.fcr, 3)],
      ];
    case "hatchery":
      return [
        ["Egg Purchases", n(ov?.hatchery.egg_purchases_today)],
        ["Hatch Entries", n(ov?.hatchery.hatch_entries_today)],
        ["Chicks", n(ov?.hatchery.chicks_today)],
      ];
    case "inventory":
      return [
        ["Items", n(ov?.inventory?.items)],
        ["Transfers Today", n(ov?.inventory?.transfers_today)],
      ];
    case "account":
      return [
        ["Vouchers Today", n(ov?.account?.vouchers_today)],
        ["Accounts", n(ov?.account?.accounts)],
      ];
    case "sms":
      return [
        ["Sent Today", n(ov?.sms.sent_today)],
        ["Failed", n(ov?.sms.failed_today)],
      ];
    default:
      return [];
  }
}

function KpiStrip({ items, color }: { items: [string, string][]; color: string }) {
  const styles = useStyles();
  if (!items.length) return null;
  return (
    <View style={styles.kpiRow}>
      {items.map(([label, value]) => (
        <View key={label} style={[styles.kpiCell, { borderTopColor: color }]}>
          <Text style={styles.kpiValue}>{value}</Text>
          <Text style={styles.kpiLabel} numberOfLines={1}>{label}</Text>
        </View>
      ))}
    </View>
  );
}

/** Module landing page: branded header + a sectioned grid of small resource tiles. */
export function ModuleHubScreen({ navigation, moduleKey }: Props) {
  const styles = useStyles();
  const mod = MODULES[moduleKey];
  const { width } = useWindowDimensions();
  const tileW = (width - spacing.md * 2 - spacing.sm * (COLS - 1)) / COLS;
  const canTab = usePermissionsStore((s) => s.canTab);
  const { data: ov } = useOverview();
  // A resource tile shows if it has no tab mapping (module-gated) or the user
  // can view its tab. Sections with no visible tiles are hidden entirely.
  const visibleKeys = (keys: string[]) =>
    [...keys]
      .filter((k) => !RESOURCE_TABS[k] || canTab(RESOURCE_TABS[k]))
      .sort((a, b) => RESOURCES[a].title.localeCompare(RESOURCES[b].title));

  // Reports used to render unconditionally, so a user saw every report in a
  // module they could open regardless of what the web matrix said about the
  // report itself. Same rule as the resource tiles now: no mapping means
  // module-gated, otherwise it needs the tab.
  const reports = (mod.reports ?? []).filter(
    (rep) => !REPORT_TABS[rep.key] || canTab(REPORT_TABS[rep.key])
  );

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      {/* Header already shows the module name — only its tagline adds context. */}
      <Text style={styles.tagline}>{mod.tagline}</Text>

      <KpiStrip items={moduleKpis(moduleKey, ov)} color={mod.color} />

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

      {reports.length > 0 ? (
        <View>
          <SectionHeader title="Reports" />
          <View style={styles.grid}>
            {reports.map((rep) => (
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

const useStyles = makeStyles((colors) => ({
  screen: { flex: 1, backgroundColor: colors.bg },
  content: { padding: spacing.md, paddingBottom: spacing.xxl },
  tagline: { ...type.caption, color: colors.textMuted, marginBottom: spacing.xs, paddingHorizontal: spacing.xs },
  kpiRow: { flexDirection: "row", gap: spacing.sm, marginBottom: spacing.md },
  kpiCell: {
    flex: 1,
    backgroundColor: colors.surface,
    borderRadius: 12,
    // A hairline of the module's colour, so the strip reads as belonging to
    // this module rather than as a generic card.
    borderTopWidth: 3,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.sm,
    ...shadow(1),
  },
  kpiValue: { ...type.h3, color: colors.text },
  kpiLabel: { ...type.caption, color: colors.textMuted, marginTop: 2 },

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
}));
