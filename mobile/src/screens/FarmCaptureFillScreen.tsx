import { NativeStackScreenProps } from "@react-navigation/native-stack";
import React, { useLayoutEffect, useMemo, useState } from "react";
import { Image, Pressable, ScrollView, Text, View } from "react-native";

import { http } from "@/api/client";
import { Row } from "@/api/types";
import {
  capturePhoto, CapturePermissionError, captureLocation,
  isLocalCapture, pickDocument, pickPhoto,
} from "@/capture";
import { AppIcon } from "@/components/AppIcon";
import { FormControl } from "@/components/form";
import { FormField } from "@/config/forms";
import { reverseGeocode } from "@/domain/reverseGeocode";
import { ModuleStackParams } from "@/navigation/types";
import { queryClient } from "@/query/queryClient";
import { makeStyles, radius, shadow, spacing, type, useTheme } from "@/theme";
import { writeThrough } from "@/net/writeThrough";
import { notify } from "@/ui/confirm";

type Props = NativeStackScreenProps<ModuleStackParams, "FarmCaptureFill">;

/**
 * Fill in what a capture is still missing — the register's "+".
 *
 * A visit is recorded in pieces: the pin and the photographs standing on the
 * farm, the cheque scan when it turns up a week later. Opening the whole
 * capture to add one file invites overwriting what is already there, so this
 * offers only the blanks and shows the rest locked.
 *
 * The locking is a courtesy, not the guard. The server writes blanks only —
 * see broiler.views.farm_location_capture_complete — so nothing here decides
 * what may be replaced.
 */

const LAT: FormField = { name: "latitude", label: "Latitude", type: "text", readOnly: true };
const LNG: FormField = { name: "longitude", label: "Longitude", type: "text", readOnly: true };
const STATE: FormField = { name: "state", label: "State", type: "text" };
const DISTRICT: FormField = { name: "district", label: "District", type: "text" };
const AREA: FormField = { name: "area", label: "Area", type: "text" };
const ADDRESS: FormField = { name: "address", label: "Farm Address", type: "textarea" };

const MASTER_SLOTS: { key: string; label: string; cameraOnly?: boolean }[] = [
  { key: "farmer_photo", label: "Farmer Photo", cameraOnly: true },
  { key: "pan", label: "PAN Card" },
  { key: "aadhar_front", label: "Aadhar (Front)" },
  { key: "aadhar_back", label: "Aadhar (Back)" },
  { key: "agreement", label: "Agreement Copy" },
  { key: "cheque_1", label: "Security Cheque 1" },
  { key: "cheque_2", label: "Security Cheque 2" },
  { key: "cheque_3", label: "Security Cheque 3" },
  { key: "cheque_4", label: "Security Cheque 4" },
];

interface CaptureFile { kind: string; name?: string; url?: string }

const str = (v: unknown) => (v == null ? "" : String(v));

