import { NativeStackScreenProps } from "@react-navigation/native-stack";
import React, { useLayoutEffect, useMemo, useState } from "react";
import { Alert, Pressable, Text, View } from "react-native";

import { http } from "@/api/client";
import { createResource, deleteResource, updateResource } from "@/api/resources";
import { ApiError, Envelope, Row } from "@/api/types";
import { FormControl } from "@/components/form";
import { KeyboardAwareScrollView } from "@/components/KeyboardAwareScrollView";
import { Button } from "@/components/ui";
import { FormField } from "@/config/forms";
import { ModuleStackParams } from "@/navigation/types";
import { queryClient } from "@/query/queryClient";
import { makeStyles, radius, shadow, spacing, type } from "@/theme";
import { isEmpty } from "@/utils/format";

type Props = NativeStackScreenProps<ModuleStackParams, "BirdSaleForm">;

const PATH = "/broiler/bird-sales/";
const RESOURCE_KEY = "broiler-bird-sales";

type SaleType = "customer" | "farmer";

// Field configs reused by the shared FormControl (same pickers as the web form).
const F_CUSTOMER: FormField = {
  name: "customer", label: "Customer", type: "select",
  optionsPath: "/customers/", optionLabelKeys: ["name", "code"], required: true,
};
const F_FARM: FormField = {
  name: "farm", label: "Farm", type: "select",
  optionsPath: "/broiler/farms/", optionLabelKeys: ["farm_name", "farm_code"], required: true,
};
const F_SUPERVISOR: FormField = {
  name: "lifting_supervisor", label: "Supervisor", type: "select",
  optionsPath: "/broiler/supervisors/", optionLabelKeys: ["name"],
};
const F_DATE: FormField = { name: "date", label: "Date", type: "date", required: true };
const F_DOC: FormField = { name: "doc_no", label: "Doc No.", type: "text" };
const F_BIRDS: FormField = { name: "birds", label: "Birds", type: "number" };
const F_NET: FormField = { name: "net_weight", label: "Net Weight (Kg)", type: "decimal", required: true };
const F_RATE: FormField = { name: "rate", label: "Rate (per Kg)", type: "decimal", required: true };
const F_ROUND: FormField = { name: "round_off", label: "Round Off", type: "decimal" };
const F_VEHICLE: FormField = { name: "vehicle", label: "Vehicle", type: "text" };
const F_DRIVER: FormField = { name: "driver", label: "Driver", type: "text" };
const F_REMARKS: FormField = { name: "remarks", label: "Remarks", type: "text" };

const num = (v: string) => Number(v) || 0;

