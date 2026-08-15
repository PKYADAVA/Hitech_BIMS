import { NativeStackScreenProps } from "@react-navigation/native-stack";
import React, { useEffect, useLayoutEffect, useState } from "react";
import { ActivityIndicator, Image, Pressable, ScrollView, Text, View } from "react-native";

import { listResource } from "@/api/resources";
import { Row } from "@/api/types";
import { capturePhoto, CapturePermissionError, pickPhoto } from "@/capture";
import { AppIcon } from "@/components/AppIcon";
import { ModuleStackParams } from "@/navigation/types";
import { queryClient } from "@/query/queryClient";
import { makeStyles, radius, spacing, type, useTheme } from "@/theme";
import { writeThrough } from "@/net/writeThrough";
import { notify } from "@/ui/confirm";

type Props = NativeStackScreenProps<ModuleStackParams, "BirdSalePhotos">;

/**
 * Add evidence to a lifting that is already filed.
 *
 * The photographs are the point of raising a bird sale on the phone, but they
 * are not always there when the sale is: the truck is loaded before the
 * weighbridge slip exists, and a sale raised at the desk from a slip brought
 * back has no pictures at all. Opening the whole sale form to attach one
 * photograph means re-submitting a record that is already right, so the
 * register offers this instead — the shots, and nothing else.
 *
 * What is already filed is shown but not touched: this screen only adds. The
 * per-kind cap counts held and pending together, so the Add tile goes at the
 * same point the server would start refusing (BirdSalePhoto.MAX_PER_KIND).
 */

const SALES_PATH = "/broiler/bird-sales/";
const PHOTOS_PATH = "/broiler/bird-sale-photos/";

/** Mirrors `BirdSalePhoto.KIND_CHOICES`, in the order the sale form asks. */
const PHOTO_KINDS = [
  { kind: "truck", label: "Truck Photo" },
  { kind: "birds", label: "Birds Photo" },
  { kind: "weighbridge", label: "Weighbridge Slip" },
  { kind: "other", label: "Add More" },
] as const;

type PhotoKind = (typeof PHOTO_KINDS)[number]["kind"];

/** Server-side cap (`BirdSalePhoto.MAX_PER_KIND`). */
const MAX_PER_KIND = 5;

const noPhotos = (): Record<PhotoKind, string[]> =>
  ({ truck: [], birds: [], weighbridge: [], other: [] });

const str = (v: unknown) => (v == null ? "" : String(v));

