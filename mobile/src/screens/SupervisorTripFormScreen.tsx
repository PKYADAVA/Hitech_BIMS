import { NativeStackScreenProps } from "@react-navigation/native-stack";
import React, { useLayoutEffect, useMemo, useState } from "react";
import { Alert, Image, Pressable, ScrollView, Text, View } from "react-native";

import { fetchMe } from "@/api/auth";
import { http } from "@/api/client";
import { Envelope, Row } from "@/api/types";
import {
  appendImage, capturePhoto, CapturePermissionError, isLocalCapture,
  LocationUnavailableError, openLocationSettings, requireLocation,
} from "@/capture";
import { AppIcon } from "@/components/AppIcon";
import { FormControl } from "@/components/form";
import { FormField } from "@/config/forms";
import { reverseGeocode } from "@/domain/reverseGeocode";
import { ModuleStackParams } from "@/navigation/types";
import { queryClient } from "@/query/queryClient";
import { usePermissionsStore } from "@/store/permissionsStore";
import { makeStyles, radius, spacing, type, useTheme } from "@/theme";

type Props = NativeStackScreenProps<ModuleStackParams, "SupervisorTripForm">;

/**
 * Supervisor Daily Trip — a day on the road, farm to farm.
 *
 * The company reimburses this travel against the odometer, so the log has to
 * stand up on its own: a photograph at each end with its own GPS stamp, an
 * odometer shot, and a check-in taken at the farm gate rather than typed from
 * memory that evening. All of which is why it is recorded here and not on a
 * desktop — the ERP end is a report over what came back.
 *
 * The log is saved repeatedly through the day and ended once. Ending is a
 * separate action from saving, because it closes the odometer run.
 */

interface Option { value: string; label: string }

/**
 * Whose trip this is.
 *
 * A supervisor's own login already answers this, so it is shown and not asked:
 * the server files the trip against the supervisor linked to the login, and a
 * picker would only offer the chance to name someone else and have it ignored.
 *
 * A back-office login is not any supervisor, so for them it *is* a question —
 * and has to be, or an admin cannot record a trip at all.
 */
const PERSON_FIXED: FormField = {
  name: "employee_name", label: "Employee", type: "text", readOnly: true,
  placeholder: "From your login",
};
const PERSON_PICK: FormField = {
  name: "employee", label: "Employee", type: "select", required: true,
  optionsPath: "/hr/employees/", optionLabelKeys: ["full_name", "employee_id"],
};
/**
 * The day the trip was driven, never chosen.
 *
 * A trip is one supervisor's day and the database holds one per supervisor per
 * day, so a free date field offers exactly two things: logging a day that was
 * not worked, and colliding with a trip that already exists. It is stamped on
 * creation and read-only from then on.
 */
const DATE: FormField = {
  name: "date", label: "Date", type: "text", readOnly: true,
};
const VEHICLE: FormField = {
  name: "vehicle_type", label: "Vehicle Type", type: "select", required: true,
  options: [
    { value: "Two Wheeler", label: "Two Wheeler" },
    { value: "Four Wheeler", label: "Four Wheeler" },
    { value: "Public Transport", label: "Public Transport" },
    { value: "Other", label: "Other" },
  ],
};
/**
 * The driver's registered vehicles. Picking one supplies both the type and the
 * number, so neither is typed again after the first time — which is what stops
 * one bike being recorded as three different vehicles across a month of logs.
 *
 * The free-text pair stays underneath as a read-only echo of what was picked,
 * because that is what the trip actually stores: a claim about a particular
 * day has to keep the registration as it stood, even if the vehicle is later
 * corrected or sold.
 */
const vehicleField = (options: Option[], typeChosen: boolean): FormField => ({
  name: "vehicle", label: "Registration", type: "select", required: true, options,
  placeholder: !typeChosen
    ? "Pick a vehicle type first"
    : options.length ? undefined : "None registered of that type",
});
/**
 * The registration as text. Used in two places, both of which need the number
 * rather than a row id: when the trip is locked (a read-only control renders
 * its raw value, so binding it to the vehicle's id showed a database number
 * where the plate should be), and when nobody has registered a vehicle and it
 * has to be typed.
 */
const REGISTRATION_TEXT = (readOnly: boolean): FormField => ({
  name: "registration", label: "Registration", type: "text", readOnly,
  placeholder: readOnly ? "From the vehicle" : "No vehicle registered — type it",
  required: !readOnly,
});
const START_ODO: FormField = { name: "start_odometer", label: "Start Odometer (km)", type: "number" };
const END_ODO: FormField = { name: "end_odometer", label: "End Odometer (km)", type: "number" };
const REMARKS: FormField = { name: "remarks", label: "Trip Remarks", type: "textarea" };

