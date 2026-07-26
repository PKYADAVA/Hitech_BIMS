import { NativeStackScreenProps } from "@react-navigation/native-stack";
import React, { useLayoutEffect, useState } from "react";
import { Alert, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { reviewChangeRequest } from "@/api/changeRequests";
import { retryMessage } from "@/api/sms";
import { Row } from "@/api/types";
import { RecordCard } from "@/components/RecordCard";
import { Badge, Button, Card, DetailRow, Divider, IconCircle } from "@/components/ui";
import { ChildConfig, RESOURCES } from "@/config/catalog";
import { isEditable } from "@/config/forms";
import { usePermissionsStore } from "@/store/permissionsStore";
import { ModuleStackParams } from "@/navigation/types";
import { queryClient } from "@/query/queryClient";
import { useResourceList } from "@/query/useResourceList";
import { colors, spacing, type } from "@/theme";
import { formatValue, humanizeKey, isEmpty } from "@/utils/format";

/** Line-items of a parent record, fetched by FK and shown (add/edit) in detail. */
function ChildSection({
  child,
  parentId,
  navigation,
}: {
  child: ChildConfig;
  parentId: number | string;
  navigation: Props["navigation"];
}) {
  const cfg = RESOURCES[child.resourceKey];
  const canAction = usePermissionsStore((s) => s.canAction);
  const canAdd = isEditable(cfg.key) && canAction(cfg.module, "add");
  const canEdit = isEditable(cfg.key) && canAction(cfg.module, "edit");
  const list = useResourceList<Row>(cfg.path, { [child.fkParam]: parentId });
  if (list.isLoading) return null;
  if (!canAdd && list.items.length === 0) return null;

  const openForm = (mode: "create" | "edit", item?: Row) =>
    navigation.navigate("Form", {
      resourceKey: cfg.key,
      mode,
      row: item,
      preset: mode === "create" ? { [child.fkParam]: String(parentId) } : undefined,
      onDoneGoBack: true,
    });

  return (
    <View style={{ gap: spacing.sm }}>
      <View style={styles.childHeader}>
        <Text style={styles.childTitle}>
          {cfg.title} ({list.items.length})
        </Text>
        {canAdd ? (
          <Pressable hitSlop={8} onPress={() => openForm("create")}>
            <Text style={styles.addLink}>＋ Add</Text>
          </Pressable>
        ) : null}
      </View>
      {list.items.map((item) => (
        <RecordCard
          key={String(item.id)}
          view={cfg.card(item)}
          icon={cfg.icon}
          accent={cfg.accent}
          onPress={() =>
            canEdit
              ? openForm("edit", item)
              : navigation.navigate("Detail", { resourceKey: cfg.key, row: item })
          }
        />
      ))}
    </View>
  );
}

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
  const canEdit =
    isEditable(config.key) && usePermissionsStore((s) => s.canAction)(config.module, "edit");

  useLayoutEffect(() => {
    navigation.setOptions({
      title: config.singular,
      headerRight: canEdit
        ? () => (
            <Pressable
              hitSlop={12}
              onPress={() =>
                config.key === "broiler-bird-sales"
                  ? navigation.navigate("BirdSaleForm", { mode: "edit", row })
                  : navigation.navigate("Form", { resourceKey: config.key, mode: "edit", row })
              }
            >
              <Text style={{ color: colors.onDark, ...type.title }}>Edit</Text>
            </Pressable>
          )
        : undefined,
    });
  }, [navigation, config.singular, config.key, row, canEdit]);

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

  const [reviewing, setReviewing] = useState(false);
  const canReview =
    config.key === "hatchery-change-requests" &&
    String(row.status ?? "").toLowerCase() === "pending";

  const onReview = (decision: "approve" | "reject") => {
    const verb = decision === "approve" ? "Approve" : "Reject";
    Alert.alert(verb, `${verb} this change request?`, [
      { text: "Cancel", style: "cancel" },
      {
        text: verb,
        style: decision === "reject" ? "destructive" : "default",
        onPress: async () => {
          setReviewing(true);
          try {
            const res = await reviewChangeRequest(row.id, decision);
            queryClient.invalidateQueries({ queryKey: ["list", "/hatchery/change-requests/"] });
            Alert.alert("Done", `Request ${res.status}.`, [
              { text: "OK", onPress: () => navigation.goBack() },
            ]);
          } catch (e) {
            Alert.alert("Failed", (e as Error)?.message ?? "Could not review request.");
          } finally {
            setReviewing(false);
          }
        },
      },
    ]);
  };

  const entries = Object.entries(row).filter(([k, v]) => {
    if (HIDDEN.test(k) || k.endsWith("_label") || isEmpty(v)) return false;
    // Many-to-many / list-of-ids fields: only show when we have a readable
    // label for them — never render a bare `[9]` id array.
    if (Array.isArray(v)) return !isEmpty(row[`${k}_label`]);
    return true;
  });
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
      {canReview ? (
        <View style={{ flexDirection: "row", gap: spacing.sm }}>
          <View style={{ flex: 1 }}>
            <Button title="Approve" loading={reviewing} onPress={() => onReview("approve")} />
          </View>
          <View style={{ flex: 1 }}>
            <Button title="Reject" variant="danger" onPress={() => onReview("reject")} />
          </View>
        </View>
      ) : null}

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

      {config.children?.map((child) => (
        <ChildSection key={child.resourceKey} child={child} parentId={row.id} navigation={navigation} />
      ))}

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
  childHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: spacing.xs },
  childTitle: { ...type.h3, color: colors.text },
  addLink: { ...type.title, color: colors.primary },
  footnote: { ...type.caption, color: colors.textFaint, textAlign: "center", marginTop: spacing.sm },
});