export function BirdSalePhotosScreen({ navigation, route }: Props) {
  const styles = useStyles();
  const { colors } = useTheme();
  const row = route.params.row;
  const saleId = row.id as number;

  const [held, setHeld] = useState<Record<PhotoKind, string[]>>(noPhotos);
  const [pending, setPending] = useState<Record<PhotoKind, string[]>>(noPhotos);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useLayoutEffect(() => {
    navigation.setOptions({ title: `Photos · ${str(row.sale_no || row.doc_no)}` });
  }, [navigation, row.sale_no, row.doc_no]);

  useEffect(() => {
    (async () => {
      try {
        const page = await listResource<Row>(PHOTOS_PATH, { sale: saleId, page_size: 100 });
        const found = noPhotos();
        for (const p of page.items) {
          const kind = str(p.kind) as PhotoKind;
          const url = str(p.image);
          if (url && kind in found) found[kind].push(url);
        }
        setHeld(found);
      } catch {
        // Shown as empty rather than as a failure: the count only decides when
        // the Add tile goes, and the server enforces the cap for real.
        setError("Could not read what is already filed — anything added here still uploads.");
      } finally {
        setLoading(false);
      }
    })();
  }, [saleId]);

  const add = async (kind: PhotoKind, fromGallery = false) => {
    try {
      const shot = fromGallery ? await pickPhoto() : await capturePhoto();
      if (shot) setPending((cur) => ({ ...cur, [kind]: [...cur[kind], shot.uri] }));
    } catch (e) {
      if (e instanceof CapturePermissionError) {
        notify(
          e.kind === "camera" ? "Camera needed" : "Photos needed",
          `Allow ${e.kind === "camera" ? "camera" : "photo library"} access to attach evidence.`,
        );
      }
    }
  };

  const drop = (kind: PhotoKind, uri: string) =>
    setPending((cur) => ({ ...cur, [kind]: cur[kind].filter((u) => u !== uri) }));

  const count = PHOTO_KINDS.reduce((n, { kind }) => n + pending[kind].length, 0);

  const upload = async () => {
    setError("");
    setSaving(true);
    const failed: string[] = [];
    let queued = false;
    for (const { kind, label } of PHOTO_KINDS) {
      for (const uri of pending[kind]) {
        try {
          const written = await writeThrough({
            type: "photo", label: "Bird Sale photo",
            method: "POST", path: PHOTOS_PATH,
            body: { fields: { sale: saleId, kind }, files: [{ field: "image", uri }] },
          });
          if (written.queued) queued = true;
        } catch {
          failed.push(label);
        }
      }
    }
    setSaving(false);

    if (failed.length) {
      // The ones that landed are filed; only the rest are left on screen, so
      // pressing again retries what failed instead of duplicating what didn't.
      setPending((cur) => {
        const next = noPhotos();
        PHOTO_KINDS.forEach(({ kind, label }) => {
          if (failed.includes(label)) next[kind] = cur[kind];
        });
        return next;
      });
      setError(`Could not upload: ${[...new Set(failed)].join(", ")}. Press Upload to try again.`);
      return;
    }
    if (queued) {
      await notify("Saved on this phone",
        "No signal — these photos are stored on the device and will go to the "
        + "ERP by themselves once you are back in range.");
    }
    queryClient.invalidateQueries({ queryKey: ["list", SALES_PATH] });
    queryClient.invalidateQueries({ queryKey: ["list", PHOTOS_PATH] });
    navigation.goBack();
  };

  return (
    <View style={styles.screen}>
      <ScrollView contentContainerStyle={styles.body}>
        <Text style={styles.intro}>
          {str(row.farm_label || row.farm_name)} · {str(row.date)}
        </Text>
        <Text style={styles.hint}>
          Photographs are only added here — what is already filed stays as it is.
        </Text>
        {error ? <Text style={styles.error}>{error}</Text> : null}

        {loading ? (
          <ActivityIndicator color={colors.tint} style={{ marginTop: spacing.lg }} />
        ) : (
          PHOTO_KINDS.map(({ kind, label }) => (
            <Slot
              key={kind}
              label={label}
              held={held[kind]}
              pending={pending[kind]}
              onAdd={() => add(kind, kind === "other")}
              onDrop={(u) => drop(kind, u)}
            />
          ))
        )}
      </ScrollView>

      <View style={styles.footer}>
        <Pressable style={[styles.cancel, { borderColor: colors.danger }]}
                   onPress={() => navigation.goBack()} disabled={saving}>
          <AppIcon name="close" size={18} color={colors.danger} />
          <Text style={[styles.cancelText, { color: colors.danger }]}>Cancel</Text>
        </Pressable>
        <Pressable style={[styles.save, { backgroundColor: colors.tint },
                           (saving || !count) && { opacity: 0.55 }]}
                   onPress={upload} disabled={saving || !count}>
          <AppIcon name="cloud-upload-outline" size={18} color={colors.onDark} />
          <Text style={styles.saveText}>
            {saving ? "Uploading…" : count ? `Upload ${count}` : "Upload"}
          </Text>
        </Pressable>
      </View>
    </View>
  );
}