export function BirdSaleFormScreen({ route, navigation }: Props) {
  const styles = useStyles();
  const { mode, row } = route.params;

  const [saleType, setSaleType] = useState<SaleType>(
    (row?.sale_type as SaleType) || "customer"
  );
  const [values, setValues] = useState<Record<string, string>>(() => ({
    date: (row?.date as string) ?? new Date().toISOString().slice(0, 10),
    doc_no: str(row?.doc_no),
    customer: idStr(row?.customer),
    farm: idStr(row?.farm),
    birds: str(row?.birds),
    net_weight: str(row?.net_weight),
    rate: str(row?.rate),
    round_off: str(row?.round_off),
    lifting_supervisor: idStr(row?.lifting_supervisor),
    vehicle: str(row?.vehicle),
    driver: str(row?.driver),
    remarks: str(row?.remarks),
  }));
  // Farm-derived, read-only display (set by the lookup, exactly like the web).
  const [batchName, setBatchName] = useState<string>(str(row?.batch_label));
  const [farmerName, setFarmerName] = useState<string>(str(row?.farmer_label));

  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useLayoutEffect(() => {
    navigation.setOptions({ title: mode === "create" ? "New Bird Sale" : "Edit Bird Sale" });
  }, [navigation, mode]);

  // Computed, non-editable — mirror BirdSale.save(): avg = net/birds, amount = net*rate + roundoff.
  const avgWeight = useMemo(() => {
    const birds = num(values.birds);
    return birds ? (num(values.net_weight) / birds).toFixed(2) : "0.00";
  }, [values.birds, values.net_weight]);
  const amount = useMemo(
    () => (num(values.net_weight) * num(values.rate) + num(values.round_off)).toFixed(2),
    [values.net_weight, values.rate, values.round_off]
  );

  const set = (name: string) => (val: string) =>
    setValues((prev) => ({ ...prev, [name]: val }));

  const onFarmChange = async (farmId: string) => {
    setValues((prev) => ({ ...prev, farm: farmId }));
    if (!farmId) {
      setBatchName("");
      setFarmerName("");
      return;
    }
    try {
      const resp = await http.get<Envelope<{ batch_name: string; farmer_name: string }>>(
        "/broiler/farm-lookup",
        { params: { farm: farmId } }
      );
      setBatchName(resp.data.data.batch_name || "No active batch");
      setFarmerName(resp.data.data.farmer_name || "No farmer on record for this farm");
    } catch {
      setBatchName("");
      setFarmerName("");
    }
  };

  const validate = (): boolean => {
    const errs: Record<string, string> = {};
    if (isEmpty(values.date)) errs.date = "Required";
    if (isEmpty(values.farm)) errs.farm = "Required";
    if (isEmpty(values.net_weight)) errs.net_weight = "Required";
    if (isEmpty(values.rate)) errs.rate = "Required";
    if (saleType === "customer" && isEmpty(values.customer)) errs.customer = "Required";
    setErrors(errs);
    return Object.keys(errs).length === 0;
  };

  const buildPayload = () => {
    const payload: Record<string, unknown> = {
      date: values.date,
      sale_type: saleType,
      doc_no: values.doc_no || "",
      farm: values.farm,
      birds: values.birds || "0",
      net_weight: values.net_weight || "0",
      rate: values.rate || "0",
      round_off: values.round_off || "0",
      lifting_supervisor: values.lifting_supervisor || null,
      vehicle: values.vehicle || "",
      driver: values.driver || "",
      remarks: values.remarks || "",
      // batch + farmer are derived server-side from the farm; avg/amount computed on save.
      customer: saleType === "customer" ? values.customer : null,
    };
    return payload;
  };

  const onSave = async () => {
    setFormError(null);
    if (!validate()) return;
    setSaving(true);
    try {
      if (mode === "create") await createResource(PATH, buildPayload());
      else await updateResource(PATH, (row as Row).id, buildPayload());
      queryClient.invalidateQueries({ queryKey: ["list", PATH] });
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
      setErrors(fieldErrs);
      setFormError(e.message || "Please fix the errors and try again.");
    } else {
      setFormError((e as Error)?.message ?? "Something went wrong.");
    }
  };

  return (
    <KeyboardAwareScrollView style={styles.screen} contentContainerStyle={styles.content}>
        {formError ? <Text style={styles.formError}>{formError}</Text> : null}

        {/* Sale type toggle */}
        <View style={styles.toggleRow}>
          {(["customer", "farmer"] as SaleType[]).map((t) => {
            const on = saleType === t;
            return (
              <Pressable
                key={t}
                onPress={() => setSaleType(t)}
                style={[styles.toggle, on && styles.toggleOn]}
              >
                <Text style={[styles.toggleText, on && styles.toggleTextOn]}>
                  {t === "customer" ? "Customer Sale" : "Farmer Sale"}
                </Text>
              </Pressable>
            );
          })}
        </View>

        <FormControl field={F_DATE} value={values.date} error={errors.date} onChange={set("date")} />

        {saleType === "customer" ? (
          <FormControl
            field={F_CUSTOMER}
            value={values.customer}
            fallbackLabel={str(row?.customer_label)}
            error={errors.customer}
            onChange={set("customer")}
          />
        ) : (
          <ReadonlyField label="Farmer" value={farmerName || "Select a Farm"} />
        )}

        <FormControl field={F_DOC} value={values.doc_no} onChange={set("doc_no")} />
        <FormControl
          field={F_FARM}
          value={values.farm}
          fallbackLabel={str(row?.farm_label)}
          error={errors.farm}
          onChange={onFarmChange}
        />
        <ReadonlyField label="Batch" value={batchName || "—"} />
        <FormControl field={F_BIRDS} value={values.birds} onChange={set("birds")} />
        <FormControl field={F_NET} value={values.net_weight} error={errors.net_weight} onChange={set("net_weight")} />
        <ReadonlyField label="Avg Weight (Kg)" value={avgWeight} />
        <FormControl field={F_RATE} value={values.rate} error={errors.rate} onChange={set("rate")} />
        <FormControl field={F_ROUND} value={values.round_off} onChange={set("round_off")} />
        <ReadonlyField label="Amount" value={amount} emphasize />
        <FormControl
          field={F_SUPERVISOR}
          value={values.lifting_supervisor}
          fallbackLabel={str(row?.lifting_supervisor_label)}
          onChange={set("lifting_supervisor")}
        />
        <FormControl field={F_VEHICLE} value={values.vehicle} onChange={set("vehicle")} />
        <FormControl field={F_DRIVER} value={values.driver} onChange={set("driver")} />
        <FormControl field={F_REMARKS} value={values.remarks} onChange={set("remarks")} />

        <Button title={mode === "create" ? "Create" : "Save changes"} onPress={onSave} loading={saving} />
        {mode === "edit" ? (
          <View style={{ marginTop: spacing.sm }}>
            <Button title="Delete" variant="danger" onPress={onDelete} />
          </View>
        ) : null}
        <View style={{ height: spacing.xxl }} />
    </KeyboardAwareScrollView>
  );
}

