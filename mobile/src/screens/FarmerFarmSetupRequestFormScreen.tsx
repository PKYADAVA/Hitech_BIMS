import { NativeStackScreenProps } from "@react-navigation/native-stack";
import React, { useLayoutEffect, useState } from "react";
import { Alert, Image, Pressable, ScrollView, Switch, Text, TextInput, View } from "react-native";

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

type Props = NativeStackScreenProps<ModuleStackParams, "FarmerFarmSetupRequestForm">;

/**
 * Farmer & Farm Setup Request — a field supervisor's on-site submission to
 * create a brand-new Farmer + Farm (Broiler > Transactions).
 *
 * Nothing here is real until an office reviewer approves it on the web; this
 * screen only ever produces a request. Save Draft leaves it editable, Submit
 * for Approval locks it into the review queue, and reopening anything past
 * Draft opens read-only with whatever the reviewer left in the note — there
 * is no Approve/Reject here, by design (office-only).
 *
 * Posts multipart to broiler/farmer-farm-setup-requests/save, which runs the
 * web form's own FarmerFarmSetupRequestAPI.post — so a phone save is held to
 * exactly the same draft/submit rules as a browser save.
 */

interface Option { value: string; label: string }
interface ShedRow { length: string; width: string }

const REQUEST_NO: FormField = {
  name: "request_no", label: "Request No.", type: "text", readOnly: true,
  placeholder: "Assigned on save",
};
const LAT: FormField = {
  name: "latitude", label: "Latitude", type: "text", readOnly: true, placeholder: "Auto-detected",
};
const LNG: FormField = {
  name: "longitude", label: "Longitude", type: "text", readOnly: true, placeholder: "Auto-detected",
};
const CAPTURED_AT: FormField = {
  name: "gps_captured_at", label: "Captured On", type: "text", readOnly: true, placeholder: "—",
};
const STATE: FormField = { name: "state", label: "State", type: "text" };
const DISTRICT: FormField = { name: "district", label: "District", type: "text" };
const LINE: FormField = { name: "line", label: "Line / Route", type: "text" };
const VILLAGE_AREA: FormField = { name: "village_area", label: "Village / Area", type: "text" };
const FULL_ADDRESS: FormField = { name: "full_address", label: "Full Farm Address", type: "textarea" };

const FARMER_NAME: FormField = { name: "farmer_name", label: "Farmer Name", type: "text", required: true };
const FATHER_SPOUSE_NAME: FormField = { name: "father_spouse_name", label: "Father / Spouse Name", type: "text" };
const PRIMARY_MOBILE: FormField = {
  name: "primary_mobile", label: "Primary Mobile", type: "text", required: true,
  placeholder: "+91 10-digit mobile number",
};
const ALTERNATE_MOBILE: FormField = { name: "alternate_mobile", label: "Alternate Mobile", type: "text" };
const EMAIL: FormField = { name: "email", label: "Email", type: "text" };
const FARMER_ADDRESS: FormField = {
  name: "farmer_address", label: "Farmer Address", type: "textarea",
  placeholder: "Where the farmer lives — may differ from the farm's own address",
};

const FARM_NAME: FormField = { name: "farm_name", label: "Farm Name", type: "text", required: true };
const CAPACITY_BIRDS: FormField = { name: "capacity_birds", label: "Capacity (Birds)", type: "number", required: true };
const REMARKS: FormField = { name: "remarks", label: "Remarks", type: "textarea" };

const AADHAAR_NUMBER: FormField = { name: "aadhaar_number", label: "Aadhaar Number", type: "text" };
const PAN_CARD: FormField = { name: "pan_card", label: "PAN Card", type: "text" };

const ACCOUNT_HOLDER_NAME: FormField = { name: "account_holder_name", label: "Account Holder Name", type: "text" };
const ACC_NO: FormField = { name: "acc_no", label: "Account Number", type: "text" };
const IFSC_CODE: FormField = { name: "ifsc_code", label: "IFSC Code", type: "text", placeholder: "e.g. SBIN0001234" };
const BANK_NAME: FormField = { name: "bank_name", label: "Bank Name", type: "text" };
const BANK_BRANCH: FormField = { name: "bank_branch", label: "Bank Branch", type: "text" };

const FARM_TYPE_OPTIONS: Option[] = [
  { value: "own", label: "Own" },
  { value: "ec_shed", label: "Ec Shed" },
  { value: "integration", label: "Integration" },
];
const SHED_TYPE_OPTIONS: Option[] = [
  { value: "open", label: "Open Shed" },
  { value: "closed", label: "Closed Shed" },
  { value: "ec", label: "Environmental Controlled" },
];

