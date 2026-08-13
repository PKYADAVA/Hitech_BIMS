import { NativeStackScreenProps } from "@react-navigation/native-stack";
import React, { useLayoutEffect, useState } from "react";
import { Alert, Image, Pressable, ScrollView, Text, View } from "react-native";

import { http } from "@/api/client";
import { Envelope } from "@/api/types";
import {
  capturePhoto, CapturePermissionError, captureLocation, pickDocument, pickPhoto,
} from "@/capture";
import { AppIcon } from "@/components/AppIcon";
import { FormControl } from "@/components/form";
import { FormField } from "@/config/forms";
import { reverseGeocode } from "@/domain/reverseGeocode";
import { ModuleStackParams } from "@/navigation/types";
import { writeThrough } from "@/net/writeThrough";
import { notify } from "@/ui/confirm";
import { queryClient } from "@/query/queryClient";
import { makeStyles, radius, shadow, spacing, type, useTheme } from "@/theme";

type Props = NativeStackScreenProps<ModuleStackParams, "FarmCaptureForm">;

/**
 * Farm Location Capture — a dated visit recording where a farm is and what it
 * looks like (Broiler > Transactions > Farm Location & Photos).
 *
 * This is the form the phone should have had first: the whole record is
 * *taken on site*. The pin comes from the device's GPS, the pictures from its
 * camera, and the KYC scans from whatever the farmer has to hand. Doing it on
 * a desktop means typing coordinates read off someone else's phone.
 *
 * Saving posts multipart to broiler/location-captures/save, which runs the web
 * form's own `_save_capture` — so the files land in the same slots and mirror
 * onto the farm and farmer masters exactly as they do from the ERP.
 */

interface Option { value: string; label: string }

const DATE: FormField = { name: "date", label: "Date", type: "date", required: true };
const CAPTURE_NO: FormField = {
  name: "capture_no", label: "Capture No.", type: "text", readOnly: true,
  placeholder: "Assigned on save",
};
const FARMER: FormField = {
  name: "farmer", label: "Farmer", type: "text", readOnly: true,
  placeholder: "Auto-filled",
};
const LAT: FormField = {
  name: "latitude", label: "Latitude", type: "text", readOnly: true,
  placeholder: "Auto-detected",
};
const LNG: FormField = {
  name: "longitude", label: "Longitude", type: "text", readOnly: true,
  placeholder: "Auto-detected",
};
const STATE: FormField = { name: "state", label: "State", type: "text" };
const DISTRICT: FormField = { name: "district", label: "District", type: "text" };
const AREA: FormField = { name: "area", label: "Area", type: "text" };
const ADDRESS: FormField = { name: "address", label: "Farm Address", type: "textarea" };
const REMARKS: FormField = { name: "remarks", label: "Remarks", type: "textarea" };

/**
 * Branch and Farm are locked once a capture exists.
 *
 * Saving a capture pushes its pin and address onto the farm master
 * (`FarmLocationCapture.sync_farm`). Re-pointing a saved capture at a
 * different farm would therefore stamp this visit's location onto a farm
 * nobody visited, and leave the farm that *was* visited holding a reading with
 * nothing behind it — from a picker that looks like an ordinary correction.
 *
 * A capture belongs to the farm it was taken at. Recording it against another
 * one is a new visit, not an edit.
 */
const branchField = (options: Option[], locked: boolean): FormField =>
  locked
    ? { name: "branch", label: "Branch", type: "text", readOnly: true,
        placeholder: "Fixed by the farm" }
    : { name: "branch", label: "Branch", type: "select", options,
        placeholder: "All branches" };

const farmField = (options: Option[], locked: boolean, ready: boolean): FormField =>
  locked
    ? { name: "farm", label: "Farm", type: "text", readOnly: true }
    : { name: "farm", label: "Farm", type: "select", required: true, options,
        // Farm is reached *through* the branch, so an empty picker says why it
        // is empty rather than looking like a branch with no farms on it.
        placeholder: ready ? undefined : "Select a branch first" };

const REMARKS_MAX = 200;

