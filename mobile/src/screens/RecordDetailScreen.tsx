import { NativeStackScreenProps } from "@react-navigation/native-stack";
import React, { useLayoutEffect, useState } from "react";
import { Alert, Pressable, ScrollView, Text, View } from "react-native";

import { reviewChangeRequest } from "@/api/changeRequests";
import { retryMessage } from "@/api/sms";
import { Row } from "@/api/types";
import { RecordCard } from "@/components/RecordCard";
import { AppIcon } from "@/components/AppIcon";
import { Button, Card, DetailRow, Divider } from "@/components/ui";
import { ChildConfig, RESOURCES } from "@/config/catalog";
import { isEditable, isRecordEditable } from "@/config/forms";
import { usePermissionsStore } from "@/store/permissionsStore";
import { openRecordForm } from "@/navigation/openForm";
import { ModuleStackParams } from "@/navigation/types";
import { queryClient } from "@/query/queryClient";
import { useResourceList } from "@/query/useResourceList";
import { makeStyles, radius, shadow, spacing, type, useTheme, withAlpha } from "@/theme";
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
  const { colors } = useTheme();
  const styles = useStyles();
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
          <Pressable hitSlop={8} onPress={() => openForm("create")} style={styles.addLinkRow}>
            <AppIcon name="plus" size={16} color={colors.tint} />
            <Text style={styles.addLink}>Add</Text>
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
  const { colors } = useTheme();
  const styles = useStyles();
  const config = RESOURCES[route.params.resourceKey];
  const row: Row = route.params.row;
  const view = config.card(row);
  const canEdit =
    isRecordEditable(config.key) && usePermissionsStore((s) => s.canAction)(config.module, "edit");

  useLayoutEffect(() => {
    navigation.setOptions({
      title: config.singular,
      headerRight: canEdit
        ? () => (
            <Pressable
              hitSlop={12}
              onPress={() => openRecordForm(navigation, config.key, "edit", row)}
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

  // The header card already surfaces the record's identity (title + subtitle).
  // Don't repeat those same values as rows in Details — collect what the header
  // shows (title, plus each middot-separated subtitle segment) and skip any
  // field whose displayed value matches. e.g. for a User this drops the
  // Username/Email/Groups rows already shown above.
  const headerShown = new Set(
    [view.title, ...(view.subtitle ? view.subtitle.split(/\s*·\s*/) : [])]
      .map((s) => String(s).trim().toLowerCase())
      .filter((s) => s.length > 0)
  );

  const entries = Object.entries(row).filter(([k, v]) => {
    if (HIDDEN.test(k) || k.endsWith("_label") || isEmpty(v)) return false;
    // Many-to-many / list-of-ids fields: only show when we have a readable
    // label for them — never render a bare `[9]` id array.
    if (Array.isArray(v)) return !isEmpty(row[`${k}_label`]);
    return true;
  });
  const main = entries.filter(
    ([k, v]) => !AUDIT.has(k) && !headerShown.has(valueFor(k, v).trim().toLowerCase())
  );
  const audit = entries.filter(([k]) => AUDIT.has(k));

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      {/* Hero header — neutral dark card with a soft light glow for depth. The
          icon chip carries the module accent; title/subtitle stack beneath. */}
      <View style={[styles.hero, { backgroundColor: colors.primary }]}>
        <View style={styles.heroGlow} pointerEvents="none" />
        <View style={styles.heroTop}>
          <View style={[styles.heroIcon, { backgroundColor: config.accent }]}>
            <AppIcon emoji={config.icon} size={28} color={colors.onDark} />
          </View>
          {view.badge ? (
            <View style={styles.heroBadge}>
              <Text style={styles.heroBadgeText}>{view.badge.label}</Text>
            </View>
          ) : null}
        </View>
        <View style={styles.heroText}>
          <Text style={styles.title} numberOfLines={2}>
            {view.title}
          </Text>
          {view.subtitle ? <Text style={styles.subtitle}>{view.subtitle}</Text> : null}
        </View>
      </View>

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

const useStyles = makeStyles((colors) => ({
  screen: { flex: 1, backgroundColor: colors.bg },
  content: { padding: spacing.md, gap: spacing.md, paddingBottom: spacing.xxl },
  hero: {
    padding: spacing.lg,
    borderRadius: radius.lg,
    overflow: "hidden",
    ...shadow(2),
  },
  // Soft off-corner highlight so the banner reads as a designed surface rather
  // than a flat block of color.
  heroGlow: {
    position: "absolute",
    top: -60,
    right: -40,
    width: 180,
    height: 180,
    borderRadius: 90,
    backgroundColor: withAlpha("#ffffff", 0.1),
  },
  heroTop: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  heroIcon: {
    width: 56,
    height: 56,
    borderRadius: radius.md + 4,
    alignItems: "center",
    justifyContent: "center",
  },
  heroText: { marginTop: spacing.md, gap: 4 },
  title: { ...type.h1, color: colors.onDark },
  subtitle: { ...type.body, color: withAlpha("#ffffff", 0.85), lineHeight: 21 },
  heroBadge: {
    paddingHorizontal: spacing.sm + 2,
    paddingVertical: 4,
    borderRadius: radius.pill,
    backgroundColor: withAlpha("#ffffff", 0.22),
  },
  heroBadgeText: { ...type.caption, color: colors.onDark, fontWeight: "700" },
  groupTitle: {
    ...type.label,
    color: colors.textFaint,
    textTransform: "uppercase",
    letterSpacing: 0.5,
    marginBottom: spacing.xs,
  },
  childHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: spacing.xs },
  childTitle: { ...type.h3, color: colors.text },
  addLinkRow: { flexDirection: "row", alignItems: "center", gap: 2 },
  addLink: { ...type.title, color: colors.tint },
  footnote: { ...type.caption, color: colors.textFaint, textAlign: "center", marginTop: spacing.sm },
}));