export function FarmCaptureFillScreen({ navigation, route }: Props) {
  const styles = useStyles();
  const { colors } = useTheme();
  const row = route.params.row;

  const held = useMemo(() => {
    const files = (row.files as CaptureFile[] | undefined) ?? [];
    const map: Record<string, CaptureFile> = {};
    files.forEach((f) => { if (!map[f.kind]) map[f.kind] = f; });
    return map;
  }, [row.files]);

  const pinned = row.latitude != null && row.longitude != null;

  const [values, setValues] = useState({
    latitude: str(row.latitude), longitude: str(row.longitude),
    state: str(row.state), district: str(row.district),
    area: str(row.area), address: str(row.address),
  });
  const [slots, setSlots] = useState<Record<string, string>>({});
  const [photos, setPhotos] = useState<string[]>([]);
  const [docs, setDocs] = useState<string[]>([]);
  const [gpsNote, setGpsNote] = useState("");
  const [locating, setLocating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useLayoutEffect(() => {
    navigation.setOptions({ title: `Fill · ${str(row.capture_no)}` });
  }, [navigation, row.capture_no]);

  const set = (key: string) => (v: string) =>
    setValues((cur) => ({ ...cur, [key]: v }));

  const useMyLocation = async () => {
    setLocating(true);
    setGpsNote("Reading location…");
    try {
      const point = await captureLocation();
      if (!point) {
        setGpsNote("Could not read the location — try again with a clearer view of the sky.");
        return;
      }
      const { latitude, longitude } = point;
      setValues((cur) => ({ ...cur, latitude, longitude }));
      setGpsNote("Pin captured — looking up the address…");
      const place = await reverseGeocode(latitude, longitude);
      if (!place) {
        setGpsNote("Pin captured. No address found for it — type one if needed.");
        return;
      }
      // Only what is still blank here. A value already on the capture is
      // locked and must not be quietly replaced by the lookup.
      setValues((cur) => ({
        ...cur,
        state: cur.state || place.state || "",
        district: cur.district || place.district || "",
        area: cur.area || place.area || "",
        address: cur.address || place.display,
      }));
      setGpsNote(`Pin resolves to: ${place.display}`);
    } catch (e) {
      setGpsNote(e instanceof CapturePermissionError
        ? "Location permission denied — allow location for BIMS, then press again."
        : "Could not read the location — press again.");
    } finally {
      setLocating(false);
    }
  };

  const takeSlot = async (key: string, cameraOnly?: boolean) => {
    try {
      const shot = cameraOnly ? await capturePhoto() : await pickDocument();
      if (shot) setSlots((cur) => ({ ...cur, [key]: shot.uri }));
    } catch {
      notify("Could not attach", "Try again, or use a different file.");
    }
  };

  const save = async () => {
    setError("");
    // Described rather than built: a FormData cannot be written to the offline
    // queue, and a capture is filled at the farm gate, which is where there is
    // no signal.
    const fields: Record<string, unknown> = {};
    const files: { field: string; uri: string }[] = [];
    if (!pinned && values.latitude && values.longitude) {
      fields.latitude = values.latitude;
      fields.longitude = values.longitude;
    }
    (["state", "district", "area", "address"] as const).forEach((f) => {
      // Only fields that were blank on the record are sent. The server ignores
      // the rest anyway; not sending them keeps the request honest.
      if (!str(row[f]) && values[f].trim()) fields[f] = values[f].trim();
    });
    Object.entries(slots).forEach(([key, uri]) => {
      if (uri) files.push({ field: `slot_${key}`, uri });
    });
    photos.forEach((uri) => files.push({ field: "photos", uri }));
    docs.forEach((uri) => files.push({ field: "documents", uri }));

    setSaving(true);
    try {
      const written = await writeThrough({
        type: "farm_visit", label: "Farm Location & Address",
        method: "POST",
        path: `/broiler/location-captures/${row.id}/fill`,
        body: { fields, files },
        scope: { farm_id: (row as { farm?: number }).farm ?? null },
        gps: values.latitude && values.longitude
          ? { latitude: Number(values.latitude),
              longitude: Number(values.longitude), accuracy: null }
          : null,
      });
      if (written.queued) {
        await notify("Saved on this phone",
          "No signal — this capture is stored on the device and will go to the "
          + "ERP by itself once you are back in range.");
      }
      queryClient.invalidateQueries({ queryKey: ["resource", "/broiler/location-captures/"] });
      navigation.goBack();
    } catch (e: unknown) {
      const err = e as { message?: string; fields?: Record<string, string[]> };
      const detail = Object.values(err.fields ?? {}).flat().join(" ");
      setError(detail || err.message || "Could not save what you filled in.");
    } finally {
      setSaving(false);
    }
  };

  const Locked = ({ label, value }: { label: string; value: string }) => (
    <View style={styles.locked}>
      <Text style={styles.lockedLabel}>{label}</Text>
      <View style={styles.lockedBox}>
        <Text style={styles.lockedValue} numberOfLines={1}>{value || "—"}</Text>
        <AppIcon name="lock-outline" size={14} color={colors.textFaint} />
      </View>
    </View>
  );

  const pendingSlots = MASTER_SLOTS.filter((s) => !held[s.key]);

  return (
    <View style={styles.screen}>
      <ScrollView contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
        <Text style={styles.intro}>
          {str(row.farm_label)} · {str(row.date)}
        </Text>
        <Text style={styles.hint}>
          Locked items were captured already — only what is still blank can be
          filled.
        </Text>
        {error ? <Text style={styles.error}>{error}</Text> : null}

        <View style={styles.card}>
          <Text style={styles.head}>Farm Location &amp; Address</Text>
          {pinned ? (
            <View style={styles.row}>
              <View style={styles.cell}>
                <Locked label="Latitude" value={Number(row.latitude).toFixed(6)} />
              </View>
              <View style={styles.cell}>
                <Locked label="Longitude" value={Number(row.longitude).toFixed(6)} />
              </View>
            </View>
          ) : (
            <>
              <Pressable
                style={({ pressed }) => [styles.gpsButton,
                                         pressed && styles.gpsButtonPressed,
                                         locating && { opacity: 0.6 }]}
                onPress={useMyLocation}
                disabled={locating}
                accessibilityRole="button"
              >
                <AppIcon name="crosshairs-gps" size={18} color={colors.onDark} />
                <Text style={styles.gpsText}>
                  {locating ? "Reading location…" : "Use My Current Location"}
                </Text>
              </Pressable>
              {gpsNote ? <Text style={styles.note}>{gpsNote}</Text> : null}
              <View style={styles.row}>
                <View style={styles.cell}>
                  <FormControl field={LAT} value={values.latitude} onChange={() => {}} />
                </View>
                <View style={styles.cell}>
                  <FormControl field={LNG} value={values.longitude} onChange={() => {}} />
                </View>
              </View>
            </>
          )}

          <View style={styles.row}>
            <View style={styles.cell}>
              {str(row.state)
                ? <Locked label="State" value={str(row.state)} />
                : <FormControl field={STATE} value={values.state} onChange={set("state")} />}
            </View>
            <View style={styles.cell}>
              {str(row.district)
                ? <Locked label="District" value={str(row.district)} />
                : <FormControl field={DISTRICT} value={values.district} onChange={set("district")} />}
            </View>
          </View>
          {str(row.area)
            ? <Locked label="Area" value={str(row.area)} />
            : <FormControl field={AREA} value={values.area} onChange={set("area")} />}
          {str(row.address)
            ? <Locked label="Farm Address" value={str(row.address)} />
            : <FormControl field={ADDRESS} value={values.address} onChange={set("address")} />}
        </View>

        <View style={styles.card}>
          <Text style={styles.head}>Master Documents</Text>
          {pendingSlots.length ? (
            pendingSlots.map((slot) => (
              <Pressable key={slot.key} style={styles.slot}
                         onPress={() => takeSlot(slot.key, slot.cameraOnly)}>
                <AppIcon
                  name={slots[slot.key] ? "check-circle-outline" : "paperclip"}
                  size={18}
                  color={slots[slot.key] ? colors.success : colors.textMuted}
                />
                <Text style={styles.slotLabel}>{slot.label}</Text>
                <Text style={styles.slotState}>
                  {slots[slot.key] ? "Attached" : "Attach"}
                </Text>
              </Pressable>
            ))
          ) : (
            <Text style={styles.note}>Every master document is already held.</Text>
          )}
          {MASTER_SLOTS.filter((s) => held[s.key]).length ? (
            <Text style={styles.note}>
              Already held:{" "}
              {MASTER_SLOTS.filter((s) => held[s.key]).map((s) => s.label).join(", ")}
            </Text>
          ) : null}
        </View>

        <View style={styles.card}>
          {/* Never "full": more pictures of a farm are always worth having,
              which is why these two are offered whatever is already there. */}
          <Text style={styles.head}>Add More</Text>
          <Strip label="Farm Pictures" uris={photos}
                 onAdd={async () => {
                   const shot = await capturePhoto();
                   if (shot) setPhotos((c) => [...c, shot.uri]);
                 }}
                 onPick={async () => {
                   const shot = await pickPhoto();
                   if (shot) setPhotos((c) => [...c, shot.uri]);
                 }}
                 onRemove={(u) => setPhotos((c) => c.filter((x) => x !== u))} />
          <Strip label="Other Documents" uris={docs}
                 onPick={async () => {
                   const doc = await pickDocument();
                   if (doc) setDocs((c) => [...c, doc.uri]);
                 }}
                 onRemove={(u) => setDocs((c) => c.filter((x) => x !== u))} />
        </View>
      </ScrollView>

      <View style={styles.footer}>
        <Pressable style={[styles.cancel, { borderColor: colors.danger }]}
                   onPress={() => navigation.goBack()} disabled={saving}>
          <AppIcon name="close" size={18} color={colors.danger} />
          <Text style={[styles.cancelText, { color: colors.danger }]}>Cancel</Text>
        </Pressable>
        <Pressable style={[styles.save, { backgroundColor: colors.tint },
                           saving && { opacity: 0.55 }]}
                   onPress={save} disabled={saving}>
          <AppIcon name="content-save-outline" size={18} color={colors.onDark} />
          <Text style={styles.saveText}>{saving ? "Saving…" : "Save"}</Text>
        </Pressable>
      </View>
    </View>
  );
}

function Strip({
  label, uris, onAdd, onPick, onRemove,
}: {
  label: string;
  uris: string[];
  onAdd?: () => void;
  onPick?: () => void;
  onRemove: (uri: string) => void;
}) {
  const styles = useStyles();
  const { colors } = useTheme();
  return (
    <View style={styles.strip}>
      <Text style={styles.fieldLabel}>{label} <Text style={styles.count}>{uris.length}</Text></Text>
      <View style={styles.tiles}>
        {uris.map((uri) => (
          <Pressable key={uri} style={styles.tile} onLongPress={() => onRemove(uri)}>
            {isLocalCapture(uri) || /\.(jpe?g|png|webp)$/i.test(uri) ? (
              <Image source={{ uri }} style={styles.thumb} />
            ) : (
              <AppIcon name="file-document-outline" size={22} color={colors.textMuted} />
            )}
          </Pressable>
        ))}
        {onAdd ? (
          <Pressable style={styles.addTile} onPress={onAdd}>
            <AppIcon name="camera-plus-outline" size={20} color={colors.tint} />
          </Pressable>
        ) : null}
        {onPick ? (
          <Pressable style={styles.addTile} onPress={onPick}>
            <AppIcon name="paperclip" size={20} color={colors.tint} />
          </Pressable>
        ) : null}
      </View>
      {uris.length ? <Text style={styles.note}>Long-press a tile to remove it.</Text> : null}
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
    borderColor: colors.border, padding: spacing.md, gap: spacing.xs,
  },
  head: { ...type.label, color: colors.tint, letterSpacing: 0.4,
          fontWeight: "800", marginBottom: spacing.xs },
  row: { flexDirection: "row", gap: spacing.md },
  cell: { flex: 1, minWidth: 0 },

  gpsButton: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: spacing.sm, backgroundColor: colors.success,
    borderRadius: radius.md, paddingVertical: spacing.md, ...shadow(2),
  },
  gpsButtonPressed: { opacity: 0.85, transform: [{ scale: 0.985 }] },
  gpsText: { ...type.title, color: colors.onDark },
  note: { ...type.caption, color: colors.textMuted, marginTop: spacing.xs },

  locked: { marginBottom: spacing.sm },
  lockedLabel: { ...type.label, color: colors.textMuted, marginBottom: 2 },
  lockedBox: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    backgroundColor: colors.surfaceAlt, paddingHorizontal: spacing.md,
    minHeight: 44,
  },
  lockedValue: { ...type.body, color: colors.textMuted, flex: 1 },

  slot: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    paddingVertical: spacing.sm, borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  slotLabel: { ...type.body, color: colors.text, flex: 1 },
  slotState: { ...type.caption, color: colors.tint, fontWeight: "700" },

  strip: { marginBottom: spacing.sm },
  fieldLabel: { ...type.label, color: colors.text, marginBottom: spacing.xs },
  count: { ...type.caption, color: colors.textMuted },
  tiles: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  tile: {
    width: 64, height: 64, borderRadius: radius.md, overflow: "hidden",
    alignItems: "center", justifyContent: "center",
    backgroundColor: colors.surfaceAlt,
  },
  thumb: { width: "100%", height: "100%" },
  addTile: {
    width: 64, height: 64, borderRadius: radius.md, borderWidth: 1,
    borderStyle: "dashed", borderColor: colors.border,
    alignItems: "center", justifyContent: "center",
  },

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