/** One kind: what the sale already holds, then what is waiting to go up. */
function Slot({
  label, held, pending, onAdd, onDrop,
}: {
  label: string;
  held: string[];
  pending: string[];
  onAdd: () => void;
  onDrop: (uri: string) => void;
}) {
  const styles = useStyles();
  const { colors } = useTheme();
  const full = held.length + pending.length >= MAX_PER_KIND;

  return (
    <View style={styles.card}>
      <View style={styles.cardHead}>
        <Text style={styles.head}>{label}</Text>
        <Text style={styles.count}>{held.length} filed</Text>
      </View>
      <View style={styles.tiles}>
        {held.map((uri) => (
          <View key={uri} style={styles.tile}>
            <Image source={{ uri }} style={styles.thumb} />
            <View style={styles.lock}>
              <AppIcon name="lock-outline" size={11} color="#fff" />
            </View>
          </View>
        ))}
        {pending.map((uri) => (
          <View key={uri} style={styles.tile}>
            <Image source={{ uri }} style={styles.thumb} />
            <Pressable style={styles.drop} onPress={() => onDrop(uri)}
                       accessibilityRole="button"
                       accessibilityLabel={`Remove ${label}`}>
              <AppIcon name="close" size={12} color="#fff" />
            </Pressable>
          </View>
        ))}
        {full ? (
          <View style={[styles.addTile, styles.fullTile]}>
            <Text style={styles.fullText}>Full</Text>
          </View>
        ) : (
          <Pressable style={styles.addTile} onPress={onAdd}
                     accessibilityRole="button" accessibilityLabel={`Add ${label}`}>
            <AppIcon name="camera-plus-outline" size={20} color={colors.tint} />
          </Pressable>
        )}
      </View>
    </View>
  );
}

const useStyles = makeStyles((colors) => ({
  screen: { flex: 1, backgroundColor: colors.bg },
  body: { padding: spacing.md, paddingBottom: spacing.xl, gap: spacing.md },
  intro: { ...type.title, color: colors.text },
  hint: { ...type.caption, color: colors.textMuted },
  error: { ...type.caption, color: colors.danger },

  card: {
    backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1,
    borderColor: colors.border, padding: spacing.md, gap: spacing.sm,
  },
  cardHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  head: { ...type.label, color: colors.tint, letterSpacing: 0.4, fontWeight: "800" },
  count: { ...type.caption, color: colors.textMuted },

  tiles: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  tile: {
    width: 64, height: 64, borderRadius: radius.md, overflow: "hidden",
    backgroundColor: colors.surfaceAlt,
  },
  thumb: { width: "100%", height: "100%" },
  lock: {
    position: "absolute", right: 2, bottom: 2, width: 18, height: 18,
    borderRadius: 9, alignItems: "center", justifyContent: "center",
    backgroundColor: "rgba(0,0,0,0.45)",
  },
  drop: {
    position: "absolute", right: 2, top: 2, width: 18, height: 18,
    borderRadius: 9, alignItems: "center", justifyContent: "center",
    backgroundColor: colors.danger,
  },
  addTile: {
    width: 64, height: 64, borderRadius: radius.md, borderWidth: 1,
    borderStyle: "dashed", borderColor: colors.border,
    alignItems: "center", justifyContent: "center",
  },
  fullTile: { borderStyle: "solid", backgroundColor: colors.surfaceAlt },
  fullText: { ...type.caption, color: colors.textMuted },

  footer: {
    flexDirection: "row", gap: spacing.sm, padding: spacing.md,
    borderTopWidth: 1, borderTopColor: colors.border,
    backgroundColor: colors.surface,
  },
  cancel: {
    flex: 1, height: 48, borderRadius: radius.md, borderWidth: 1,
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: spacing.xs,
  },
  cancelText: { ...type.title },
  save: {
    flex: 1.2, height: 48, borderRadius: radius.md, flexDirection: "row",
    alignItems: "center", justifyContent: "center", gap: spacing.xs,
  },
  saveText: { ...type.title, color: colors.onDark },
}));