const farmField = (options: Option[]): FormField => ({
  name: "farm", label: "Farm", type: "select", required: true, options,
});
const PURPOSE: FormField = { name: "purpose", label: "Purpose", type: "text" };

const REMARKS_MAX = 200;
const today = () => new Date().toISOString().slice(0, 10);

/** A visit being built on screen. Times are ISO; the server derives duration. */
interface Visit {
  farm: string;
  farmLabel: string;
  purpose: string;
  checked_in_at: string;
  checked_out_at: string;
  latitude: string;
  longitude: string;
}

const clockLabel = (iso: string) =>
  iso ? new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";

const durationLabel = (from: string, to: string) => {
  if (!from || !to) return "";
  const minutes = Math.max(Math.round((Date.parse(to) - Date.parse(from)) / 60000), 0);
  const h = Math.floor(minutes / 60);
  return h ? `${h}h ${minutes % 60}m` : `${minutes}m`;
};

export function SupervisorTripFormScreen({ navigation, route }: Props) {
  const styles = useStyles();
  const { colors } = useTheme();
  const existing = route.params?.row ?? null;
  /** Arrived here from the register's End Trip, to supply the closing evidence. */
  const finishing = !!route.params?.ending;
  const canEdit = usePermissionsStore((s) => s.canResource)(
    "hr-supervisor-trips", "hr", "edit");

  const [values, setValues] = useState<Record<string, string>>({
    employee: "", date: today(), vehicle: "", vehicle_type: "", registration: "",
    start_address: "", end_address: "",
    start_odometer: "", end_odometer: "", remarks: "",
  });
  const [tripId, setTripId] = useState<number | null>(null);
  const [tripNo, setTripNo] = useState("");
  const [status, setStatus] = useState("In Progress");
  const [personName, setPersonName] = useState("");
  const [photos, setPhotos] = useState<Record<string, string>>({});
  const [visits, setVisits] = useState<Visit[]>([]);
  const [farmOptions, setFarmOptions] = useState<Option[]>([]);
  const [vehicles, setVehicles] = useState<Row[]>([]);

  /**
   * Registrations of the chosen type only.
   *
   * Type first, then the number mapped to it: someone with a bike and a car
   * says which they took, and is then offered the one or two numbers that can
   * possibly be. Offering every registration at once and hoping the right type
   * is picked alongside is how the two disagree on a claim.
   */
  const registrationOptions = useMemo<Option[]>(() =>
    vehicles
      .filter((v) => !values.vehicle_type || v.vehicle_type === values.vehicle_type)
      .map((v) => ({
        value: String(v.id),
        label: String(v.registration) + (v.nickname ? ` (${v.nickname})` : ""),
      })),
    [vehicles, values.vehicle_type]);
  /** Null until the profile answers; false means "pick whose trip this is". */
  const [isEmployee, setIsEmployee] = useState<boolean | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useLayoutEffect(() => {
    navigation.setOptions({ title: "Supervisor Daily Trip" });
  }, [navigation]);

  React.useEffect(() => {
    loadFarms();
    loadVehicles();
    if (!existing) {
      // Whose trip this will be, straight from the session — the same person
      // the server will file it against.
      fetchMe()
        .then((me) => {
          const own = !!me.employee;
          setIsEmployee(own);
          setPersonName(own ? me.employee_name || "" : "");
        })
        .catch(() => setIsEmployee(false));
      return;
    }
    const str = (v: unknown) => (v == null ? "" : String(v));
    setTripId(Number(existing.id));
    setTripNo(str(existing.trip_no));
    setStatus(str(existing.status) || "In Progress");
    setPersonName(str(existing.employee_name));
    setValues((cur) => ({
      ...cur,
      employee: str(existing.employee),
      date: str(existing.date) || cur.date,
      vehicle: str(existing.vehicle),
      vehicle_type: str(existing.vehicle_type) || cur.vehicle_type,
      registration: str(existing.registration),
      start_odometer: str(existing.start_odometer),
      end_odometer: str(existing.end_odometer),
      remarks: str(existing.remarks),
    }));
    // Photos already on the record arrive as stored URLs. Without this the
    // boxes read "Required" on a trip that was photographed days ago, and the
    // only way to see the picture was the ERP.
    const stored: Record<string, string> = {};
    for (const field of ["start_photo", "end_photo"]) {
      const url = str(existing[field]);
      if (url) stored[field] = url;
    }
    setPhotos(stored);

    const rows = (existing.visits as Row[] | undefined) ?? [];
    setVisits(rows.map((v) => ({
      farm: str(v.farm),
      farmLabel: str(v.farm_label),
      purpose: str(v.purpose),
      checked_in_at: str(v.checked_in_at),
      checked_out_at: str(v.checked_out_at),
      latitude: str(v.latitude),
      longitude: str(v.longitude),
    })));
  }, []);

  /**
   * The vehicles belonging to whoever the trip is for.
   *
   * A driver's own login already narrows this server-side. The case this
   * handles is the other one: a back-office login recording a trip for a
   * colleague sees every vehicle in scope, so the picker has to ask for that
   * colleague's. The server refuses a vehicle that is not theirs either way —
   * this is so the list never offers one it would then reject.
   */
  const loadVehicles = async (forEmployee?: string) => {
    try {
      const { data } = await http.get<Envelope<Row[]>>("/hr/vehicles/", {
        params: {
          is_retired: false, page_size: 100,
          ...(forEmployee ? { employee: forEmployee } : {}),
        },
      });
      setVehicles(data.data);
      // Start on the usual one, so the common case needs no tap at all.
      const usual = data.data.find((v) => v.is_default);
      if (usual) {
        setValues((cur) => cur.vehicle ? cur : {
          ...cur,
          vehicle_type: String(usual.vehicle_type || ""),
          vehicle: String(usual.id),
        });
      }
    } catch {
      setVehicles([]);
    }
  };

  const loadFarms = async () => {
    try {
      const { data } = await http.get<Envelope<Row[]>>(
        "/broiler/farms/", { params: { page_size: 500 } });
      setFarmOptions(data.data.map((f) => ({
        value: String(f.id),
        label: String(f.farm_name || f.farm_code || `#${f.id}`),
      })));
    } catch {
      setFarmOptions([]);
    }
  };

  const distance = useMemo(() => {
    const start = Number(values.start_odometer);
    const end = Number(values.end_odometer);
    if (!values.start_odometer || !values.end_odometer || Number.isNaN(start) || Number.isNaN(end)) {
      return null;
    }
    return Math.max(end - start, 0);
  }, [values.start_odometer, values.end_odometer]);

  const onChange = (name: string) => (value: string) => {
    setValues((cur) => ({ ...cur, [name]: value }));
    // Choosing whose trip it is changes whose vehicles may be picked, so the
    // list is reloaded and any vehicle already chosen is dropped.
    if (name === "vehicle_type") setValues((cur) => ({ ...cur, vehicle: "", registration: "" }));
    if (name === "vehicle") {
      const picked = vehicles.find((v) => String(v.id) === value);
      if (picked) {
        setValues((cur) => ({ ...cur, registration: String(picked.registration || "") }));
      }
    }
    if (name === "employee") {
      setValues((cur) => ({ ...cur, vehicle: "" }));
      loadVehicles(value);
    }
  };

  /**
   * A trip photograph is the pin as much as the picture — a shot at the depot
   * and a shot at the last farm are the whole point — so taking one also reads
   * the location, and the two travel together.
   */
  const takePhoto = (field: string, stampAs?: "start" | "end") => async () => {
    try {
      const shot = await capturePhoto();
      if (!shot) return;
      setPhotos((cur) => ({ ...cur, [field]: shot.uri }));
      if (!stampAs) return;
      const point = await requireLocation();
      setValues((cur) => ({
        ...cur,
        [`${stampAs}_latitude`]: point.latitude,
        [`${stampAs}_longitude`]: point.longitude,
      }));
      // Resolve the pin to an address too, the same way Farm Location Capture
      // does. A coordinate pair means nothing on a printed report; the written
      // form is what a reviewer can actually read. Best effort — a trip taken
      // out of signal still keeps its pin.
      const place = await reverseGeocode(point.latitude, point.longitude);
      if (place?.display) {
        setValues((cur) => ({ ...cur, [`${stampAs}_address`]: place.display }));
      }
    } catch (e) {
      if (e instanceof LocationUnavailableError) return askForLocation(e);
      Alert.alert(
        e instanceof CapturePermissionError ? "Permission needed" : "Could not take that",
        (e as Error)?.message ?? "Please try again.");
    }
  };

  /**
   * Send the user to the switch, rather than telling them a pin is missing.
   *
   * The two causes are fixed in different places — the device's location
   * setting, or this app's permission — so the prompt names the right one and
   * opens it.
   */
  const askForLocation = (e: LocationUnavailableError) => {
    const message = e.reason === "services-off"
      ? "Location is switched off on this device. A trip cannot be started without it."
      : e.reason === "denied"
        ? "BIMS needs permission to use your location before a trip can be started."
        : "No location fix yet. Step outside or wait a moment, then try again.";
    Alert.alert("Location needed", message,
      e.reason === "no-fix"
        ? [{ text: "OK" }]
        : [{ text: "Not now", style: "cancel" },
           { text: "Open settings", onPress: () => { void openLocationSettings(); } }]);
  };

  /** GPS one-tap check-in: stamps the arrival where the supervisor is now. */
  const checkIn = async () => {
    try {
      const point = await requireLocation();
      const now = new Date().toISOString();
      setVisits((cur) => [...cur, {
        farm: "", farmLabel: "", purpose: "",
        checked_in_at: now, checked_out_at: "",
        latitude: point.latitude, longitude: point.longitude,
      }]);
    } catch (e) {
      if (e instanceof LocationUnavailableError) return askForLocation(e);
      Alert.alert("Could not check in", (e as Error)?.message ?? "Please try again.");
    }
  };

  const setVisit = (index: number, key: keyof Visit, value: string) =>
    setVisits((cur) => cur.map((v, i) => (i === index ? { ...v, [key]: value } : v)));

  const body = async (extra: Record<string, string> = {}) => {
    const form = new FormData();
    if (isEmployee === false && values.employee) {
      form.append("employee", values.employee);
    }
    if (!values.vehicle) {
      // Typed by hand: the server takes the type and number as given.
      for (const key of ["vehicle_type", "registration"]) {
        if (values[key]) form.append(key, values[key]);
      }
    }
    for (const key of ["date", "vehicle",
                       "start_odometer", "end_odometer", "remarks",
                       "start_latitude", "start_longitude", "start_address",
                       "end_latitude", "end_longitude", "end_address"]) {
      if (values[key]) form.append(key, values[key]);
    }
    for (const [key, value] of Object.entries(extra)) form.append(key, value);
    // Only pictures taken in this session travel. A stored URL sent back would
    // be fetched and re-uploaded as a copy — or, worse, saved as the string.
    for (const [field, uri] of Object.entries(photos)) {
      if (uri && isLocalCapture(uri)) await appendImage(form, field, uri);
    }
    form.append("visits", JSON.stringify(
      visits.filter((v) => v.farm).map((v) => ({
        farm: v.farm, purpose: v.purpose,
        checked_in_at: v.checked_in_at || null,
        checked_out_at: v.checked_out_at || null,
        latitude: v.latitude, longitude: v.longitude,
      }))));
    return form;
  };

  const save = async (extra: Record<string, string> = {}, thenLeave = false) => {
    setError(null);
    if (!values.date) return setError("Date is required.");
    // A trip is a travel claim; without the opening photograph and the pin it
    // was taken at, there is nothing to check it against later.
    if (!tripId) {
      if (!photos.start_photo) {
        return setError("Take the start trip photo before saving.");
      }
      if (!values.start_latitude || !values.start_longitude) {
        return setError("The start photo has no location. Switch location on and retake it.");
      }
      if (!values.start_odometer) {
        return setError("Enter the start odometer reading.");
      }
    }
    if (!tripId && isEmployee === false && !values.employee) {
      return setError("Choose whose trip this is.");
    }
    const unnamed = visits.filter((v) => !v.farm).length;
    if (unnamed) return setError(`Choose a farm for ${unnamed} check-in(s).`);

    setSaving(true);
    try {
      const url = tripId ? `/hr/trips/save/${tripId}` : "/hr/trips/save";
      const { data } = await http.post<Envelope<{
        id: number; trip_no: string; status: string; distance_km: number;
      }>>(url, await body(extra), { headers: { "Content-Type": "multipart/form-data" } });
      setTripId(data.data.id);
      setTripNo(data.data.trip_no);
      setStatus(data.data.status);
      queryClient.invalidateQueries({ queryKey: ["resource", "/hr/trips/"] });
      // Home pins today's trip above the dashboard, and it is the screen a
      // driver lands back on — it must not still be offering "Start Trip".
      queryClient.invalidateQueries({ queryKey: ["today-trip"] });
      if (thenLeave) navigation.goBack();
    } catch (e: unknown) {
      // The envelope carries the useful part in `fields`; `message` alone is
      // the generic "Validation failed." that says nothing about what to fix.
      const err = e as { message?: string; fields?: Record<string, string[]> };
      const detail = Object.values(err.fields ?? {}).flat().join(" ");
      const message = detail || err.message || "Could not save the trip.";
      setError(message);
      Alert.alert("Could not save", message);
    } finally {
      setSaving(false);
    }
  };

  /**
   * Ending is the moment the closing evidence is recorded, so it says what is
   * missing before it closes anything. Named rather than refused: a camera can
   * fail on the road, and a trip that cannot be closed at all is worse than one
   * closed with a gap the report already flags.
   */
  const endTrip = () => {
    // The closing reading is not optional: it is half of the distance the
    // claim is paid on, and nobody can recover it later.
    if (!values.end_odometer) {
      setError("Enter the end odometer reading before ending the trip.");
      return Alert.alert("End odometer needed",
        "Enter the reading at the end of the trip. The distance is worked out " +
        "from it, and it cannot be recovered afterwards.");
    }
    const detail = photos.end_photo ? "" : "The end photo has not been taken. ";
    Alert.alert("End this trip?",
      `${detail}The odometer run closes and the log is settled.`, [
        { text: "Cancel", style: "cancel" },
        { text: photos.end_photo ? "End Trip" : "End anyway", style: "destructive",
          onPress: () => save({ end_trip: "true" }, true) },
      ]);
  };

  const PhotoBox = ({ field, label, hint, stampAs }: {
    field: string; label: string; hint: string; stampAs?: "start" | "end";
  }) => {
    const uri = photos[field];
    return (
      <View style={styles.cell}>
        <View style={styles.labelRow}>
          <Text style={styles.fieldLabel}>{label}</Text>
          <View style={[styles.pill, uri && { backgroundColor: colors.successLight }]}>
            <Text style={[styles.pillText, { color: uri ? colors.success : colors.textMuted }]}>
              {uri ? "Uploaded" : "Required"}
            </Text>
          </View>
        </View>
        <Pressable style={styles.dropZone} onPress={takePhoto(field, stampAs)}
                   disabled={locked || (stampAs === "start" && startLocked)}>
          {uri ? <Image source={{ uri }} style={styles.shot} /> : (
            <>
              <AppIcon name="camera-outline" size={22} color={colors.tint} />
              <Text style={[styles.dropTitle, { color: colors.tint }]}>{label}</Text>
              <Text style={styles.dropHint}>{hint}</Text>
            </>
          )}
        </Pressable>
      </View>
    );
  };

  const SectionHead = ({ icon, title }: { icon: string; title: string }) => (
    <View style={styles.sectionHead}>
      <AppIcon name={icon as never} size={18} color={colors.tint} />
      <Text style={[styles.sectionTitle, { color: colors.tint }]}>{title}</Text>
    </View>
  );

  const open = status !== "Completed";

  /**
   * A settled trip is read-only.
   *
   * Ending the trip closes the odometer run that the travel is reimbursed
   * against. Leaving the readings, the photographs and the timeline editable
   * afterwards would mean the figure someone approved and the figure now on
   * record need not be the same one, with nothing on the row to say it
   * changed. Correcting a settled trip is a decision for whoever settles it,
   * not a stray tap on a form that is still open.
   */
  //
  // ...but not to whoever settles it. A correction after the fact is a real
  // need, so the gate is the Edit permission rather than the status alone.
  const locked = !open && !canEdit;

  /**
   * Arriving to finish a trip locks how it started.
   *
   * The start photograph and the start reading were taken hours ago at the
   * vehicle; the only reason to be on this screen now is the closing pair.
   * Leaving the opening figures editable at the moment the distance is being
   * settled is an invitation to adjust the number the claim is calculated
   * from, and nothing on the record would show it had moved.
   */
  const startLocked = locked || (finishing && !!existing);
  const startRo = (field: FormField): FormField =>
    startLocked ? { ...field, readOnly: true, required: false } : field;
  /** The same field, refusing input once the trip is closed. */
  const ro = (field: FormField): FormField =>
    locked ? { ...field, readOnly: true, required: false } : field;

  return (
    <View style={styles.screen}>
      <ScrollView contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
        {error ? <Text style={styles.error}>{error}</Text> : null}
        {finishing && open ? (
          <View style={styles.finishNote}>
            <AppIcon name="flag-checkered" size={16} color={colors.warning} />
            <Text style={[styles.finishText, { color: colors.warning }]}>
              Finishing this trip — the start photo and start reading are fixed.
              Add the end photo and the end odometer, then End Trip.
            </Text>
          </View>
        ) : null}

        <View style={[styles.statusCard,
                      { backgroundColor: open ? colors.successLight : colors.surfaceAlt }]}>
          <View style={{ flex: 1 }}>
            <View style={styles.statusRow}>
              <View style={[styles.dot, { backgroundColor: open ? colors.success : colors.textMuted }]} />
              <Text style={[styles.statusText, { color: open ? colors.success : colors.textMuted }]}>
                {open ? "TRIP IN PROGRESS" : "TRIP COMPLETED"}
              </Text>
            </View>
            <Text style={styles.statusLine}>
              {tripNo || "Not started"}   •   {values.date}
            </Text>
            {personName ? (
              <Text style={styles.statusSub}>Supervisor: {personName}</Text>
            ) : null}
          </View>
          <View style={[styles.statusIcon, { backgroundColor: colors.surface }]}>
            <AppIcon name="car" size={22} color={open ? colors.success : colors.textMuted} />
          </View>
        </View>

        {!tripId ? (
          <View style={styles.card}>
            <SectionHead icon="account-outline" title="WHOSE TRIP" />
            <View style={styles.row}>
              <View style={styles.cell}>
                {isEmployee === false ? (
                  <FormControl field={PERSON_PICK} value={values.employee}
                               values={values} onChange={onChange("employee")} />
                ) : (
                  <FormControl field={PERSON_FIXED} value={personName}
                               values={values} onChange={() => {}} />
                )}
              </View>
              <View style={styles.cell}>
                <FormControl field={DATE} value={values.date} values={values}
                             onChange={() => {}} />
              </View>
            </View>
          </View>
        ) : null}

        <View style={styles.card}>
          <SectionHead icon="camera-outline" title="START & END TRIP PHOTOS" />
          <View style={styles.row}>
            {/* One shot at each end, and it is the odometer that has to be in
                it — the reading is what the travel is reimbursed against, and
                the photo carries its own GPS stamp so the reading is tied to
                where it was taken. */}
            <PhotoBox field="start_photo" label="Start Trip Photo"
                      hint="Odometer + current location" stampAs="start" />
            <PhotoBox field="end_photo" label="End Trip Photo"
                      hint="Odometer + end location" stampAs="end" />
          </View>
        </View>

        <View style={styles.card}>
          <SectionHead icon="car" title="VEHICLE & TRIP DETAILS" />
          <View style={styles.row}>
            <View style={styles.cell}>
              <FormControl field={startRo(VEHICLE)} value={values.vehicle_type}
                           values={values} onChange={onChange("vehicle_type")} />
            </View>
            <View style={styles.cell}>
              {startLocked || !registrationOptions.length ? (
                // Locked: show what the trip actually recorded. Unlocked with
                // nothing registered: let it be typed, so a driver whose
                // vehicle is not on file can still log the day.
                <FormControl field={REGISTRATION_TEXT(startLocked)}
                             value={values.registration} values={values}
                             onChange={onChange("registration")} />
              ) : (
                <FormControl field={vehicleField(registrationOptions,
                                                 !!values.vehicle_type)}
                             value={values.vehicle} values={values}
                             onChange={onChange("vehicle")} />
              )}
            </View>
          </View>
          <View style={styles.row}>
            <View style={styles.cell}>
              <FormControl field={startRo(START_ODO)} value={values.start_odometer} values={values}
                           onChange={onChange("start_odometer")} />
            </View>
            <View style={styles.cell}>
              <FormControl field={ro(END_ODO)} value={values.end_odometer} values={values}
                           onChange={onChange("end_odometer")} />
            </View>
          </View>
          {locked ? null : (
            <Pressable style={styles.manageLink}
                       onPress={() => navigation.navigate("List",
                                                          { resourceKey: "hr-vehicles" })}>
              <AppIcon name="playlist-edit" size={16} color={colors.tint} />
              <Text style={[styles.manageText, { color: colors.tint }]}>
                Manage my vehicles
              </Text>
            </Pressable>
          )}
          <View style={styles.distance}>
            <AppIcon name="map-marker-distance" size={18} color={colors.tint} />
            <Text style={[styles.distanceText, { color: colors.tint }]}>
              DISTANCE: {distance == null ? "—" : `${distance} km`}
            </Text>
          </View>
        </View>

        <View style={styles.card}>
          <SectionHead icon="map-marker" title={`FARM VISITS TIMELINE (${visits.length})`} />
          {visits.map((v, i) => (
            <View key={i} style={styles.visitRow}>
              <View style={styles.timeline}>
                <View style={[styles.node, { borderColor: colors.tint }]}>
                  <Text style={[styles.nodeText, { color: colors.tint }]}>{i + 1}</Text>
                </View>
                {i < visits.length - 1 ? <View style={styles.rail} /> : null}
              </View>
              <View style={styles.visitBody}>
                <View style={styles.labelRow}>
                  <Text style={styles.visitTime}>
                    {clockLabel(v.checked_in_at)}
                    {v.farmLabel ? `  •  ${v.farmLabel}` : ""}
                  </Text>
                  {locked ? null : (
                    <Pressable onPress={() => setVisits((c) => c.filter((_, j) => j !== i))}>
                      <Text style={[styles.remove, { color: colors.danger }]}>Remove</Text>
                    </Pressable>
                  )}
                </View>
                <FormControl field={ro(farmField(farmOptions))} value={v.farm}
                             onChange={(value) => {
                               setVisit(i, "farm", value);
                               setVisit(i, "farmLabel",
                                        farmOptions.find((o) => o.value === value)?.label ?? "");
                             }} />
                <FormControl field={ro(PURPOSE)} value={v.purpose}
                             onChange={(value) => setVisit(i, "purpose", value)} />
                <View style={styles.visitFoot}>
                  <Text style={styles.checkedIn}>
                    Checked-in: {clockLabel(v.checked_in_at) || "—"}
                    {v.checked_out_at ? `   •   ${durationLabel(v.checked_in_at, v.checked_out_at)}` : ""}
                  </Text>
                  {v.checked_out_at || locked ? null : (
                    <Pressable onPress={() => setVisit(i, "checked_out_at", new Date().toISOString())}>
                      <Text style={[styles.checkOut, { color: colors.tint }]}>Check out</Text>
                    </Pressable>
                  )}
                </View>
              </View>
            </View>
          ))}
          {locked ? null : (
          <Pressable style={styles.checkInButton} onPress={checkIn}>
            <AppIcon name="crosshairs-gps" size={18} color={colors.tint} />
            <Text style={[styles.checkInText, { color: colors.tint }]}>
              GPS One-Tap Check-In at New Visit
            </Text>
          </Pressable>
          )}
        </View>

        <View style={styles.card}>
          <SectionHead icon="message-outline" title="TRIP REMARKS" />
          <FormControl field={ro(REMARKS)} value={values.remarks} values={values}
                       onChange={(v) => onChange("remarks")(v.slice(0, REMARKS_MAX))} />
          <Text style={styles.counter}>{values.remarks.length}/{REMARKS_MAX}</Text>
        </View>
      </ScrollView>

      <View style={styles.footer}>
        {locked ? (
          <View style={styles.lockedNote}>
            <AppIcon name="lock-outline" size={16} color={colors.textMuted} />
            <Text style={styles.lockedText}>
              This trip is settled. Ask someone with edit rights to change it.
            </Text>
          </View>
        ) : (
        <>
        <Pressable style={[styles.endButton,
                           { borderColor: open ? colors.danger : colors.border },
                           !open && { opacity: 0.55 }]}
                   onPress={endTrip} disabled={saving || !open}>
          <AppIcon name={open ? "close-circle-outline" : "flag-checkered"} size={18}
                   color={open ? colors.danger : colors.textFaint} />
          <Text style={[styles.endText,
                        { color: open ? colors.danger : colors.textFaint }]}>
            {open ? "End Trip" : "Ended"}
          </Text>
        </Pressable>
        {/* Arriving to finish a trip leaves one thing to do. Save Log would
            write the closing photo and reading but leave the trip open, which
            is the one outcome nobody wants from this screen, so it greys out
            and End Trip is the way through. */}
        <Pressable style={[styles.saveButton,
                           { backgroundColor: finishing ? colors.surfaceAlt : colors.tint },
                           (saving || finishing) && { opacity: 0.55 }]}
                   onPress={() => save({}, true)} disabled={saving || finishing}>
          <AppIcon name="content-save-outline" size={18}
                   color={finishing ? colors.textFaint : colors.onDark} />
          <Text style={[styles.saveText,
                        finishing && { color: colors.textFaint }]}>
            {saving ? "Saving…" : "Save Log"}
          </Text>
        </Pressable>
        </>
        )}
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
  statusCard: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    borderRadius: radius.md, borderWidth: 1, borderColor: colors.border,
    padding: spacing.md,
  },
  statusRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  dot: { width: 10, height: 10, borderRadius: 5 },
  statusText: { ...type.label, letterSpacing: 0.6 },
  statusLine: { ...type.title, color: colors.text, marginTop: 4 },
  statusSub: { ...type.caption, color: colors.textMuted, marginTop: 2 },
  statusIcon: { width: 44, height: 44, borderRadius: 22, alignItems: "center", justifyContent: "center" },

  sectionHead: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginBottom: spacing.sm },
  sectionTitle: { ...type.label, letterSpacing: 0.6 },
  row: { flexDirection: "row", gap: spacing.sm, alignItems: "flex-start" },
  cell: { flex: 1, minWidth: 0 },
  labelRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  fieldLabel: { ...type.label, color: colors.text },
  pill: { borderRadius: radius.sm, paddingHorizontal: spacing.sm, paddingVertical: 2,
          backgroundColor: colors.surfaceAlt },
  pillText: { ...type.caption, fontWeight: "700" },

  dropZone: {
    alignItems: "center", justifyContent: "center", gap: 2,
    borderWidth: 1, borderStyle: "dashed", borderColor: colors.border,
    borderRadius: radius.md, paddingVertical: spacing.lg, marginTop: spacing.xs,
  },
  dropTitle: { ...type.body, fontWeight: "700" },
  dropHint: { ...type.caption, color: colors.textMuted },
  shot: { width: "100%", height: 96, borderRadius: radius.sm },

  manageLink: {
    flexDirection: "row", alignItems: "center", justifyContent: "flex-end",
    gap: spacing.xs, paddingVertical: spacing.xs,
  },
  manageText: { ...type.caption, fontWeight: "700" },
  distance: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    backgroundColor: colors.surfaceAlt, borderRadius: radius.md,
    paddingHorizontal: spacing.md, paddingVertical: spacing.md, marginTop: spacing.sm,
  },
  distanceText: { ...type.title },

  visitRow: { flexDirection: "row", gap: spacing.sm },
  timeline: { alignItems: "center", width: 28 },
  node: {
    width: 26, height: 26, borderRadius: 13, borderWidth: 2,
    alignItems: "center", justifyContent: "center", backgroundColor: colors.surface,
  },
  nodeText: { ...type.caption, fontWeight: "800" },
  rail: { flex: 1, width: 2, backgroundColor: colors.border, marginVertical: 2 },
  visitBody: {
    flex: 1, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    padding: spacing.sm, marginBottom: spacing.sm,
  },
  visitTime: { ...type.title, color: colors.text, flexShrink: 1 },
  remove: { ...type.caption, fontWeight: "700" },
  visitFoot: { flexDirection: "row", alignItems: "center", justifyContent: "space-between",
               marginTop: spacing.xs },
  checkedIn: { ...type.caption, color: colors.textMuted, flexShrink: 1 },
  checkOut: { ...type.caption, fontWeight: "700" },
  checkInButton: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.sm,
    borderWidth: 1, borderColor: colors.tint, borderRadius: radius.md,
    paddingVertical: spacing.md, marginTop: spacing.xs,
  },
  checkInText: { ...type.title },

  counter: { ...type.caption, color: colors.textMuted, textAlign: "right" },
  error: { ...type.caption, color: colors.danger },
  footer: {
    flexDirection: "row", gap: spacing.sm, padding: spacing.md,
    borderTopWidth: 1, borderTopColor: colors.border, backgroundColor: colors.surface,
  },
  finishNote: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    backgroundColor: colors.warningLight ?? colors.surfaceAlt,
    borderRadius: radius.md, padding: spacing.md,
  },
  finishText: { ...type.caption, fontWeight: "700", flex: 1 },
  lockedNote: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: spacing.sm, paddingVertical: spacing.md,
  },
  lockedText: { ...type.caption, color: colors.textMuted },
  endButton: {
    flex: 1, height: 48, borderRadius: radius.md, borderWidth: 1,
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.xs,
  },
  endText: { ...type.title },
  saveButton: {
    flex: 1.4, height: 48, borderRadius: radius.md,
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.xs,
  },
  saveText: { ...type.title, color: colors.onDark },
}));
