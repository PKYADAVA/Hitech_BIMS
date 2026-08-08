import { NativeStackScreenProps } from "@react-navigation/native-stack";
import React, { useLayoutEffect, useState } from "react";
import {
  Alert, Image, Linking, Modal, Pressable, ScrollView, Text, View,
} from "react-native";

import { MEDIA_BASE_URL } from "@/config";
import { reviewChangeRequest } from "@/api/changeRequests";
import { retryMessage } from "@/api/sms";
import { Row } from "@/api/types";
import { RecordCard } from "@/components/RecordCard";
import { AppIcon } from "@/components/AppIcon";
import { Button, Card, DetailRow, Divider } from "@/components/ui";
import { ChildConfig, RESOURCES } from "@/config/catalog";
import { isEditable, isRecordEditable } from "@/config/forms";
import { hasCreateForm } from "@/navigation/openForm";
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
  const canResource = usePermissionsStore((s) => s.canResource);
  const canAdd = hasCreateForm(cfg.key) && canResource(cfg.key, cfg.module, "add");
  const canEdit = isEditable(cfg.key) && canResource(cfg.key, cfg.module, "edit");
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
/** Image fields — rendered as photo thumbnails instead of hidden. */
const IMAGE_KEY = /(_image$|image$|_photo$|photo$)/;
/**
 * A stored file's absolute address.
 *
 * The API returns media as a server-relative path ("/media/..."), which a
 * browser resolves against the page it is on and a phone cannot resolve at
 * all. The base the client already talks to is the one to hang it off.
 */