/** The 5 KYC scans — one file each, uploaded from camera, gallery or storage
 *  (unlike the Farmer Photo, none of these has to be taken standing there). */
const KYC_SLOTS: { key: string; label: string }[] = [
  { key: "aadhaar_front", label: "Aadhaar (Front)" },
  { key: "aadhaar_back", label: "Aadhaar (Back)" },
  { key: "pan_upload", label: "PAN Card Upload" },
  { key: "agreement_copy", label: "Agreement Copy" },
  { key: "security_cheque", label: "Security Cheque" },
];

interface Branch { id: number; branch_name: string }
interface FarmerGroupRow { id: number; code: string; description: string }
interface SupervisorRow { id: number; name: string }

const FIELD_KEYS = [
  "state", "district", "line", "village_area", "full_address",
  "farmer_name", "father_spouse_name", "primary_mobile", "whatsapp_number",
  "alternate_mobile", "email", "farmer_address", "farm_name", "supervisor", "farm_type", "farmer_group",
  "capacity_birds", "shed_type", "remarks", "aadhaar_number", "pan_card",
  "account_holder_name", "acc_no", "ifsc_code", "bank_name", "bank_branch",
];

const STATUS_LABEL: Record<string, string> = {
  draft: "Draft", pending: "Pending Review", approved: "Approved", rejected: "Rejected",
};

/** Field defs are shared statics; a reopened request past Draft is read-only
 *  end to end, so this stamps `readOnly` on at render time rather than
 *  forking every const into a locked/unlocked pair. */
const ro = (field: FormField, locked: boolean): FormField => (locked ? { ...field, readOnly: true } : field);

