import { NativeStackScreenProps } from "@react-navigation/native-stack";
import React, { useLayoutEffect, useState } from "react";
import { Alert, Image, Pressable, Text, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { http } from "@/api/client";
import { createResource, deleteResource, listResource, updateResource } from "@/api/resources";
import { ApiError, Envelope, Row } from "@/api/types";
import {
  appendImage, capturePhoto, CapturePermissionError, isLocalCapture, pickPhoto, requireLocation,
  LocationUnavailableError, openLocationSettings,
} from "@/capture";
import { AppIcon, IconName } from "@/components/AppIcon";
import { FormControl } from "@/components/form";
import { KeyboardAwareScrollView } from "@/components/KeyboardAwareScrollView";
import { Button } from "@/components/ui";
import { FormField } from "@/config/forms";
import { reverseGeocode } from "@/domain/reverseGeocode";
import { ModuleStackParams } from "@/navigation/types";
import { queryClient } from "@/query/queryClient";
import { makeStyles, radius, spacing, type, useTheme, withAlpha } from "@/theme";
import { isEmpty } from "@/utils/format";

type Props = NativeStackScreenProps<ModuleStackParams, "BirdSaleForm">;

/**
 * Bird Sale — a lifting, recorded where it happens.
 *
 * The web form is a wide grid: one row per lifting, seventeen columns, several
 * liftings entered in a sitting. That shape is right at a desk and unusable on
 * a phone, so the same record is laid out here as four stacked sections —
 * party & farm, the weighment, the lifting itself, remarks — and several
 * liftings are several blocks rather than several rows.
 *
 * Same rules as the web, not a re-reading of them: the batch comes from the
 * farm (auto when there is one open flock, asked when there are more), the
 * farmer is the farm's own, the customer's outstanding balance is the Customer
 * Balance report's figure, and avg weight / amount are recomputed here only to
 * show what the server will store.
 *
 * What the phone adds is the evidence. A lifting is the one broiler
 * transaction nobody at the desk witnesses — the birds leave the farm and the
 * branch is billed for whatever the slip says — so this form stamps the GPS
 * pin and asks for the truck, the birds and the weighbridge slip. Both are
 * optional on the model, because the same sale is also raised at a desk from a
 * slip brought back; they are asked for here because here the camera is
 * standing in front of the lorry.
 */

const PATH = "/broiler/bird-sales/";
const PHOTOS_PATH = "/broiler/bird-sale-photos/";
const RESOURCE_KEY = "broiler-bird-sales";

type SaleType = "customer" | "farmer";

/** The three shots a lifting is expected to carry, in the order asked for.
 *  Mirrors `BirdSalePhoto.REQUIRED_KINDS`; "other" holds the Add More ones. */
const PHOTO_KINDS = [
  { kind: "truck", label: "Truck Photo" },
  { kind: "birds", label: "Birds Photo" },
  { kind: "weighbridge", label: "Weighbridge Slip" },
] as const;

type PhotoKind = "truck" | "birds" | "weighbridge" | "other";

/** Server-side cap (`BirdSalePhoto.MAX_PER_KIND`), mirrored so the Add tile
 *  disappears at the limit rather than letting a save fail on the sixth shot. */
const MAX_PER_KIND = 5;

const REMARKS_MAX = 200;

// Field configs for the shared FormControl — the same pickers as the web form.
const F_DATE: FormField = { name: "date", label: "Date", type: "date", required: true };
const F_DOC: FormField = { name: "doc_no", label: "Doc No.", type: "text" };
const F_CUSTOMER: FormField = {
  name: "customer", label: "Customer / Farmer", type: "select",
  optionsPath: "/sales/customers/", optionLabelKeys: ["name", "code"], required: true,
  placeholder: "Select Customer",
};
const F_FARM: FormField = {
  name: "farm", label: "Farm", type: "select",
  optionsPath: "/broiler/farms/", optionLabelKeys: ["farm_name", "farm_code"], required: true,
};
const F_BIRDS: FormField = { name: "birds", label: "Birds Count", type: "number", required: true };
const F_NET: FormField = { name: "net_weight", label: "Net Weight (Kg)", type: "decimal", required: true };
const F_RATE: FormField = { name: "rate", label: "Rate (₹)", type: "decimal", required: true };
const F_VEHICLE: FormField = { name: "vehicle", label: "Vehicle No.", type: "text", required: true };
const F_DRIVER: FormField = { name: "driver", label: "Driver Name", type: "text", required: true };
/**
 * Lifting Supervisor is *any active employee*, not the broiler Supervisor
 * master — the person who witnessed the weighment may be a branch manager, an
 * accountant or a weighbridge operator. The field is an `hr.Employee` FK, and
 * this picker used to list `/broiler/supervisors/`: a different table, whose
 * ids land on whichever employee happens to share the number.
 */
const F_SUPERVISOR: FormField = {
  name: "lifting_supervisor", label: "Lifting Supervisor", type: "select",
  optionsPath: "/hr/employees/?relieve=false", optionLabelKeys: ["full_name"], required: true,
};

/** The farm's open batches, as the picker's options. One is chosen for the
 *  user; more than one has to be asked, because a sale takes birds off
 *  whichever flock it names. */
const batchField = (batches: BatchOption[], farmChosen: boolean): FormField => ({
  name: "batch", label: "Batch", type: "select",
  options: batches.map((b) => ({ value: String(b.id), label: b.name })),
  placeholder: !farmChosen ? "Select a farm first" : batches.length ? "Select batch" : "No open batch",
});

interface BatchOption { id: number; name: string }

interface Balance {
  label: string;
  /** Over the customer's credit limit — shown in red rather than green. */
  exceeded: boolean;
  note: string;
}

/** One lifting: everything the four sections hold, plus what was looked up for it. */
interface SaleBlock {
  key: string;
  values: Record<string, string>;
  batches: BatchOption[];
  farmerId: string;
  farmerName: string;
  balance: Balance | null;
  place: string;
  gpsBusy: boolean;
  photos: Record<PhotoKind, string[]>;
  errors: Record<string, string>;
}

const num = (v: string) => Number(v) || 0;
const str = (v: unknown) => (isEmpty(v) ? "" : String(v));
const today = () => new Date().toISOString().slice(0, 10);
const noPhotos = (): Record<PhotoKind, string[]> =>
  ({ truck: [], birds: [], weighbridge: [], other: [] });

let seq = 0;
const blankBlock = (): SaleBlock => ({
  key: `b${++seq}`,
  values: {
    date: today(), doc_no: "", customer: "", farm: "", batch: "",
    birds: "", net_weight: "", rate: "",
    lifting_supervisor: "", vehicle: "", driver: "", remarks: "",
    latitude: "", longitude: "",
  },
  batches: [], farmerId: "", farmerName: "", balance: null,
  place: "", gpsBusy: false, photos: noPhotos(), errors: {},
});

/** Indian-format money, matching the ERP's amount columns. */
const money = (n: number) =>
  n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function BirdSaleFormScreen({ route, navigation }: Props) {
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const { mode, row } = route.params;
  const editing = mode === "edit";

  const [saleType, setSaleType] = useState<SaleType>(
    (row?.sale_type as SaleType) || "customer"
  );
  const [blocks, setBlocks] = useState<SaleBlock[]>(() => {
    if (!editing || !row) return [blankBlock()];
    const b = blankBlock();
    b.values = {
      date: str(row.date) || today(),
      doc_no: str(row.doc_no),
      customer: str(row.customer),
      farm: str(row.farm),
      batch: str(row.batch),
      birds: str(row.birds),
      net_weight: str(row.net_weight),
      rate: str(row.rate),
      lifting_supervisor: str(row.lifting_supervisor),
      vehicle: str(row.vehicle),
      driver: str(row.driver),
      remarks: str(row.remarks),
      latitude: str(row.lift_latitude),
      longitude: str(row.lift_longitude),
    };
    // The saved batch is shown as the chosen one, exactly as the web form's
    // prefill does — re-deriving it would silently move an old sale onto
    // whichever flock the farm is running now.
    if (row.batch) b.batches = [{ id: Number(row.batch), name: str(row.batch_label) || "Current batch" }];
    b.farmerId = str(row.farmer);
    b.farmerName = str(row.farmer_label);
    b.place = str(row.lift_place);
    return [b];
  });

  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useLayoutEffect(() => {
    navigation.setOptions({
      title: editing ? "Edit Bird Sale" : "Add Bird Sale",
      // The web form puts a Register link in its page header; the same way back
      // to the list belongs here, or the only exit is the back arrow.
      headerRight: () => (
        <Pressable
          onPress={() => navigation.navigate("List", { resourceKey: RESOURCE_KEY })}
          style={styles.registerBtn}
          accessibilityRole="button"
          accessibilityLabel="Bird Sale register"
        >
          <AppIcon name="format-list-bulleted" size={16} color={colors.onDark} />
          <Text style={styles.registerText}>Register</Text>
        </Pressable>
      ),
    });
  }, [navigation, editing, styles, colors.broiler]);

  /** Load an edited sale's photos, so its strips show what is already filed. */
  React.useEffect(() => {
    if (!editing || !row?.id) return;
    (async () => {
      try {
        const page = await listResource<Row>(PHOTOS_PATH, { sale: row.id as number, page_size: 100 });
        const found = noPhotos();
        for (const p of page.items) {
          const kind = str(p.kind) as PhotoKind;
          const url = str(p.image);
          if (url && kind in found) found[kind].push(url);
        }
        setBlocks((cur) => cur.map((b, i) => (i === 0 ? { ...b, photos: found } : b)));
      } catch {
        // A strip that could not be loaded is left empty; the sale itself is
        // editable regardless, and the photos already filed are untouched.
      }
    })();
  }, [editing, row?.id]);

  const patch = (key: string, changes: Partial<SaleBlock>) =>
    setBlocks((cur) => cur.map((b) => (b.key === key ? { ...b, ...changes } : b)));

  const setValue = (key: string, name: string, val: string) =>
    setBlocks((cur) =>
      cur.map((b) =>
        b.key === key
          ? { ...b, values: { ...b.values, [name]: val }, errors: { ...b.errors, [name]: "" } }
          : b
      )
    );

  /* ---------------------------------------------------------------- lookups */

  /** Farm → its open batches and its farmer, the web form's `farm` handler. */
  const onFarmChange = async (key: string, farmId: string) => {
    setBlocks((cur) =>
      cur.map((b) =>
        b.key === key
          ? { ...b, values: { ...b.values, farm: farmId, batch: "" }, batches: [],
              farmerId: "", farmerName: "", errors: { ...b.errors, farm: "" } }
          : b
      )
    );
    if (!farmId) return;
    try {
      const resp = await http.get<Envelope<{
        batches: BatchOption[]; farmer: number | null; farmer_name: string;
      }>>("/broiler/farm-lookup", { params: { farm: farmId } });
      const data = resp.data.data;
      const batches = data.batches || [];
      setBlocks((cur) =>
        cur.map((b) =>
          b.key === key
            ? {
                ...b,
                batches,
                // One open flock is chosen; two or more have to be asked.
                values: { ...b.values, batch: batches.length === 1 ? String(batches[0].id) : "" },
                farmerId: data.farmer ? String(data.farmer) : "",
                farmerName: data.farmer_name || "No farmer on record for this farm",
              }
            : b
        )
      );
    } catch {
      patch(key, { farmerName: "Could not read this farm's batches" });
    }
  };

  /** Customer → outstanding balance, the same figure the Customer Balance
   *  report shows and the web form fetches. */
  const onCustomerChange = async (key: string, customerId: string) => {
    setValue(key, "customer", customerId);
    if (!customerId) return patch(key, { balance: null });
    try {
      const resp = await http.get<Envelope<{
        label: string; credit_limit: string; available: string; limit_exceeded: string;
      }>>("/sales/customer-balance", { params: { customer: customerId } });
      const d = resp.data.data;
      const over = Number(d.limit_exceeded) > 0;
      patch(key, {
        balance: {
          label: d.label || "—",
          exceeded: over,
          note: over
            ? `Over credit limit by ${d.limit_exceeded} (limit ${d.credit_limit})`
            : Number(d.credit_limit) > 0
              ? `Limit ${d.credit_limit} · available ${d.available}`
              : "",
        },
      });
    } catch {
      patch(key, { balance: null });
    }
  };

  /* ------------------------------------------------------------------- GPS */

  const takeLocation = async (key: string) => {
    patch(key, { gpsBusy: true });
    try {
      const point = await requireLocation();
      // A pin without a name is still a pin — reverseGeocode answers null out
      // of signal, and the coordinates are what actually gets saved.
      const found = await reverseGeocode(point.latitude, point.longitude);
      const place = found?.display ?? "";
      setBlocks((cur) =>
        cur.map((b) =>
          b.key === key
            ? { ...b, gpsBusy: false, place,
                values: { ...b.values, latitude: point.latitude, longitude: point.longitude } }
            : b
        )
      );
    } catch (e) {
      patch(key, { gpsBusy: false });
      if (e instanceof LocationUnavailableError && e.reason === "services-off") {
        Alert.alert("Location is off", "Switch location on to stamp this lifting.", [
          { text: "Not now", style: "cancel" },
          { text: "Settings", onPress: () => void openLocationSettings() },
        ]);
      } else if (e instanceof LocationUnavailableError && e.reason === "denied") {
        Alert.alert("Location needed", "Allow location access to stamp this lifting.");
      } else {
        Alert.alert("No signal yet", "Could not get a fix — try again in the open.");
      }
    }
  };

  /* ---------------------------------------------------------------- photos */

  const addPhoto = async (key: string, kind: PhotoKind, fromGallery = false) => {
    try {
      const shot = fromGallery ? await pickPhoto() : await capturePhoto();
      if (!shot) return;
      setBlocks((cur) =>
        cur.map((b) =>
          b.key === key
            ? { ...b, photos: { ...b.photos, [kind]: [...b.photos[kind], shot.uri] } }
            : b
        )
      );
    } catch (e) {
      if (e instanceof CapturePermissionError) {
        Alert.alert(
          e.kind === "camera" ? "Camera needed" : "Photos needed",
          `Allow ${e.kind === "camera" ? "camera" : "photo library"} access to attach evidence.`
        );
      }
    }
  };

  const dropPhoto = (key: string, kind: PhotoKind, uri: string) =>
    setBlocks((cur) =>
      cur.map((b) =>
        b.key === key
          ? { ...b, photos: { ...b.photos, [kind]: b.photos[kind].filter((u) => u !== uri) } }
          : b
      )
    );

  /**
   * Push a block's local shots up against a saved sale.
   *
   * Reported rather than thrown: by this point the sale itself is filed, and
   * failing the whole save over a photo that did not upload would push the
   * supervisor into re-entering a record that already exists.
   */
  const uploadPhotos = async (saleId: number, block: SaleBlock): Promise<string[]> => {
    const failed: string[] = [];
    for (const kind of ["truck", "birds", "weighbridge", "other"] as PhotoKind[]) {
      for (const uri of block.photos[kind]) {
        if (!isLocalCapture(uri)) continue;              // already on the server
        try {
          const form = new FormData();
          form.append("sale", String(saleId));
          form.append("kind", kind);
          await appendImage(form, "image", uri);
          await createResource(PHOTOS_PATH, form);
        } catch {
          failed.push(PHOTO_KINDS.find((p) => p.kind === kind)?.label ?? "Extra photos");
        }
      }
    }
    return [...new Set(failed)];
  };

  /* ----------------------------------------------------------------- blocks */

  const addBlock = () =>
    setBlocks((cur) => {
      // A second lifting is nearly always the same round: same day, same
      // supervisor, same lorry. Carrying those over is the difference between
      // adding a lifting and re-entering one.
      const prev = cur[cur.length - 1];
      const fresh = blankBlock();
      fresh.values.date = prev.values.date;
      fresh.values.lifting_supervisor = prev.values.lifting_supervisor;
      fresh.values.vehicle = prev.values.vehicle;
      fresh.values.driver = prev.values.driver;
      fresh.values.latitude = prev.values.latitude;
      fresh.values.longitude = prev.values.longitude;
      fresh.place = prev.place;
      return [...cur, fresh];
    });

  const removeBlock = (key: string) =>
    setBlocks((cur) => (cur.length > 1 ? cur.filter((b) => b.key !== key) : cur));

  /* ------------------------------------------------------------------ save */

  const validate = (): boolean => {
    let ok = true;
    setBlocks((cur) =>
      cur.map((b) => {
        const e: Record<string, string> = {};
        if (isEmpty(b.values.date)) e.date = "Required";
        if (isEmpty(b.values.farm)) e.farm = "Required";
        if (isEmpty(b.values.net_weight) || num(b.values.net_weight) <= 0) e.net_weight = "Required";
        if (isEmpty(b.values.rate) || num(b.values.rate) <= 0) e.rate = "Required";
        if (isEmpty(b.values.birds) || num(b.values.birds) <= 0) e.birds = "Required";
        if (isEmpty(b.values.lifting_supervisor)) e.lifting_supervisor = "Required";
        if (isEmpty(b.values.vehicle)) e.vehicle = "Required";
        if (isEmpty(b.values.driver)) e.driver = "Required";
        // A farm running two flocks must be told which one; one open flock has
        // already been filled in, and a farm with none cannot be sold from.
        if (b.values.farm && b.batches.length > 1 && isEmpty(b.values.batch)) e.batch = "Select a batch";
        if (saleType === "customer" && isEmpty(b.values.customer)) e.customer = "Required";
        if (saleType === "farmer" && isEmpty(b.farmerId)) {
          e.farm = "This farm has no farmer on record";
        }
        if (Object.keys(e).length) ok = false;
        return { ...b, errors: e };
      })
    );
    return ok;
  };

  /**
   * The photo evidence the mockup marks mandatory.
   *
   * Asked for, not enforced — a warning the user may go past. The model keeps
   * the photos optional because the same sale is raised at a desk from a slip
   * brought in from the field, and a phone standing in a shed with no signal
   * must still be able to file the weighment it just watched.
   *
   * The GPS pin is not in here: it is taken at submit rather than asked for
   * (see `stampAll`), so there is nothing for the user to have forgotten.
   */
  const missingEvidence = (b: SaleBlock): string[] =>
    PHOTO_KINDS.filter(({ kind }) => !b.photos[kind].length).map((p) => p.label);

  /** The fix taken during submit, before the state holding it has re-rendered. */
  const pendingPoint = React.useRef<{ latitude: string; longitude: string; place: string } | null>(null);

  /**
   * Stamp every unstamped block with where the phone is standing.
   *
   * Taken on submit rather than left to a button: the pin's whole job is to
   * say where the lifting was recorded, and one that has to be remembered is
   * missing from exactly the records where it would have mattered. One fix
   * serves every block — they are one round, at one weighbridge, in one
   * sitting — and a block already stamped by hand keeps what it has.
   *
   * Returns false only if a pin was needed and could not be had.
   */
  const stampAll = async (): Promise<boolean> => {
    if (blocks.every((b) => b.values.latitude && b.values.longitude)) return true;
    try {
      const point = await requireLocation();
      const found = await reverseGeocode(point.latitude, point.longitude);
      const place = found?.display ?? "";
      setBlocks((cur) =>
        cur.map((b) =>
          b.values.latitude && b.values.longitude
            ? b
            : { ...b, place,
                values: { ...b.values, latitude: point.latitude, longitude: point.longitude } }
        )
      );
      // The save below reads `blocks` from this render, which React has not
      // re-run yet, so the payload is built from the fix directly.
      pendingPoint.current = { ...point, place };
      return true;
    } catch {
      return false;
    }
  };

  const payloadFor = (b: SaleBlock) => ({
    date: b.values.date,
    sale_type: saleType,
    doc_no: b.values.doc_no || "",
    farm: b.values.farm,
    batch: b.values.batch || null,
    customer: saleType === "customer" ? b.values.customer : null,
    birds: b.values.birds || "0",
    net_weight: b.values.net_weight || "0",
    rate: b.values.rate || "0",
    // round_off and amount are derived in BirdSale.save(); sending them would
    // be ignored, and disagreeing with them would be worse.
    lifting_supervisor: b.values.lifting_supervisor || null,
    vehicle: b.values.vehicle || "",
    driver: b.values.driver || "",
    remarks: b.values.remarks || "",
    lift_latitude: b.values.latitude || pendingPoint.current?.latitude || null,
    lift_longitude: b.values.longitude || pendingPoint.current?.longitude || null,
    lift_place: b.place || pendingPoint.current?.place || "",
    // farmer is derived from the farm server-side, exactly as on the web.
  });

  const submit = async () => {
    setFormError(null);
    if (!validate()) {
      setFormError("Fill in the fields marked in red.");
      return;
    }
    // The pin is taken here, not asked for — so it is the place the lifting
    // was actually filed from, and cannot be forgotten.
    setSaving(true);
    const located = await stampAll();
    setSaving(false);

    const gaps = [...new Set(blocks.flatMap(missingEvidence))];
    if (!located) gaps.unshift("GPS location");
    if (gaps.length) {
      const proceed = await confirm(
        "Evidence missing",
        `${gaps.join(", ")} not captured. Save the lifting anyway?`
      );
      if (!proceed) return;
    }
    await save();
  };

  const save = async () => {
    setSaving(true);
    const photoProblems: string[] = [];
    try {
      for (const b of blocks) {
        const saved = editing
          ? await updateResource<Row>(PATH, (row as Row).id, payloadFor(b))
          : await createResource<Row>(PATH, payloadFor(b));
        const id = Number(saved?.id ?? (row as Row)?.id);
        if (id) photoProblems.push(...(await uploadPhotos(id, b)));
      }
      queryClient.invalidateQueries({ queryKey: ["list", PATH] });
      if (photoProblems.length) {
        Alert.alert(
          "Saved, but some photos did not upload",
          `${photoProblems.join(", ")}. The sale is filed — re-attach them by editing it.`
        );
      }
      navigation.navigate("List", { resourceKey: RESOURCE_KEY });
    } catch (e) {
      handleApiError(e);
    } finally {
      setSaving(false);
    }
  };

  const onDelete = () => {
    Alert.alert("Delete", "Delete this bird sale?", [
      { text: "Cancel", style: "cancel" },
      {
        text: "Delete",
        style: "destructive",
        onPress: async () => {
          try {
            await deleteResource(PATH, (row as Row).id);
            queryClient.invalidateQueries({ queryKey: ["list", PATH] });
            navigation.navigate("List", { resourceKey: RESOURCE_KEY });
          } catch (e) {
            handleApiError(e);
          }
        },
      },
    ]);
  };

  const handleApiError = (e: unknown) => {
    if (e instanceof ApiError) {
      const fieldErrs: Record<string, string> = {};
      for (const [k, msgs] of Object.entries(e.fields || {})) {
        fieldErrs[k] = Array.isArray(msgs) ? msgs.join(" ") : String(msgs);
      }
      // Field errors belong to whichever block was rejected; with one save at a
      // time the first unsaved block is the one, and in edit mode the only one.
      setBlocks((cur) => cur.map((b, i) => (i === 0 ? { ...b, errors: fieldErrs } : b)));
      setFormError(e.message || "Please fix the errors and try again.");
    } else {
      setFormError((e as Error)?.message ?? "Something went wrong.");
    }
  };

  /* ---------------------------------------------------------------- render */

  return (
    <View style={styles.screen}>
      <KeyboardAwareScrollView contentContainerStyle={styles.content}>
        {formError ? <Text style={styles.formError}>{formError}</Text> : null}

        <SaleTypePicker value={saleType} onChange={setSaleType} disabled={editing} />

        {blocks.map((b, i) => (
          <SaleBlockView
            key={b.key}
            block={b}
            index={i}
            total={blocks.length}
            saleType={saleType}
            onRemove={() => removeBlock(b.key)}
            onValue={(name, v) => setValue(b.key, name, v)}
            onFarm={(v) => onFarmChange(b.key, v)}
            onCustomer={(v) => onCustomerChange(b.key, v)}
            onLocate={() => takeLocation(b.key)}
            onAddPhoto={(kind, gallery) => addPhoto(b.key, kind, gallery)}
            onDropPhoto={(kind, uri) => dropPhoto(b.key, kind, uri)}
          />
        ))}

        {!editing ? (
          <Pressable style={styles.addBlock} onPress={addBlock} accessibilityRole="button">
            <AppIcon name="plus" size={18} color={colors.broiler} />
            <Text style={styles.addBlockText}>Add Another Bird Sale</Text>
          </Pressable>
        ) : null}

        {editing ? (
          <View style={styles.deleteWrap}>
            <Button title="Delete this sale" variant="danger" onPress={onDelete} />
          </View>
        ) : null}
      </KeyboardAwareScrollView>

      {/* Cancel and Submit stay on screen: the form is long enough that a
          footer scrolled to the bottom is a footer nobody finds. */}
      <View style={[styles.footer, { paddingBottom: Math.max(insets.bottom, spacing.sm) }]}>
        <Pressable
          style={styles.cancelBtn}
          onPress={() => navigation.goBack()}
          accessibilityRole="button"
        >
          <AppIcon name="close" size={18} color={colors.danger} />
          <Text style={styles.cancelText}>Cancel</Text>
        </Pressable>
        <Pressable
          style={[styles.submitBtn, saving && styles.submitBusy]}
          onPress={submit}
          disabled={saving}
          accessibilityRole="button"
        >
          <AppIcon name="check" size={18} color="#fff" />
          <Text style={styles.submitText}>{saving ? "Saving…" : "Submit"}</Text>
        </Pressable>
      </View>
    </View>
  );
}

/* ==================================================================== parts */

/** Customer Sale / Farmer Sale — the web form's pair of radios. Global to the
 *  form, as it is there: a round is one kind of sale or the other. */
function SaleTypePicker({
  value, onChange, disabled,
}: { value: SaleType; onChange: (v: SaleType) => void; disabled?: boolean }) {
  const styles = useStyles();
  const { colors } = useTheme();
  return (
    <View style={styles.card}>
      <Text style={styles.cardCaption}>SALE TYPE</Text>
      <View style={styles.radioRow}>
        {(["customer", "farmer"] as SaleType[]).map((t) => {
          const on = value === t;
          return (
            <Pressable
              key={t}
              onPress={() => !disabled && onChange(t)}
              style={[styles.radio, on && styles.radioOn, disabled && styles.radioLocked]}
              accessibilityRole="radio"
              accessibilityState={{ selected: on, disabled }}
            >
              <View style={[styles.radioDot, on && { borderColor: colors.broiler }]}>
                {on ? <View style={styles.radioDotFill} /> : null}
              </View>
              <Text style={[styles.radioText, on && styles.radioTextOn]}>
                {t === "customer" ? "Customer Sale" : "Farmer Sale"}
              </Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

/** A numbered section: icon chip, title, and an optional control on the right. */
function Section({
  n, icon, title, note, right, children,
}: {
  n: number; icon: IconName; title: string; note?: string;
  right?: React.ReactNode; children: React.ReactNode;
}) {
  const styles = useStyles();
  return (
    <View style={styles.card}>
      <View style={styles.sectionHead}>
        <View style={styles.sectionIcon}>
          <AppIcon name={icon} size={17} color="#fff" />
        </View>
        <Text style={styles.sectionTitle}>{`${n}. ${title}`}</Text>
        {note ? <Text style={styles.sectionNote}>{note}</Text> : null}
        <View style={styles.spacer} />
        {right}
      </View>
      {children}
    </View>
  );
}

/** Two controls side by side, as the mockup pairs them. */
function Pair({ children }: { children: React.ReactNode }) {
  const styles = useStyles();
  return (
    <View style={styles.pair}>
      {React.Children.map(children, (c) => <View style={styles.pairCell}>{c}</View>)}
    </View>
  );
}

/** A derived value in the same shell as an input, so a read-only figure reads
 *  as part of the form rather than as stray text. */
function Readonly({
  label, value, tone,
}: { label: string; value: string; tone?: "money" | "good" | "bad" }) {
  const styles = useStyles();
  return (
    <View style={styles.field}>
      <Text style={styles.fieldLabel}>{label}</Text>
      <View
        style={[
          styles.readonly,
          tone === "money" && styles.readonlyMoney,
          tone === "good" && styles.readonlyGood,
          tone === "bad" && styles.readonlyBad,
        ]}
      >
        <Text
          style={[
            styles.readonlyText,
            tone === "money" && styles.readonlyMoneyText,
            tone === "good" && styles.readonlyGoodText,
            tone === "bad" && styles.readonlyBadText,
          ]}
          numberOfLines={1}
        >
          {value}
        </Text>
      </View>
    </View>
  );
}

function SaleBlockView({
  block: b, index, total, saleType,
  onRemove, onValue, onFarm, onCustomer, onLocate, onAddPhoto, onDropPhoto,
}: {
  block: SaleBlock;
  index: number;
  total: number;
  saleType: SaleType;
  onRemove: () => void;
  onValue: (name: string, v: string) => void;
  onFarm: (v: string) => void;
  onCustomer: (v: string) => void;
  onLocate: () => void;
  onAddPhoto: (kind: PhotoKind, gallery?: boolean) => void;
  onDropPhoto: (kind: PhotoKind, uri: string) => void;
}) {
  const styles = useStyles();
  const { colors } = useTheme();

  // Mirrors BirdSale.save(). Round off is derived, not typed: a lifting is
  // billed to the rupee, the paise fall off the total, and Round Off records
  // what that cost or gained.
  const birds = num(b.values.birds);
  const avg = birds ? (num(b.values.net_weight) / birds).toFixed(2) : "0.00";
  const raw = num(b.values.net_weight) * num(b.values.rate);
  const amount = Math.round(raw);
  const roundOff = amount - raw;

  const located = !!b.values.latitude && !!b.values.longitude;

  return (
    <View>
      {total > 1 ? <Text style={styles.blockCaption}>{`BIRD SALE ${index + 1} OF ${total}`}</Text> : null}

      <Section
        n={1}
        icon="account-multiple"
        title="PARTY & FARM"
        right={
          total > 1 ? (
            <Pressable
              onPress={onRemove}
              style={styles.trash}
              accessibilityRole="button"
              accessibilityLabel={`Remove bird sale ${index + 1}`}
            >
              <AppIcon name="trash-can-outline" size={18} color={colors.danger} />
            </Pressable>
          ) : null
        }
      >
        <Pair>
          <FormControl field={F_DATE} value={b.values.date} error={b.errors.date}
                       onChange={(v) => onValue("date", v)} />
          <FormControl field={F_DOC} value={b.values.doc_no}
                       onChange={(v) => onValue("doc_no", v)} />
        </Pair>

        {saleType === "customer" ? (
          <>
            {/* Paired as the mockup pairs them: what a customer already owes
                belongs beside their name, not a scroll below it — it is read
                at the moment the name is chosen. */}
            <View style={styles.pair}>
              <View style={styles.customerCell}>
                <FormControl field={F_CUSTOMER} value={b.values.customer}
                             error={b.errors.customer} onChange={onCustomer} />
              </View>
              <View style={styles.balanceCell}>
                <Readonly
                  label="Ledger Balance"
                  value={b.balance?.label || "—"}
                  tone={b.balance ? (b.balance.exceeded ? "bad" : "good") : undefined}
                />
              </View>
            </View>
            {b.balance?.note ? <Text style={styles.hint}>{b.balance.note}</Text> : null}
          </>
        ) : (
          // A farmer sale is the farm's own farmer buying back, so there is
          // nothing to pick — and no customer ledger to show against it.
          <Readonly label="Farmer" value={b.farmerName || "Select a farm"} />
        )}

        <Pair>
          <FormControl field={F_FARM} value={b.values.farm} error={b.errors.farm}
                       onChange={onFarm} />
          <FormControl field={batchField(b.batches, !!b.values.farm)} value={b.values.batch}
                       error={b.errors.batch} onChange={(v) => onValue("batch", v)} />
        </Pair>
      </Section>

      <Section n={2} icon="scale" title="SALE DETAILS">
        <Pair>
          <FormControl field={F_BIRDS} value={b.values.birds} error={b.errors.birds}
                       onChange={(v) => onValue("birds", v)} />
          <FormControl field={F_NET} value={b.values.net_weight} error={b.errors.net_weight}
                       onChange={(v) => onValue("net_weight", v)} />
        </Pair>
        <Pair>
          <Readonly label="Avg Weight (Kg)" value={`${avg} (Auto)`} />
          <FormControl field={F_RATE} value={b.values.rate} error={b.errors.rate}
                       onChange={(v) => onValue("rate", v)} />
        </Pair>
        <Pair>
          <Readonly label="Round Off (₹)" value={`${roundOff.toFixed(2)} (Auto)`} />
          <Readonly label="Total Amount (₹)" value={money(amount)} tone="money" />
        </Pair>
      </Section>

      <Section n={3} icon="truck" title="LIFTING & LOGISTICS">
        <FormControl field={F_SUPERVISOR} value={b.values.lifting_supervisor}
                     error={b.errors.lifting_supervisor}
                     onChange={(v) => onValue("lifting_supervisor", v)} />
        <Pair>
          <FormControl field={F_VEHICLE} value={b.values.vehicle} error={b.errors.vehicle}
                       onChange={(v) => onValue("vehicle", v)} />
          <FormControl field={F_DRIVER} value={b.values.driver} error={b.errors.driver}
                       onChange={(v) => onValue("driver", v)} />
        </Pair>

        <Text style={styles.fieldLabel}>GPS Location</Text>
        <Pressable
          style={styles.gpsBox}
          onPress={onLocate}
          disabled={b.gpsBusy}
          accessibilityRole="button"
          accessibilityLabel="Stamp the lifting location"
        >
          <AppIcon name="map-marker" size={18} color={located ? colors.success : colors.textMuted} />
          <Text style={[styles.gpsText, !located && styles.gpsEmpty]} numberOfLines={1}>
            {b.gpsBusy
              ? "Locating…"
              : located
                ? b.place || `${b.values.latitude}, ${b.values.longitude}`
                : "Taken automatically on submit"}
          </Text>
          <View style={[styles.gpsBadge, located && styles.gpsBadgeOn]}>
            <Text style={[styles.gpsBadgeText, located && styles.gpsBadgeTextOn]}>
              {located ? "Auto Detected" : "Tap to detect now"}
            </Text>
            {located ? <AppIcon name="check-circle" size={13} color={colors.success} /> : null}
          </View>
        </Pressable>

        <Text style={[styles.fieldLabel, styles.photoHead]}>Photos</Text>
        <View style={styles.photoRow}>
          {PHOTO_KINDS.map(({ kind, label }) => (
            <PhotoSlot
              key={kind}
              label={label}
              uris={b.photos[kind]}
              onAdd={() => onAddPhoto(kind)}
              onDrop={(u) => onDropPhoto(kind, u)}
            />
          ))}
          <PhotoSlot
            label="Add More"
            uris={b.photos.other}
            addMore
            onAdd={() => onAddPhoto("other", true)}
            onDrop={(u) => onDropPhoto("other", u)}
          />
        </View>
      </Section>

      <Section n={4} icon="note-text-outline" title="REMARKS" note="(Optional)">
        <TextInput
          style={styles.remarks}
          value={b.values.remarks}
          onChangeText={(t) => onValue("remarks", t.slice(0, REMARKS_MAX))}
          placeholder="Add any remarks or lifting notes…"
          placeholderTextColor={colors.textMuted}
          multiline
          maxLength={REMARKS_MAX}
        />
        <Text style={styles.counter}>{`${b.values.remarks.length}/${REMARKS_MAX}`}</Text>
      </Section>
    </View>
  );
}

/** One evidence slot: its shots as thumbnails, plus a tile to add another. */
function PhotoSlot({
  label, uris, onAdd, onDrop, addMore,
}: {
  label: string;
  uris: string[];
  onAdd: () => void;
  onDrop: (uri: string) => void;
  addMore?: boolean;
}) {
  const styles = useStyles();
  const { colors } = useTheme();
  const full = uris.length >= MAX_PER_KIND;

  return (
    <View style={styles.slot}>
      {uris.map((uri) => (
        <View key={uri} style={styles.thumbWrap}>
          <Image source={{ uri }} style={styles.thumb} />
          <Pressable
            style={styles.thumbDrop}
            onPress={() => onDrop(uri)}
            accessibilityRole="button"
            accessibilityLabel={`Remove ${label}`}
          >
            <AppIcon name="close" size={12} color="#fff" />
          </Pressable>
        </View>
      ))}
      {!full && !uris.length ? (
        <Pressable
          style={[styles.tile, addMore && styles.tileDashed]}
          onPress={onAdd}
          accessibilityRole="button"
          accessibilityLabel={label}
        >
          <AppIcon name={addMore ? "plus" : "camera"} size={20} color={colors.textMuted} />
        </Pressable>
      ) : null}
      {!full && uris.length ? (
        <Pressable
          style={styles.addSmall}
          onPress={onAdd}
          accessibilityRole="button"
          accessibilityLabel={`Add another ${label}`}
        >
          <AppIcon name="plus" size={13} color={colors.textMuted} />
        </Pressable>
      ) : null}
      <Text style={styles.slotLabel} numberOfLines={1}>{label}</Text>
    </View>
  );
}

/** Alert.alert as a promise — RN has no confirm(), and the evidence warning
 *  has to know whether the user chose to go ahead. */
function confirm(title: string, message: string): Promise<boolean> {
  return new Promise((resolve) => {
    Alert.alert(title, message, [
      { text: "Go back", style: "cancel", onPress: () => resolve(false) },
      { text: "Save anyway", onPress: () => resolve(true) },
    ]);
  });
}

const useStyles = makeStyles((colors) => ({
  screen: { flex: 1, backgroundColor: colors.bg },
  content: { padding: spacing.md, paddingBottom: spacing.xl },

  formError: {
    ...type.label, color: colors.danger, backgroundColor: colors.dangerLight,
    padding: spacing.md, borderRadius: radius.md, marginBottom: spacing.md,
  },

  // The header is the module's own colour, so the button reads in white on it
  // — in the module colour it was there but invisible.
  registerBtn: {
    flexDirection: "row", alignItems: "center", gap: spacing.xs,
    borderWidth: 1, borderColor: withAlpha(colors.onDark, 0.55), borderRadius: radius.sm,
    paddingHorizontal: spacing.sm, paddingVertical: 5, marginRight: spacing.xs,
  },
  registerText: { ...type.label, color: colors.onDark, fontWeight: "700" },

  card: {
    backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1,
    borderColor: colors.border, padding: spacing.md, marginBottom: spacing.md,
  },
  cardCaption: { ...type.caption, color: colors.textMuted, fontWeight: "700",
                 letterSpacing: 0.6, marginBottom: spacing.sm },
  blockCaption: { ...type.caption, color: colors.textMuted, fontWeight: "800",
                  letterSpacing: 0.8, marginBottom: spacing.xs, marginLeft: 2 },

  radioRow: { flexDirection: "row", gap: spacing.sm },
  radio: {
    flex: 1, flexDirection: "row", alignItems: "center", gap: spacing.sm,
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingVertical: spacing.md, paddingHorizontal: spacing.md,
  },
  radioOn: { borderColor: colors.broiler, backgroundColor: withAlpha(colors.broiler, 0.06) },
  radioLocked: { opacity: 0.55 },
  radioDot: {
    width: 20, height: 20, borderRadius: 10, borderWidth: 2,
    borderColor: colors.border, alignItems: "center", justifyContent: "center",
  },
  radioDotFill: { width: 10, height: 10, borderRadius: 5, backgroundColor: colors.broiler },
  radioText: { ...type.body, color: colors.textMuted, flexShrink: 1 },
  radioTextOn: { color: colors.text, fontWeight: "700" },

  sectionHead: { flexDirection: "row", alignItems: "center", gap: spacing.sm,
                 marginBottom: spacing.md },
  sectionIcon: {
    width: 30, height: 30, borderRadius: 15, backgroundColor: colors.broiler,
    alignItems: "center", justifyContent: "center",
  },
  sectionTitle: { ...type.label, color: colors.text, fontWeight: "800", letterSpacing: 0.4 },
  sectionNote: { ...type.caption, color: colors.textMuted },
  spacer: { flex: 1 },
  trash: {
    borderWidth: 1, borderColor: withAlpha(colors.danger, 0.4), borderRadius: radius.sm,
    padding: 6,
  },

  pair: { flexDirection: "row", gap: spacing.sm, alignItems: "flex-start" },
  pairCell: { flex: 1, minWidth: 0 },
  // The name needs the room; the balance is a short figure.
  customerCell: { flex: 3, minWidth: 0 },
  balanceCell: { flex: 2, minWidth: 0 },

  field: { marginBottom: spacing.lg },
  fieldLabel: { ...type.label, color: colors.text, marginBottom: spacing.xs },
  hint: { ...type.caption, color: colors.textMuted, marginTop: -spacing.md,
          marginBottom: spacing.md },

  readonly: {
    minHeight: 48, justifyContent: "center", borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.md, paddingHorizontal: spacing.md, backgroundColor: colors.surfaceAlt,
  },
  readonlyText: { ...type.body, color: colors.textMuted },
  readonlyMoney: { backgroundColor: withAlpha(colors.broiler, 0.08),
                   borderColor: withAlpha(colors.broiler, 0.35) },
  readonlyMoneyText: { ...type.h3, color: colors.broiler },
  readonlyGood: { backgroundColor: colors.successLight, borderColor: withAlpha(colors.success, 0.3) },
  readonlyGoodText: { color: colors.success, fontWeight: "700" },
  readonlyBad: { backgroundColor: colors.dangerLight, borderColor: withAlpha(colors.danger, 0.3) },
  readonlyBadText: { color: colors.danger, fontWeight: "700" },

  gpsBox: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: spacing.md, paddingVertical: spacing.md, marginBottom: spacing.lg,
  },
  gpsText: { ...type.body, color: colors.text, flex: 1 },
  gpsEmpty: { color: colors.textMuted },
  gpsBadge: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: colors.surfaceAlt, borderRadius: radius.sm,
    paddingHorizontal: spacing.sm, paddingVertical: 5,
  },
  gpsBadgeOn: { backgroundColor: colors.successLight },
  gpsBadgeText: { ...type.caption, color: colors.textMuted, fontWeight: "700" },
  gpsBadgeTextOn: { color: colors.success },

  photoHead: { marginTop: 0 },
  photoRow: { flexDirection: "row", gap: spacing.sm },
  slot: { flex: 1, alignItems: "center", gap: 4 },
  tile: {
    width: "100%", aspectRatio: 1, borderRadius: radius.sm, borderWidth: 1,
    borderColor: colors.border, backgroundColor: colors.surfaceAlt,
    alignItems: "center", justifyContent: "center",
  },
  tileDashed: { borderStyle: "dashed", backgroundColor: "transparent" },
  thumbWrap: { width: "100%", aspectRatio: 1 },
  thumb: { width: "100%", height: "100%", borderRadius: radius.sm },
  thumbDrop: {
    position: "absolute", top: 3, right: 3, width: 20, height: 20, borderRadius: 10,
    backgroundColor: "rgba(0,0,0,0.6)", alignItems: "center", justifyContent: "center",
  },
  addSmall: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    paddingVertical: 2,
  },
  slotLabel: { ...type.caption, color: colors.textMuted, fontSize: 10, textAlign: "center" },

  remarks: {
    minHeight: 84, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    padding: spacing.md, ...type.body, color: colors.text, textAlignVertical: "top",
  },
  counter: { ...type.caption, color: colors.textMuted, textAlign: "right", marginTop: 4 },

  addBlock: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.sm,
    borderWidth: 1, borderStyle: "dashed", borderColor: withAlpha(colors.broiler, 0.5),
    borderRadius: radius.md, paddingVertical: spacing.md,
    backgroundColor: withAlpha(colors.broiler, 0.05), marginBottom: spacing.md,
  },
  addBlockText: { ...type.label, color: colors.broiler, fontWeight: "700" },

  deleteWrap: { marginTop: spacing.sm },

  footer: {
    flexDirection: "row", gap: spacing.sm, padding: spacing.md,
    borderTopWidth: 1, borderTopColor: colors.border, backgroundColor: colors.surface,
  },
  cancelBtn: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: spacing.xs, borderWidth: 1, borderColor: withAlpha(colors.danger, 0.5),
    borderRadius: radius.md, paddingVertical: spacing.md,
  },
  cancelText: { ...type.label, color: colors.danger, fontWeight: "700" },
  submitBtn: {
    flex: 2, flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: spacing.xs, backgroundColor: colors.broiler, borderRadius: radius.md,
    paddingVertical: spacing.md,
  },
  submitBusy: { opacity: 0.6 },
  submitText: { ...type.label, color: "#fff", fontWeight: "800" },
}));