function mediaUrl(url: string): string {
  if (/^https?:\/\//i.test(url)) return url;
  return `${MEDIA_BASE_URL}${url.startsWith("/") ? "" : "/"}${url}`;
}

/** True when a value looks like a usable image URL. */
const isImageUrl = (v: unknown): v is string =>
  typeof v === "string" && /^https?:\/\//i.test(v);

/**
 * True when an attachment is something that can be shown rather than opened.
 *
 * Judged on the extension, not the protocol: an attachment's url arrives as a
 * server-relative path, so the http(s) test above calls every one of them a
 * document and a farm's photographs rendered as filenames in grey boxes.
 */
const looksLikeImage = (url?: string): boolean =>
  !!url && /\.(jpe?g|png|gif|webp|heic|bmp)(\?|$)/i.test(url);
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
    isRecordEditable(config.key) &&
    usePermissionsStore((s) => s.canResource)(config.key, config.module, "edit");

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

  // Image fields (mort/cull/feed photos, farmer photo, etc.) are hidden from
  // the text rows but shown here as tappable thumbnails.
  const images = Object.entries(row).filter(
    ([k, v]) => IMAGE_KEY.test(k) && isImageUrl(v)
  ) as [string, string][];

  /**
   * Which picture is open, if any.
   *
   * A thumbnail is for finding the right one; it is too small to read a cheque
   * or a licence off, which is what these are. Tapping used to hand the file to
   * the browser and leave the record behind — now it opens over the page and
   * closes back onto it.
   */
  const [viewing, setViewing] = useState<{ uri: string; label: string } | null>(null);

  /**
   * Attachments carried in a `files` list rather than as fields of their own.
   *
   * A farm capture keeps its photographs and scans in a child table, so none
   * of them matched the field-name rule above and View showed a visit with no
   * evidence at all — the one thing the visit exists to record. The web
   * register renders them; this is the same list, read the same way.
   */
  const files = (Array.isArray(row.files) ? row.files : []) as {
    id?: number; kind?: string; label?: string; name?: string; url?: string;
  }[];
  const attachments = files.filter((f) => f && f.url);

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

      {images.length > 0 ? (
        <Card>
          <View style={styles.photoGrid}>
            {images.map(([k, uri]) => (
              <Pressable
                key={k}
                style={styles.photoItem}
                onPress={() => setViewing({ uri, label: humanizeKey(k) })}
              >
                <Image source={{ uri }} style={styles.photo} resizeMode="cover" />
                <Text style={styles.photoLabel} numberOfLines={1}>
                  {humanizeKey(k)}
                </Text>
              </Pressable>
            ))}
          </View>
        </Card>
      ) : null}

      {attachments.length > 0 ? (
        <Card>
          <Text style={styles.groupTitle}>
            Attachments <Text style={styles.photoLabel}>{attachments.length}</Text>
          </Text>
          <View style={styles.photoGrid}>
            {attachments.map((f, i) => {
              const label = f.label || humanizeKey(f.kind ?? "File");
              const uri = mediaUrl(f.url!);
              const image = looksLikeImage(f.url);
              return (
                <Pressable
                  key={f.id ?? `${f.kind}-${i}`}
                  style={styles.thumbItem}
                  // A picture opens over the record; anything else has to go
                  // to whatever on the device knows how to read it.
                  onPress={() => (image
                    ? setViewing({ uri, label })
                    : Linking.openURL(uri))}
                >
                  {/* A scan is as often a PDF as a photograph. Both are worth
                      listing and both open; only one of them can be shown. */}
                  {image ? (
                    <Image source={{ uri }} style={styles.thumb} resizeMode="cover" />
                  ) : (
                    <View style={[styles.thumb, styles.fileTile]}>
                      <AppIcon name="file-document-outline" size={20}
                               color={colors.textMuted} />
                    </View>
                  )}
                  <Text style={styles.thumbLabel} numberOfLines={2}>{label}</Text>
                </Pressable>
              );
            })}
          </View>
        </Card>
      ) : null}

      <Modal
        visible={!!viewing}
        transparent
        animationType="fade"
        onRequestClose={() => setViewing(null)}
      >
        {/* Tapping anywhere closes: on a picture opened by accident that is
            the only gesture anyone tries. */}
        <Pressable style={styles.viewerBack} onPress={() => setViewing(null)}>
          <View style={styles.viewerBar}>
            <Text style={styles.viewerTitle} numberOfLines={1}>
              {viewing?.label ?? ""}
            </Text>
            <Pressable hitSlop={12} onPress={() => setViewing(null)}
                       accessibilityRole="button" accessibilityLabel="Close">
              <AppIcon name="close" size={24} color="#fff" />
            </Pressable>
          </View>
          {viewing ? (
            <Image source={{ uri: viewing.uri }} style={styles.viewerImage}
                   resizeMode="contain" />
          ) : null}
          <Pressable style={styles.viewerOpen}
                     onPress={() => viewing && Linking.openURL(viewing.uri)}>
            <AppIcon name="open-in-new" size={16} color="#fff" />
            <Text style={styles.viewerOpenText}>Open full size</Text>
          </Pressable>
        </Pressable>
      </Modal>

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
  photoGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  photoItem: { width: "31%", gap: 4 },
  photo: {
    width: "100%",
    aspectRatio: 1,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceAlt,
    borderWidth: 1,
    borderColor: colors.border,
  },
  fileTile: {
    alignItems: "center", justifyContent: "center",
    backgroundColor: colors.surfaceAlt, padding: spacing.xs,
  },
  // Small on purpose: a thumbnail is for picking the right one out, and a row
  // of them says at a glance how much evidence a visit carries. Reading it is
  // what the viewer is for.
  thumbItem: { width: 76, gap: 4 },
  thumb: {
    width: 76, height: 76, borderRadius: radius.md,
    backgroundColor: colors.surfaceAlt,
    borderWidth: 1, borderColor: colors.border,
  },
  thumbLabel: { ...type.caption, fontSize: 10, color: colors.textMuted },

  viewerBack: {
    flex: 1, backgroundColor: "rgba(0,0,0,0.92)",
    alignItems: "center", justifyContent: "center",
  },
  viewerBar: {
    position: "absolute", top: 0, left: 0, right: 0,
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.lg, paddingVertical: spacing.lg, gap: spacing.md,
  },
  viewerTitle: { ...type.title, color: "#fff", flex: 1 },
  viewerImage: { width: "94%", height: "72%" },
  viewerOpen: {
    position: "absolute", bottom: spacing.xl,
    flexDirection: "row", alignItems: "center", gap: spacing.xs,
    paddingHorizontal: spacing.lg, paddingVertical: spacing.sm,
    borderRadius: radius.pill ?? 999, borderWidth: 1, borderColor: "#ffffff55",
  },
  viewerOpenText: { ...type.label, color: "#fff" },
  photoLabel: { ...type.label, color: colors.textMuted },
}));