/**
 * The single-file master slots, in the order the ERP lists them
 * (FarmCaptureFile.SLOT_TARGETS). Each one overwrites a field on the farm or
 * farmer master, so exactly one file goes in each.
 *
 * `cameraOnly` marks the one slot that may not be attached from the gallery.
 * See SourcePair for why that is the farmer's photo and nothing else.
 */
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

interface Farm { id: number; farm_name: string; farm_code: string }
interface Branch { id: number; branch_name: string }

const today = () => new Date().toISOString().slice(0, 10);

export function FarmCaptureFormScreen({ navigation, route }: Props) {
  /** The saved capture being corrected, or null when recording a new visit. */
  const editing = route.params?.row ?? null;
  const styles = useStyles();
  const { colors } = useTheme();

  const [values, setValues] = useState<Record<string, string>>({
    date: today(), branch: "", farm: "", farm_label: "", farmer: "",
    latitude: "", longitude: "", state: "", district: "", area: "",
    address: "", remarks: "",
  });
  const [branchOptions, setBranchOptions] = useState<Option[]>([]);
  const [farmOptions, setFarmOptions] = useState<Option[]>([]);
  /** Farm pictures — any number, so they are a list. */
  const [pictures, setPictures] = useState<string[]>([]);
  /** Other documents — also any number. */
  const [documents, setDocuments] = useState<string[]>([]);
  /** One file per master slot, keyed by slot code. */
  const [slots, setSlots] = useState<Record<string, string>>({});
  const [slotsOpen, setSlotsOpen] = useState(true);
  const [gpsNote, setGpsNote] = useState("");
  const [locating, setLocating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useLayoutEffect(() => {
    navigation.setOptions({
      title: editing ? "Edit Farm Location Capture" : "Farm Location Capture",
    });
  }, [navigation, editing]);

  React.useEffect(() => {
    loadBranches();
    if (!editing) return;
    // Prefill from the row the register already holds — no second fetch for
    // data that came down with the list.
    const str = (v: unknown) => (v == null ? "" : String(v));
    setValues((cur) => ({
      ...cur,
      date: str(editing.date) || cur.date,
      farm: str(editing.farm),
      farm_label: str(editing.farm_label),
      farmer: str(editing.farmer_label),
      latitude: str(editing.latitude),
      longitude: str(editing.longitude),
      state: str(editing.state),
      district: str(editing.district),
      area: str(editing.area),
      address: str(editing.address),
      remarks: str(editing.remarks),
    }));
  }, []);

  const loadBranches = async () => {
    try {
      const { data } = await http.get<Envelope<Branch[]>>(
        "/broiler/branches/", { params: { page_size: 200 } });
      setBranchOptions(data.data.map((b) => ({ value: String(b.id), label: b.branch_name })));
    } catch {
      /* the picker simply stays empty; Branch only narrows the farm list */
    }
  };

  /**
   * The farms mapped to one branch — the Farm picker's whole list.
   *
   * Never every farm in the company: the record is a visit to a farm the
   * branch actually runs, and a list of all of them is how a capture ends up
   * filed under someone else's.
   *
   * On Add, a farm already captured drops off the list too — same rule the
   * web Add-Capture form applies — so this calls the filtered endpoint. On
   * Edit the picker is locked to the farm the capture already holds (which
   * IS already captured, being the very record open), so it keeps the plain,
   * unfiltered farm list instead — otherwise that farm would filter itself
   * out of its own field.
   */
  const loadFarms = async (branchId: string) => {
    if (!branchId) return setFarmOptions([]);
    try {
      const { data } = editing
        ? await http.get<Envelope<Farm[]>>("/broiler/farms/", {
            params: { branch: branchId, page_size: 500 },
          })
        : await http.get<Envelope<Farm[]>>("/broiler/farms-for-capture", {
            params: { branch: branchId },
          });
      setFarmOptions(data.data.map((f) => ({
        value: String(f.id), label: f.farm_name || f.farm_code || `#${f.id}`,
      })));
    } catch {
      setFarmOptions([]);
    }
  };

  const onChange = (name: string) => async (value: string) => {
    const next = { ...values, [name]: value };
    if (name === "branch") {
      // A farm from the previous branch must not survive the change.
      next.farm = "";
      next.farmer = "";
    }
    setValues(next);
    if (name === "branch") await loadFarms(value);
    if (name === "farm" && value) {
      // The farmer is read through from the farm rather than chosen: a capture
      // stores no farmer of its own, precisely so a farm changing hands cannot
      // leave one pointing at the wrong person.
      try {
        const { data } = await http.get<Envelope<{ farmer_name: string }>>(
          "/broiler/farm-lookup", { params: { farm: value } });
        setValues((cur) => ({ ...cur, farmer: data.data.farmer_name || "" }));
      } catch {
        setValues((cur) => ({ ...cur, farmer: "" }));
      }
    }
  };

  /**
   * The pin, then the address it resolves to.
   *
   * Typed text is never overwritten — a hand-written address always wins, and
   * the looked-up one is offered instead. State, District and Area are derived
   * labels rather than things anyone types, so a new pin refreshes them.
   */
  const useMyLocation = async () => {
    setLocating(true);
    setGpsNote("Reading location…");
    try {
      const point = await captureLocation();
      if (!point) {
        setGpsNote("Could not read the location — try again with a clearer view of the sky.");
        return;
      }
      // captureLocation already hands back the strings the form's state holds,
      // and reports no accuracy figure, so there is none to quote back.
      const { latitude, longitude } = point;
      setValues((cur) => ({ ...cur, latitude, longitude }));
      setGpsNote("Pin captured — looking up the address…");
      const place = await reverseGeocode(latitude, longitude);
      if (!place) {
        setGpsNote("Pin captured. No address found for it — type one if needed.");
        return;
      }
      setValues((cur) => ({
        ...cur,
        state: place.state || cur.state,
        district: place.district || cur.district,
        area: place.area || cur.area,
        address: cur.address.trim() ? cur.address : place.display,
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

  const addFile = (
    take: () => Promise<{ uri: string } | null>,
    onGot: (uri: string) => void,
  ) => async () => {
    try {
      const shot = await take();
      if (shot) onGot(shot.uri);
    } catch (e) {
      Alert.alert(
        e instanceof CapturePermissionError ? "Permission needed" : "Could not attach that",
        (e as Error)?.message ?? "Please try again.",
      );
    }
  };

  const submit = async () => {
    setError(null);
    if (!values.branch && !editing) return setError("Select a branch.");
    if (!values.farm) return setError("Select a farm.");
    if (!values.date) return setError("Date is required.");
    // The model refuses half a pair: it looks like a location but cannot be
    // plotted, and would overwrite a good one on the farm master.
    if (!!values.latitude !== !!values.longitude) {
      return setError("Capture both coordinates, or neither.");
    }

    setSaving(true);
    try {
      // Described rather than built: a FormData cannot be written to the
      // offline queue, and a capture is made at the farm gate.
      const fields: Record<string, unknown> = {};
      for (const key of ["date", "farm", "latitude", "longitude",
                         "state", "district", "area", "address", "remarks"]) {
        if (values[key]) fields[key] = values[key];
      }
      const files: { field: string; uri: string }[] = [
        ...pictures.map((uri) => ({ field: "photos", uri })),
        ...documents.map((uri) => ({ field: "documents", uri })),
        ...Object.entries(slots)
          .filter(([, uri]) => !!uri)
          .map(([slot, uri]) => ({ field: `slot_${slot}`, uri: uri as string })),
      ];
      // Files are only ever *added* by a save: the ERP's _save_capture attaches
      // whatever came with the request and leaves the existing ones alone, so
      // re-sending nothing does not clear what is already on the record.
      const url = editing
        ? `/broiler/location-captures/save/${editing.id}`
        : "/broiler/location-captures/save";
      const written = await writeThrough({
        type: "farm_visit", label: "Farm Location & Address",
        method: "POST", path: url, date: values.date,
        body: { fields, files },
        scope: { farm_id: values.farm || null },
        gps: values.latitude && values.longitude
          ? { latitude: Number(values.latitude),
              longitude: Number(values.longitude), accuracy: null }
          : null,
      });
      queryClient.invalidateQueries({ queryKey: ["list", "/broiler/location-captures/"] });
      if (written.queued) {
        await notify("Saved on this phone",
          "No signal — this capture is stored on the device and will go to the "
          + "ERP by itself once you are back in range.");
      }
      navigation.goBack();
    } catch (e: unknown) {
      const message = (e as { message?: string })?.message ?? "Could not save the capture.";
      setError(message);
      Alert.alert("Could not save", message);
    } finally {
      setSaving(false);
    }
  };

  /**
   * One attach button that asks where the file comes from.
   *
   * Three sources now that documents are real files and not just photographs
   * of them — camera, gallery, storage — which is one too many to sit as
   * buttons on a slot row, and the question is quick to answer anyway.
   *
   * `cameraOnly` is the Farmer Photo and nothing else, and it skips the
   * question entirely. Every other slot is a shed or a piece of paper, and
   * either may reasonably already be on the phone: a cheque photographed in
   * the office, an Aadhar PDF sent over WhatsApp. The farmer's own photo is
   * the one thing the visit exists to *prove*, so it has to be taken there and
   * then — letting it come from the gallery is exactly how a farm gets
   * verified by someone who never went.
   */
  const attach = (add: (uri: string) => void, cameraOnly?: boolean) => () => {
    const take = async (source: () => Promise<{ uri: string } | null>) => {
      try {
        const picked = await source();
        if (picked) add(picked.uri);
      } catch (e) {
        Alert.alert(
          e instanceof CapturePermissionError ? "Permission needed" : "Could not attach that",
          (e as Error)?.message ?? "Please try again.",
        );
      }
    };
    if (cameraOnly) return take(capturePhoto);
    Alert.alert("Attach", "Where is this coming from?", [
      { text: "Take a photo", onPress: () => take(capturePhoto) },
      { text: "Photo gallery", onPress: () => take(pickPhoto) },
      { text: "File (PDF, doc)", onPress: () => take(pickDocument) },
      { text: "Cancel", style: "cancel" },
    ]);
  };

  const SectionHead = ({ n, title, tone }: { n: number; title: string; tone: string }) => (
    <View style={styles.sectionHead}>
      <View style={[styles.badge, { backgroundColor: tone }]}>
        <Text style={styles.badgeText}>{n}</Text>
      </View>
      <Text style={[styles.sectionTitle, { color: tone }]}>{title}</Text>
    </View>
  );

  const Thumbs = ({ uris, onRemove }: { uris: string[]; onRemove: (i: number) => void }) => (
    <View style={styles.thumbs}>
      {uris.map((uri, i) => (
        <Pressable key={`${uri}-${i}`} onPress={() => onRemove(i)} style={styles.thumbWrap}>
          <Image source={{ uri }} style={styles.thumb} />
          <View style={styles.thumbX}><Text style={styles.thumbXText}>×</Text></View>
        </Pressable>
      ))}
    </View>
  );

  return (
    <View style={styles.screen}>
      <ScrollView contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
        {error ? <Text style={styles.error}>{error}</Text> : null}

        <View style={styles.card}>
          <SectionHead n={1} title="CAPTURE DETAILS" tone={colors.tint} />
          <View style={styles.row}>
            <View style={styles.cell}>
              <FormControl field={CAPTURE_NO} value="" values={values} onChange={() => {}} />
            </View>
            <View style={styles.cell}>
              <FormControl field={DATE} value={values.date} values={values}
                           onChange={onChange("date")} />
            </View>
          </View>
          <FormControl field={branchField(branchOptions, !!editing)} value={values.branch}
                       values={values} onChange={onChange("branch")} />
          <View style={styles.row}>
            <View style={styles.cell}>
              <FormControl field={farmField(farmOptions, !!editing, !!values.branch)}
                           value={editing ? values.farm_label : values.farm}
                           values={values} onChange={onChange("farm")} />
            </View>
            <View style={styles.cell}>
              <FormControl field={FARMER} value={values.farmer} values={values}
                           onChange={() => {}} />
            </View>
          </View>
        </View>

        <View style={styles.card}>
          <SectionHead n={2} title="FARM LOCATION & ADDRESS" tone={colors.success} />
          {/* The one action of this section, so it is drawn as one: filled,
              raised and it moves under the thumb. As a pale tint with green
              text it read as a banner, and a banner is not something anyone
              thinks to press. */}
          <Pressable
            style={({ pressed }) => [
              styles.gpsButton,
              pressed && styles.gpsButtonPressed,
              locating && { opacity: 0.6 },
            ]}
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
              <FormControl field={LAT} value={values.latitude} values={values} onChange={() => {}} />
            </View>
            <View style={styles.cell}>
              <FormControl field={LNG} value={values.longitude} values={values} onChange={() => {}} />
            </View>
          </View>
          <View style={styles.row}>
            <View style={styles.cell}>
              <FormControl field={STATE} value={values.state} values={values}
                           onChange={onChange("state")} />
            </View>
            <View style={styles.cell}>
              <FormControl field={DISTRICT} value={values.district} values={values}
                           onChange={onChange("district")} />
            </View>
          </View>
          <FormControl field={AREA} value={values.area} values={values} onChange={onChange("area")} />
          <FormControl field={ADDRESS} value={values.address} values={values}
                       onChange={onChange("address")} />
        </View>

        <View style={styles.card}>
          <SectionHead n={3} title="PHOTOS & DOCUMENTS" tone={colors.warning} />

          <Text style={styles.fieldLabel}>Farm Pictures</Text>
          <Pressable style={styles.dropZone}
                     onPress={attach((u) => setPictures((c) => [...c, u]))}>
            <AppIcon name="camera-outline" size={18} color={colors.tint} />
            <Text style={[styles.dropText, { color: colors.tint }]}>Tap to Capture / Upload</Text>
          </Pressable>
          <Thumbs uris={pictures} onRemove={(i) => setPictures((c) => c.filter((_, j) => j !== i))} />

          <Text style={styles.fieldLabel}>Other Documents</Text>
          <Pressable style={styles.dropZone}
                     onPress={attach((u) => setDocuments((c) => [...c, u]))}>
            <AppIcon name="file-document" size={18} color={colors.tint} />
            <Text style={[styles.dropText, { color: colors.tint }]}>Tap to Capture / Upload</Text>
          </Pressable>
          <Thumbs uris={documents} onRemove={(i) => setDocuments((c) => c.filter((_, j) => j !== i))} />

          <Pressable style={styles.slotsHead} onPress={() => setSlotsOpen((o) => !o)}>
            <Text style={[styles.slotsTitle, { color: colors.warning }]}>MASTER DOCUMENTS</Text>
            <AppIcon name={slotsOpen ? "chevron-up" : "chevron-down"} size={20}
                     color={colors.warning} />
          </Pressable>
          {slotsOpen ? (
            <View style={styles.slots}>
              {MASTER_SLOTS.map((slot) => {
                const filled = !!slots[slot.key];
                return (
                  <View key={slot.key} style={styles.slotRow}>
                    <AppIcon name={filled ? "check-circle" : "file-document"} size={16}
                             color={filled ? colors.success : colors.textMuted} />
                    <Text style={styles.slotLabel} numberOfLines={1}>{slot.label}</Text>
                    <Pressable
                      style={[styles.slotButton, filled && { borderColor: colors.success }]}
                      onPress={attach((u) => setSlots((c) => ({ ...c, [slot.key]: u })),
                                      slot.cameraOnly)}>
                      <Text style={[styles.slotButtonText,
                                    { color: filled ? colors.success : colors.tint }]}>
                        {filled ? "Attached" : slot.cameraOnly ? "Capture" : "Upload"}
                      </Text>
                    </Pressable>
                  </View>
                );
              })}
            </View>
          ) : null}

          <FormControl field={REMARKS} value={values.remarks} values={values}
                       onChange={(v) => setValues((c) => ({ ...c, remarks: v.slice(0, REMARKS_MAX) }))} />
          <Text style={styles.counter}>{values.remarks.length}/{REMARKS_MAX}</Text>
        </View>
      </ScrollView>

      <View style={styles.footer}>
        <Pressable style={styles.cancel} onPress={() => navigation.goBack()}>
          <Text style={styles.cancelText}>Cancel</Text>
        </Pressable>
        <Pressable style={[styles.save, { backgroundColor: colors.tint }, saving && { opacity: 0.6 }]}
                   onPress={submit} disabled={saving}>
          <Text style={styles.saveText}>{saving ? "Saving…" : "Save"}</Text>
        </Pressable>
      </View>
    </View>
  );
}

const useStyles = makeStyles((colors) => ({
  screen: { flex: 1, backgroundColor: colors.bg },
  body: { padding: spacing.md, paddingBottom: spacing.xl, gap: spacing.md },
  card: {
    backgroundColor: colors.surface, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border, padding: spacing.md,
  },
  sectionHead: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginBottom: spacing.sm },
  badge: {
    width: 24, height: 24, borderRadius: 6,
    alignItems: "center", justifyContent: "center",
  },
  badgeText: { color: colors.onDark, fontWeight: "800", fontSize: 12 },
  sectionTitle: { ...type.label, letterSpacing: 0.6 },
  row: { flexDirection: "row", gap: spacing.sm, alignItems: "flex-start" },
  cell: { flex: 1, minWidth: 0 },

  gpsButton: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.sm,
    backgroundColor: colors.success,
    borderRadius: radius.md, paddingVertical: spacing.md,
    ...shadow(2),
  },
  gpsButtonPressed: { opacity: 0.85, transform: [{ scale: 0.985 }] },
  gpsText: { ...type.title, color: colors.onDark },
  note: { ...type.caption, color: colors.textMuted, marginTop: spacing.xs },

  labelRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  fieldLabel: { ...type.label, color: colors.text, marginTop: spacing.sm },
  dropZone: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    borderWidth: 1, borderStyle: "dashed", borderColor: colors.border,
    borderRadius: radius.md, paddingVertical: spacing.md, marginTop: spacing.xs,
    gap: spacing.sm,
  },
  dropText: { ...type.body, fontWeight: "600" },

  thumbs: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, marginTop: spacing.sm },
  thumbWrap: { width: 64, height: 64 },
  thumb: { width: 64, height: 64, borderRadius: radius.sm, backgroundColor: colors.surfaceAlt },
  thumbX: {
    position: "absolute", top: -6, right: -6, width: 20, height: 20, borderRadius: 10,
    backgroundColor: colors.danger, alignItems: "center", justifyContent: "center",
  },
  thumbXText: { color: colors.onDark, fontWeight: "800", lineHeight: 18 },

  slotsHead: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    marginTop: spacing.md, paddingVertical: spacing.sm,
    borderTopWidth: 1, borderTopColor: colors.border,
  },
  slotsTitle: { ...type.label, letterSpacing: 0.6 },
  slots: { gap: spacing.xs },
  slotRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    paddingVertical: spacing.xs,
  },
  slotLabel: { ...type.body, color: colors.text, flex: 1 },
  slotButton: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm,
    paddingHorizontal: spacing.md, paddingVertical: spacing.xs,
  },
  slotButtonText: { ...type.caption, fontWeight: "700" },

  counter: { ...type.caption, color: colors.textMuted, textAlign: "right" },
  error: { ...type.caption, color: colors.danger },
  footer: {
    flexDirection: "row", gap: spacing.sm, padding: spacing.md,
    borderTopWidth: 1, borderTopColor: colors.border, backgroundColor: colors.surface,
  },
  cancel: {
    flex: 1, height: 48, borderRadius: radius.md, borderWidth: 1,
    borderColor: colors.border, alignItems: "center", justifyContent: "center",
  },
  cancelText: { ...type.title, color: colors.text },
  save: { flex: 2, height: 48, borderRadius: radius.md, alignItems: "center", justifyContent: "center" },
  saveText: { ...type.title, color: colors.onDark },
}));
