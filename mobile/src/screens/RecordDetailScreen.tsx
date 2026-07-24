import { NativeStackScreenProps } from "@react-navigation/native-stack";
import React, { useLayoutEffect } from "react";
import { ScrollView, StyleSheet, Text, View } from "react-native";

import { Row } from "@/api/types";
import { Badge, Card, DetailRow, Divider, IconCircle } from "@/components/ui";
import { RESOURCES } from "@/config/catalog";
import { ModuleStackParams } from "@/navigation/types";
import { colors, spacing, type } from "@/theme";
import { formatValue, humanizeKey, isEmpty } from "@/utils/format";

type Props = NativeStackScreenProps<ModuleStackParams, "Detail">;

/** Fields never shown as text (media/blobs/geo/internal). */
const HIDDEN = /(^id$|_image$|_photo$|photo$|_upload|_file$|_copy$|documents?$|latitude$|longitude$)/;
/** Fields grouped under "Record" instead of the main details. */
const AUDIT = new Set([
  "created_at",
  "updated_at",
  "created_on",
  "updated_on",
  "entry_by",
  "entry_time",
  "created_by",
  "modified_by",
]);

export function RecordDetailScreen({ route, navigation }: Props) {
  const config = RESOURCES[route.params.resourceKey];
  const row: Row = route.params.row;
  const view = config.card(row);

  useLayoutEffect(() => {
    navigation.setOptions({ title: config.singular });
  }, [navigation, config.singular]);

  const entries = Object.entries(row).filter(
    ([k, v]) => !HIDDEN.test(k) && !isEmpty(v)
  );
  const main = entries.filter(([k]) => !AUDIT.has(k));
  const audit = entries.filter(([k]) => AUDIT.has(k));

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      {/* Header card */}
      <Card style={styles.header}>
        <IconCircle icon={config.icon} color={config.accent} size={52} />
        <View style={{ flex: 1, gap: 4 }}>
          <Text style={styles.title}>{view.title}</Text>
          {view.subtitle ? <Text style={styles.subtitle}>{view.subtitle}</Text> : null}
          {view.badge ? (
            <View style={{ flexDirection: "row", marginTop: 4 }}>
              <Badge label={view.badge.label} tone={view.badge.tone} />
            </View>
          ) : null}
        </View>
      </Card>

      <Card>
        <Text style={styles.groupTitle}>Details</Text>
        {main.map(([k, v], i) => (
          <View key={k}>
            {i > 0 ? <Divider /> : null}
            <DetailRow label={humanizeKey(k)} value={formatValue(k, v)} />
          </View>
        ))}
      </Card>

      {audit.length > 0 ? (
        <Card>
          <Text style={styles.groupTitle}>Record</Text>
          {audit.map(([k, v], i) => (
            <View key={k}>
              {i > 0 ? <Divider /> : null}
              <DetailRow label={humanizeKey(k)} value={formatValue(k, v)} />
            </View>
          ))}
        </Card>
      ) : null}

      <Text style={styles.footnote}>Record #{row.id}</Text>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.bg },
  content: { padding: spacing.md, gap: spacing.md, paddingBottom: spacing.xxl },
  header: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  title: { ...type.h2, color: colors.text },
  subtitle: { ...type.body, color: colors.textMuted },
  groupTitle: {
    ...type.label,
    color: colors.textFaint,
    textTransform: "uppercase",
    letterSpacing: 0.5,
    marginBottom: spacing.xs,
  },
  footnote: { ...type.caption, color: colors.textFaint, textAlign: "center", marginTop: spacing.sm },
});