/** A non-editable, computed/derived value shown in the same shell as inputs. */
function ReadonlyField({ label, value, emphasize }: { label: string; value: string; emphasize?: boolean }) {
  const styles = useStyles();
  return (
    <View style={styles.field}>
      <Text style={styles.label}>{label}</Text>
      <View style={[styles.readonly, emphasize && styles.readonlyStrong]}>
        <Text style={[styles.readonlyText, emphasize && styles.readonlyTextStrong]}>{value}</Text>
      </View>
    </View>
  );
}

const str = (v: unknown) => (isEmpty(v) ? "" : String(v));
const idStr = (v: unknown) => (v === null || v === undefined || v === "" ? "" : String(v));

const useStyles = makeStyles((colors) => ({
  screen: { flex: 1, backgroundColor: colors.bg },
  content: { padding: spacing.md },
  formError: {
    ...type.label,
    color: colors.danger,
    backgroundColor: colors.dangerLight,
    padding: spacing.md,
    borderRadius: 12,
    marginBottom: spacing.md,
  },

  toggleRow: {
    flexDirection: "row",
    gap: spacing.sm,
    backgroundColor: colors.surfaceAlt,
    padding: 4,
    borderRadius: radius.md,
    marginBottom: spacing.lg,
  },
  toggle: { flex: 1, paddingVertical: spacing.sm, borderRadius: radius.sm, alignItems: "center" },
  toggleOn: { backgroundColor: colors.surface, ...shadow(1) },
  toggleText: { ...type.label, color: colors.textMuted },
  toggleTextOn: { color: colors.tint, fontWeight: "800" },

  field: { marginBottom: spacing.lg },
  label: { ...type.label, color: colors.text, marginBottom: spacing.xs },
  readonly: {
    minHeight: 50,
    justifyContent: "center",
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    backgroundColor: colors.surfaceAlt,
  },
  readonlyStrong: { backgroundColor: colors.primaryLight, borderColor: colors.primaryLight },
  readonlyText: { ...type.body, color: colors.textMuted },
  readonlyTextStrong: { ...type.h3, color: colors.tint },
}));
