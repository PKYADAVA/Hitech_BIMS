import { NativeStackScreenProps } from "@react-navigation/native-stack";
import React, { useLayoutEffect, useState } from "react";
import { Alert, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { retryMessage } from "@/api/sms";
import { Row } from "@/api/types";
import { Badge, Button, Card, DetailRow, Divider, IconCircle } from "@/components/ui";
import { RESOURCES } from "@/config/catalog";
import { isEditable } from "@/config/forms";
import { ModuleStackParams } from "@/navigation/types";
import { queryClient } from "@/query/queryClient";
import { colors, spacing, type } from "@/theme";
import { formatValue, humanizeKey, isEmpty } from "@/utils/format";

const RETRYABLE = /fail|reject|expire|invalid|unknown/i;

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
    navigation.setOptions({
      title: config.singular,
      headerRight: isEditable(config.key)
        ? () => (
            <Pressable
              hitSlop={12}
              onPress={() =>
                navigation.navigate("Form", { resourceKey: config.key, mode: "edit", row })
              }
            >
              <Text style={{ color: colors.onDark, ...type.title }}>Edit</Text>
            </Pressable>
          )
        : undefined,
    });
  }, [navigation, config.singular, config.key, row]);

  // FKs come back as raw ids plus a `<fk>_label` companion (str of the related
  // row). Show the label as the value and hide the standalone `_label` field.
  const valueFor = (k: string, v: unknown): string => {
    const lbl = row[`${k}_label`];
    return isEmpty(lbl) ? formatValue(k, v) : String(lbl);
  };

  const [retrying, setRetrying] = useState(false);

  const onRetry = async () => {
    setRetrying(true);
    try {
      const res = await retryMessage(row.id);
      queryClient.invalidateQueries({ queryKey: ["list", "/sms/messages/"] });
      Alert.alert(
        res.sent ? "Retried ✓" : "Retry failed",
        res.sent ? `Status: ${res.status}` : res.error || res.status
      );
    } catch (e) {
      Alert.alert("Failed", (e as Error)?.message ?? "Retry failed.");
    } finally {
      setRetrying(false);
    }
  };

  const canRetry = config.key === "sms-messages" && RETRYABLE.test(String(row.status ?? ""));

  const entries = Object.entries(row).filter(
    ([k, v]) => !HIDDEN.test(k) && !k.endsWith("_label") && !isEmpty(v)
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

      {config.key === "sms-templates" ? (
        <Button title="Send SMS" onPress={() => navigation.navigate("SmsSend", { row })} />
      ) : null}
      {canRetry ? <Button title="Retry send" loading={retrying} onPress={onRetry} /> : null}

      <Card>
        <Text style={styles.groupTitle}>Details</Text>
        {main.map(([k, v], i) => (
          <View key={k}>
            {i > 0 ? <Divider /> : null}
            <DetailRow label={humanizeKey(k)} value={valueFor(k, v)} />
          </View>
        ))}
      </Card>

      {audit.length > 0 ? (
        <Card>
          <Text style={styles.groupTitle}>Record</Text>
          {audit.map(([k, v], i) => (
            <View key={k}>
              {i > 0 ? <Divider /> : null}
              <DetailRow label={humanizeKey(k)} value={valueFor(k, v)} />
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