export function FarmerFarmSetupRequestFormScreen({ navigation, route }: Props) {
  const editing = route.params?.row ?? null;
  const locked = !!editing && editing.status !== "draft";
  const styles = useStyles();
  const { colors } = useTheme();

  const str = (v: unknown) => (v == null ? "" : String(v));

  const [values, setValues] = useState<Record<string, string>>(() => ({
    branch: str(editing?.branch), latitude: str(editing?.latitude), longitude: str(editing?.longitude),
    gps_captured_at: str(editing?.gps_captured_at), state: str(editing?.state),
    district: str(editing?.district), line: str(editing?.line), village_area: str(editing?.village_area),
    full_address: str(editing?.full_address), farmer_name: str(editing?.farmer_name),
    father_spouse_name: str(editing?.father_spouse_name), primary_mobile: str(editing?.primary_mobile),
    whatsapp_number: str(editing?.whatsapp_number), alternate_mobile: str(editing?.alternate_mobile),
    email: str(editing?.email), farmer_address: str(editing?.farmer_address),
    farm_name: str(editing?.farm_name),
    supervisor: str(editing?.supervisor),
    farm_type: str(editing?.farm_type) || "own", farmer_group: str(editing?.farmer_group),
    capacity_birds: str(editing?.capacity_birds), shed_type: str(editing?.shed_type) || "open",
    remarks: str(editing?.remarks), aadhaar_number: str(editing?.aadhaar_number),
    pan_card: str(editing?.pan_card),
    account_holder_name: str(editing?.account_holder_name), acc_no: str(editing?.acc_no),
    ifsc_code: str(editing?.ifsc_code), bank_name: str(editing?.bank_name),
    bank_branch: str(editing?.bank_branch),
    physically_verified: editing?.physically_verified ? "true" : "false",
  }));
  const [sameAsPrimary, setSameAsPrimary] = useState(
    !!editing && !!editing.whatsapp_number && editing.whatsapp_number === editing.primary_mobile,
  );
  const [sheds, setSheds] = useState<ShedRow[]>(() => {
    const rows = Array.isArray(editing?.sheds) ? editing.sheds : [];
    return rows.length
      ? rows.map((s: any) => ({ length: str(s.length), width: str(s.width) }))
      : [{ length: "", width: "" }];
  });
  const [branchOptions, setBranchOptions] = useState<Option[]>([]);
  const [groupOptions, setGroupOptions] = useState<Option[]>([]);
  const [supervisorOptions, setSupervisorOptions] = useState<Option[]>([]);
  const [farmerPhoto, setFarmerPhoto] = useState(str(editing?.farmer_photo));
  const [slots, setSlots] = useState<Record<string, string>>(() => {
    const initial: Record<string, string> = {};
    for (const slot of KYC_SLOTS) initial[slot.key] = str((editing as any)?.[slot.key]);
    return initial;
  });
  const [existingPhotos, setExistingPhotos] = useState<{ id: number; url: string }[]>(
    Array.isArray(editing?.photos) ? editing.photos : [],
  );
  const [pendingPhotos, setPendingPhotos] = useState<string[]>([]);
  const [removedPhotoIds, setRemovedPhotoIds] = useState<number[]>([]);
  const [gpsNote, setGpsNote] = useState("");
  const [locating, setLocating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useLayoutEffect(() => {
    navigation.setOptions({
      title: editing ? "Farmer & Farm Setup Request" : "New Farmer & Farm Setup",
    });
  }, [navigation, editing]);

  React.useEffect(() => {
    (async () => {
      try {
        const { data } = await http.get<Envelope<Branch[]>>(
          "/broiler/branches/", { params: { page_size: 200 } });
        setBranchOptions(data.data.map((b) => ({ value: String(b.id), label: b.branch_name })));
      } catch { /* the picker simply stays empty */ }
      try {
        const { data } = await http.get<Envelope<FarmerGroupRow[]>>(
          "/broiler/farmer-groups/", { params: { page_size: 200 } });
        setGroupOptions(data.data.map((g) => ({
          value: String(g.id), label: g.description || g.code,
        })));
      } catch { /* Farmer Group is optional; an empty picker just offers none */ }
      if (editing?.branch) await loadSupervisors(String(editing.branch));
    })();
  }, []);

  /** Supervisor is reached through Branch, same cascade the Broiler Farm
   *  master's own form uses — a request belongs to whichever branch it was
   *  raised for, and that branch is what limits who may take it on. */
  const loadSupervisors = async (branchId: string) => {
    if (!branchId) return setSupervisorOptions([]);
    try {
      const { data } = await http.get<Envelope<SupervisorRow[]>>(
        "/broiler/supervisors/", { params: { branch: branchId, page_size: 200 } });
      setSupervisorOptions(data.data.map((s) => ({ value: String(s.id), label: s.name })));
    } catch {
      setSupervisorOptions([]);
    }
  };

  const onChange = (name: string) => (value: string) => {
    setValues((cur) => ({ ...cur, [name]: value }));
  };

  const onBranchChange = (value: string) => {
    setValues((cur) => ({ ...cur, branch: value, supervisor: "" }));
    loadSupervisors(value);
  };

  /** Ticking the box copies Primary Mobile in immediately and keeps mirroring
   *  it; typing a WhatsApp number of its own un-ticks it, same as the web
   *  form's checkbox. */
  const onPrimaryMobileChange = (value: string) => {
    setValues((cur) => ({
      ...cur, primary_mobile: value,
      whatsapp_number: sameAsPrimary ? value : cur.whatsapp_number,
    }));
  };
  const onWhatsappChange = (value: string) => {
    setSameAsPrimary(false);
    setValues((cur) => ({ ...cur, whatsapp_number: value }));
  };
  const onToggleSameAsPrimary = () => {
    setSameAsPrimary((cur) => {
      const next = !cur;
      if (next) setValues((v) => ({ ...v, whatsapp_number: v.primary_mobile }));
      return next;
    });
  };

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
      setValues((cur) => ({ ...cur, latitude, longitude, gps_captured_at: new Date().toISOString() }));
      setGpsNote("Pin captured — looking up the address…");
      const place = await reverseGeocode(latitude, longitude);
      if (!place) {
        setGpsNote("Pin captured. No address found for it — type one if needed.");
        return;
      }
      setValues((cur) => ({
        ...cur,
        state: cur.state || place.state || cur.state,
        district: cur.district || place.district || cur.district,
        village_area: cur.village_area || place.area || cur.village_area,
        full_address: cur.full_address.trim() ? cur.full_address : place.display,
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

  /** One attach button asking where a KYC scan comes from — camera, gallery
   *  or a file already on the phone. The farmer's own photo skips the
   *  question: it is the one thing the visit exists to prove, so it has to
   *  be taken there and then. */
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

  /** Farm Pictures: any number, added one at a time the same way a KYC scan
   *  is — an existing one is only marked for removal until save confirms it,
   *  matching the shed rows and the KYC slots' own "nothing is lost by
   *  re-sending nothing" rule. */
  const addPhoto = attach((uri) => setPendingPhotos((cur) => [...cur, uri]));
  const removePendingPhoto = (i: number) =>
    setPendingPhotos((cur) => cur.filter((_, j) => j !== i));
  const removeExistingPhoto = (id: number) => {
    setRemovedPhotoIds((cur) => [...cur, id]);
    setExistingPhotos((cur) => cur.filter((p) => p.id !== id));
  };

  const shedArea = (row: ShedRow) => {
    const l = parseFloat(row.length) || 0;
    const w = parseFloat(row.width) || 0;
    return l && w ? (l * w).toFixed(2) : "";
  };
  const updateShed = (i: number, patch: Partial<ShedRow>) =>
    setSheds((cur) => cur.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const addShed = () => setSheds((cur) => [...cur, { length: "", width: "" }]);
  const removeShed = (i: number) => setSheds((cur) => cur.filter((_, j) => j !== i));
  const shedSummary = () => {
    if (!sheds.length) return "";
    const totalArea = sheds.reduce((t, r) => t + (parseFloat(shedArea(r)) || 0), 0);
    const capacity = parseFloat(values.capacity_birds) || 0;
    const perShed = Math.floor(capacity / sheds.length);
    return `${sheds.length} shed(s) · total ${totalArea.toFixed(2)} sq ft`
      + (capacity ? ` · ~${perShed} birds/shed` : "");
  };

  const save = async (action: "draft" | "submit") => {
    setError(null);
    if (!values.branch && !editing) return setError("Select a branch.");
    if (action === "submit" && values.physically_verified !== "true") {
      return setError("Tick Physically Verified before submitting for approval.");
    }

    setSaving(true);
    try {
      const fields: Record<string, unknown> = { action };
      if (!editing) fields.branch = values.branch;
      for (const key of FIELD_KEYS) {
        if (values[key]) fields[key] = values[key];
      }
      fields.physically_verified = values.physically_verified;
      if (values.latitude) fields.latitude = values.latitude;
      if (values.longitude) fields.longitude = values.longitude;
      if (values.gps_captured_at) fields.gps_captured_at = values.gps_captured_at;
      fields.sheds = JSON.stringify(
        sheds.filter((r) => r.length || r.width).map((r) => ({ length: r.length || null, width: r.width || null })),
      );

      // Only a freshly-picked local file goes back out — a slot still holding
      // the URL it was loaded with is already saved, and re-sending nothing
      // for it leaves the stored file exactly as it was (same convention as
      // FarmCaptureFormScreen's own slots).
      const isLocal = (uri: string) => !!uri && !/^https?:\/\//i.test(uri);
      const files: { field: string; uri: string }[] = [
        ...(isLocal(farmerPhoto) ? [{ field: "farmer_photo", uri: farmerPhoto }] : []),
        ...KYC_SLOTS
          .filter((slot) => isLocal(slots[slot.key]))
          .map((slot) => ({ field: slot.key, uri: slots[slot.key] })),
        // Every picture posts under the same field name — Django reads them
        // all back with request.FILES.getlist("photos").
        ...pendingPhotos.map((uri) => ({ field: "photos", uri })),
      ];
      fields.remove_photo_ids = JSON.stringify(removedPhotoIds);

      const url = editing
        ? `/broiler/farmer-farm-setup-requests/save/${editing.id}`
        : "/broiler/farmer-farm-setup-requests/save";
      const written = await writeThrough({
        type: "farmer_farm_setup_request", label: "Farmer & Farm Setup Request",
        method: "POST", path: url,
        body: { fields, files },
        scope: { branch_id: values.branch || null },
        gps: values.latitude && values.longitude
          ? { latitude: Number(values.latitude), longitude: Number(values.longitude), accuracy: null }
          : null,
      });
      queryClient.invalidateQueries({ queryKey: ["list", "/broiler/farmer-farm-setup-requests/"] });
      if (written.queued) {
        await notify("Saved on this phone",
          "No signal — this request is stored on the device and will go to the "
          + "ERP by itself once you are back in range.");
      }
      navigation.goBack();
    } catch (e: unknown) {
      const message = (e as { message?: string })?.message ?? "Could not save the request.";
      setError(message);
      Alert.alert("Could not save", message);
    } finally {
      setSaving(false);
    }
  };

  const SectionHead = ({ n, title, tone }: { n: number; title: string; tone: string }) => (
    <View style={styles.sectionHead}>
      <View style={[styles.badge, { backgroundColor: tone }]}>
        <Text style={styles.badgeText}>{n}</Text>
      </View>
      <Text style={[styles.sectionTitle, { color: tone }]}>{title}</Text>
    </View>
  );

  const statusTone = editing?.status === "approved" ? colors.success
    : editing?.status === "rejected" ? colors.danger
    : editing?.status === "pending" ? colors.warning : colors.textMuted;

  return (
    <View style={styles.screen}>
      <ScrollView contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
        {error ? <Text style={styles.error}>{error}</Text> : null}

        {editing ? (
          <View style={[styles.statusBanner, { borderColor: statusTone }]}>
            <Text style={[styles.statusText, { color: statusTone }]}>
              {STATUS_LABEL[str(editing.status)] ?? str(editing.status)}
            </Text>
            {editing.review_note ? <Text style={styles.note}>{str(editing.review_note)}</Text> : null}
          </View>
        ) : null}

        <View style={styles.card}>
          <SectionHead n={1} title="FARM LOCATION & GPS" tone={colors.tint} />
          {!locked ? (
            <Pressable
              style={({ pressed }) => [
                styles.gpsButton, pressed && styles.gpsButtonPressed, locating && { opacity: 0.6 },
              ]}
              onPress={useMyLocation} disabled={locating} accessibilityRole="button"
            >
              <AppIcon name="crosshairs-gps" size={18} color={colors.onDark} />
              <Text style={styles.gpsText}>{locating ? "Reading location…" : "Capture GPS Location"}</Text>
            </Pressable>
          ) : null}
          {gpsNote ? <Text style={styles.note}>{gpsNote}</Text> : null}
          <View style={styles.row}>
            <View style={styles.cell}>
              <FormControl field={LAT} value={values.latitude} values={values} onChange={() => {}} />
            </View>
            <View style={styles.cell}>
              <FormControl field={LNG} value={values.longitude} values={values} onChange={() => {}} />
            </View>
          </View>
          <FormControl field={CAPTURED_AT}
                       value={values.gps_captured_at ? new Date(values.gps_captured_at).toLocaleString() : ""}
                       values={values} onChange={() => {}} />
          <View style={styles.row}>
            <View style={styles.cell}>
              <FormControl field={ro(STATE, locked)} value={values.state} values={values}
                           onChange={onChange("state")} />
            </View>
            <View style={styles.cell}>
              <FormControl field={ro(DISTRICT, locked)} value={values.district} values={values}
                           onChange={onChange("district")} />
            </View>
          </View>
          <FormControl field={ro(VILLAGE_AREA, locked)} value={values.village_area} values={values}
                       onChange={onChange("village_area")} />
          <FormControl field={ro(FULL_ADDRESS, locked)} value={values.full_address} values={values}
                       onChange={onChange("full_address")} />
        </View>

        <View style={styles.card}>
          <SectionHead n={2} title="FARMER PROFILE & CONTACT" tone={colors.success} />
          <FormControl field={ro(FARMER_NAME, locked)} value={values.farmer_name} values={values}
                       onChange={onChange("farmer_name")} />
          <FormControl field={ro(FATHER_SPOUSE_NAME, locked)} value={values.father_spouse_name} values={values}
                       onChange={onChange("father_spouse_name")} />
          <FormControl field={ro(PRIMARY_MOBILE, locked)} value={values.primary_mobile} values={values}
                       onChange={onPrimaryMobileChange} />
          {!locked ? (
            <Pressable style={styles.checkRow} onPress={onToggleSameAsPrimary}>
              <View style={[styles.checkbox, sameAsPrimary && styles.checkboxOn]}>
                {sameAsPrimary ? <AppIcon name="check" size={14} color={colors.onDark} /> : null}
              </View>
              <Text style={styles.checkLabel}>Same as Primary Mobile</Text>
            </Pressable>
          ) : null}
          <FormControl
            field={ro({
              name: "whatsapp_number", label: "WhatsApp Number", type: "text",
              placeholder: "Same as Primary (optional)",
            }, locked || sameAsPrimary)}
            value={values.whatsapp_number} values={values} onChange={onWhatsappChange}
          />
          <FormControl field={ro(ALTERNATE_MOBILE, locked)} value={values.alternate_mobile} values={values}
                       onChange={onChange("alternate_mobile")} />
          <FormControl field={ro(EMAIL, locked)} value={values.email} values={values}
                       onChange={onChange("email")} />
          <FormControl field={ro(FARMER_ADDRESS, locked)} value={values.farmer_address} values={values}
                       onChange={onChange("farmer_address")} />

          <Text style={styles.fieldLabel}>Farmer Photo</Text>
          {farmerPhoto ? (
            <View style={styles.slotRow}>
              <AppIcon name="check-circle" size={16} color={colors.success} />
              <Text style={styles.slotLabel} numberOfLines={1}>Attached</Text>
              {!locked ? (
                <Pressable style={styles.slotButton} onPress={attach(setFarmerPhoto, true)}>
                  <Text style={[styles.slotButtonText, { color: colors.tint }]}>Retake</Text>
                </Pressable>
              ) : null}
            </View>
          ) : !locked ? (
            <Pressable style={styles.dropZone} onPress={attach(setFarmerPhoto, true)}>
              <AppIcon name="camera-outline" size={18} color={colors.tint} />
              <Text style={[styles.dropText, { color: colors.tint }]}>Tap to Capture</Text>
            </Pressable>
          ) : (
            <Text style={styles.note}>Not attached</Text>
          )}
        </View>

        <View style={styles.card}>
          <SectionHead n={3} title="FARM & SHED DETAILS" tone={colors.warning} />
          {!locked ? (
            <FormControl field={{ name: "branch", label: "Branch", type: "select", required: true,
                                   options: branchOptions, placeholder: "Select a branch" }}
                         value={values.branch} values={values} onChange={onBranchChange} />
          ) : (
            <FormControl field={{ name: "branch", label: "Branch", type: "text", readOnly: true }}
                         value={branchOptions.find((b) => b.value === values.branch)?.label ?? values.branch}
                         values={values} onChange={() => {}} />
          )}
          <FormControl field={ro(LINE, locked)} value={values.line} values={values}
                       onChange={onChange("line")} />
          {!locked ? (
            <FormControl field={{ name: "supervisor", label: "Supervisor", type: "select", required: true,
                                   options: supervisorOptions,
                                   placeholder: values.branch ? "Select a supervisor" : "Select a branch first" }}
                         value={values.supervisor} values={values} onChange={onChange("supervisor")} />
          ) : (
            <FormControl field={{ name: "supervisor", label: "Supervisor", type: "text", readOnly: true }}
                         value={supervisorOptions.find((s) => s.value === values.supervisor)?.label ?? ""}
                         values={values} onChange={() => {}} />
          )}
          <FormControl field={ro(FARM_NAME, locked)} value={values.farm_name} values={values}
                       onChange={onChange("farm_name")} />
          <FormControl field={ro({ name: "farm_type", label: "Farm Type", type: "select", required: true,
                                    options: FARM_TYPE_OPTIONS }, locked)}
                       value={values.farm_type} values={values} onChange={onChange("farm_type")} />
          <FormControl field={ro({ name: "farmer_group", label: "Farmer Group", type: "select",
                                    options: groupOptions, placeholder: "None" }, locked)}
                       value={values.farmer_group} values={values} onChange={onChange("farmer_group")} />
          <FormControl field={ro(CAPACITY_BIRDS, locked)} value={values.capacity_birds} values={values}
                       onChange={onChange("capacity_birds")} />
          <FormControl field={ro({ name: "shed_type", label: "Shed Type", type: "select", required: true,
                                    options: SHED_TYPE_OPTIONS }, locked)}
                       value={values.shed_type} values={values} onChange={onChange("shed_type")} />

          <Text style={styles.fieldLabel}>Sheds <Text style={{ color: colors.danger }}>*</Text></Text>
          {sheds.map((row, i) => (
            <View key={i} style={styles.shedRow}>
              <View style={styles.shedCell}>
                <Text style={styles.shedCellLabel}>Length (ft)</Text>
                <TextInput style={styles.input} keyboardType="decimal-pad" value={row.length}
                           editable={!locked} onChangeText={(v) => updateShed(i, { length: v })} />
              </View>
              <View style={styles.shedCell}>
                <Text style={styles.shedCellLabel}>Width (ft)</Text>
                <TextInput style={styles.input} keyboardType="decimal-pad" value={row.width}
                           editable={!locked} onChangeText={(v) => updateShed(i, { width: v })} />
              </View>
              <View style={styles.shedCell}>
                <Text style={styles.shedCellLabel}>Area (sq ft)</Text>
                <View style={[styles.input, styles.readonly]}>
                  <Text style={styles.readonlyText}>{shedArea(row) || "—"}</Text>
                </View>
              </View>
              {!locked && sheds.length > 1 ? (
                <Pressable style={styles.shedRemove} onPress={() => removeShed(i)}>
                  <AppIcon name="close" size={16} color={colors.danger} />
                </Pressable>
              ) : null}
            </View>
          ))}
          {!locked ? (
            <Pressable style={styles.dropZone} onPress={addShed}>
              <AppIcon name="plus" size={18} color={colors.tint} />
              <Text style={[styles.dropText, { color: colors.tint }]}>Add Shed</Text>
            </Pressable>
          ) : null}
          {shedSummary() ? <Text style={styles.note}>{shedSummary()}</Text> : null}

          <Text style={styles.fieldLabel}>Farm Pictures</Text>
          {!locked ? (
            <Pressable style={styles.dropZone} onPress={addPhoto}>
              <AppIcon name="camera-outline" size={18} color={colors.tint} />
              <Text style={[styles.dropText, { color: colors.tint }]}>Add Picture</Text>
            </Pressable>
          ) : null}
          <View style={styles.thumbs}>
            {existingPhotos.map((p) => (
              <Pressable key={`existing-${p.id}`} style={styles.thumbWrap}
                         onPress={() => !locked && removeExistingPhoto(p.id)}>
                <Image source={{ uri: p.url }} style={styles.thumb} />
                {!locked ? (
                  <View style={styles.thumbX}><Text style={styles.thumbXText}>×</Text></View>
                ) : null}
              </Pressable>
            ))}
            {pendingPhotos.map((uri, i) => (
              <Pressable key={`pending-${i}`} style={styles.thumbWrap} onPress={() => removePendingPhoto(i)}>
                <Image source={{ uri }} style={styles.thumb} />
                <View style={styles.thumbX}><Text style={styles.thumbXText}>×</Text></View>
              </Pressable>
            ))}
          </View>

          <FormControl field={ro(REMARKS, locked)} value={values.remarks} values={values}
                       onChange={onChange("remarks")} />
        </View>

        <View style={styles.card}>
          <SectionHead n={4} title="BANK DETAILS" tone={colors.tint} />
          <FormControl field={ro(ACCOUNT_HOLDER_NAME, locked)} value={values.account_holder_name} values={values}
                       onChange={onChange("account_holder_name")} />
          <FormControl field={ro(ACC_NO, locked)} value={values.acc_no} values={values}
                       onChange={onChange("acc_no")} />
          <FormControl field={ro(IFSC_CODE, locked)} value={values.ifsc_code} values={values}
                       onChange={onChange("ifsc_code")} />
          <FormControl field={ro(BANK_NAME, locked)} value={values.bank_name} values={values}
                       onChange={onChange("bank_name")} />
          <FormControl field={ro(BANK_BRANCH, locked)} value={values.bank_branch} values={values}
                       onChange={onChange("bank_branch")} />
        </View>

        <View style={styles.card}>
          <SectionHead n={5} title="KYC & DOCUMENTS" tone={colors.tint} />
          <FormControl field={ro(AADHAAR_NUMBER, locked)} value={values.aadhaar_number} values={values}
                       onChange={onChange("aadhaar_number")} />
          <FormControl field={ro(PAN_CARD, locked)} value={values.pan_card} values={values}
                       onChange={onChange("pan_card")} />

          <View style={styles.slots}>
            {KYC_SLOTS.map((slot) => {
              const filled = !!slots[slot.key];
              return (
                <View key={slot.key} style={styles.slotRow}>
                  <AppIcon name={filled ? "check-circle" : "file-document"} size={16}
                           color={filled ? colors.success : colors.textMuted} />
                  <Text style={styles.slotLabel} numberOfLines={1}>{slot.label}</Text>
                  {!locked ? (
                    <Pressable
                      style={[styles.slotButton, filled && { borderColor: colors.success }]}
                      onPress={attach((u) => setSlots((c) => ({ ...c, [slot.key]: u })))}>
                      <Text style={[styles.slotButtonText,
                                    { color: filled ? colors.success : colors.tint }]}>
                        {filled ? "Attached" : "Upload"}
                      </Text>
                    </Pressable>
                  ) : (
                    <Text style={styles.slotButtonText}>{filled ? "Attached" : "Not attached"}</Text>
                  )}
                </View>
              );
            })}
          </View>

          <View style={styles.verifyRow}>
            <Text style={styles.verifyLabel}>
              Physically Verified<Text style={{ color: colors.danger }}> *</Text>
            </Text>
            <Switch
              value={values.physically_verified === "true"}
              onValueChange={(v) => onChange("physically_verified")(v ? "true" : "false")}
              trackColor={{ true: colors.tint }}
              disabled={locked}
            />
          </View>
        </View>
      </ScrollView>

      {!locked ? (
        <View style={styles.footer}>
          <Pressable style={styles.cancel} onPress={() => navigation.goBack()}>
            <Text style={styles.cancelText}>Cancel</Text>
          </Pressable>
          <Pressable style={[styles.draftBtn, saving && { opacity: 0.6 }]}
                     onPress={() => save("draft")} disabled={saving}>
            <Text style={styles.draftBtnText}>Save Draft</Text>
          </Pressable>
          <Pressable style={[styles.save, { backgroundColor: colors.tint }, saving && { opacity: 0.6 }]}
                     onPress={() => save("submit")} disabled={saving}>
            <Text style={styles.saveText}>{saving ? "Saving…" : "Submit"}</Text>
          </Pressable>
        </View>
      ) : (
        <View style={styles.footer}>
          <Pressable style={styles.cancel} onPress={() => navigation.goBack()}>
            <Text style={styles.cancelText}>Close</Text>
          </Pressable>
        </View>
      )}
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
  badge: { width: 24, height: 24, borderRadius: 6, alignItems: "center", justifyContent: "center" },
  badgeText: { color: colors.onDark, fontWeight: "800", fontSize: 12 },
  sectionTitle: { ...type.label, letterSpacing: 0.6 },
  row: { flexDirection: "row", gap: spacing.sm, alignItems: "flex-start" },
  cell: { flex: 1, minWidth: 0 },

  statusBanner: {
    borderWidth: 1, borderRadius: radius.md, padding: spacing.md, backgroundColor: colors.surface, gap: spacing.xs,
  },
  statusText: { ...type.title, fontWeight: "800" },

  gpsButton: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.sm,
    backgroundColor: colors.success, borderRadius: radius.md, paddingVertical: spacing.md, ...shadow(2),
  },
  gpsButtonPressed: { opacity: 0.85, transform: [{ scale: 0.985 }] },
  gpsText: { ...type.title, color: colors.onDark },
  note: { ...type.caption, color: colors.textMuted, marginTop: spacing.xs },

  fieldLabel: { ...type.label, color: colors.text, marginTop: spacing.sm },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm,
    paddingHorizontal: spacing.sm, paddingVertical: spacing.sm, color: colors.text, ...type.body,
  },
  readonly: { backgroundColor: colors.surfaceAlt },
  readonlyText: { ...type.body, color: colors.textMuted },

  checkRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginTop: spacing.sm },
  checkbox: {
    width: 20, height: 20, borderRadius: 4, borderWidth: 1, borderColor: colors.border,
    alignItems: "center", justifyContent: "center",
  },
  checkboxOn: { backgroundColor: colors.tint, borderColor: colors.tint },
  checkLabel: { ...type.body, color: colors.text },

  verifyRow: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    marginTop: spacing.md,
  },
  verifyLabel: { ...type.body, color: colors.text, flex: 1, marginRight: spacing.sm },

  dropZone: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    borderWidth: 1, borderStyle: "dashed", borderColor: colors.border,
    borderRadius: radius.md, paddingVertical: spacing.md, marginTop: spacing.xs, gap: spacing.sm,
  },
  dropText: { ...type.body, fontWeight: "600" },

  slots: { gap: spacing.xs, marginTop: spacing.sm },
  slotRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingVertical: spacing.xs },
  slotLabel: { ...type.body, color: colors.text, flex: 1 },
  slotButton: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm,
    paddingHorizontal: spacing.md, paddingVertical: spacing.xs,
  },
  slotButtonText: { ...type.caption, fontWeight: "700" },

  thumbs: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, marginTop: spacing.sm },
  thumbWrap: { width: 64, height: 64 },
  thumb: { width: 64, height: 64, borderRadius: radius.sm, backgroundColor: colors.surfaceAlt },
  thumbX: {
    position: "absolute", top: -6, right: -6, width: 20, height: 20, borderRadius: 10,
    backgroundColor: colors.danger, alignItems: "center", justifyContent: "center",
  },
  thumbXText: { color: colors.onDark, fontWeight: "800", lineHeight: 18 },

  shedRow: { flexDirection: "row", gap: spacing.sm, alignItems: "flex-end", marginTop: spacing.sm },
  shedCell: { flex: 1, minWidth: 0 },
  shedCellLabel: { ...type.caption, color: colors.textMuted, marginBottom: spacing.xs },
  shedRemove: {
    width: 32, height: 40, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.border,
    alignItems: "center", justifyContent: "center",
  },

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
  draftBtn: {
    flex: 1, height: 48, borderRadius: radius.md, borderWidth: 1, borderColor: colors.tint,
    alignItems: "center", justifyContent: "center",
  },
  draftBtnText: { ...type.title, color: colors.tint },
  save: { flex: 1, height: 48, borderRadius: radius.md, alignItems: "center", justifyContent: "center" },
  saveText: { ...type.title, color: colors.onDark },
}));
