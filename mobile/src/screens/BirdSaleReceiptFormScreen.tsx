import { NativeStackScreenProps } from "@react-navigation/native-stack";
import React, { useLayoutEffect, useState } from "react";
import { Alert, Pressable, Text, View } from "react-native";

import { createResource, deleteResource, updateResource } from "@/api/resources";
import { ApiError, Row } from "@/api/types";
import { FormControl } from "@/components/form";
import { KeyboardAwareScrollView } from "@/components/KeyboardAwareScrollView";
import { Button } from "@/components/ui";
import { FormField } from "@/config/forms";
import { ModuleStackParams } from "@/navigation/types";
import { queryClient } from "@/query/queryClient";
import { makeStyles, radius, shadow, spacing, type } from "@/theme";
import { isEmpty } from "@/utils/format";

type Props = NativeStackScreenProps<ModuleStackParams, "BirdSaleReceiptForm">;

const PATH = "/broiler/bird-sale-receipts/";
const RESOURCE_KEY = "broiler-sale-receipts";

type SaleType = "customer" | "farmer";

// Same pickers the web Receipt form uses.
const F_DATE: FormField = { name: "date", label: "Date", type: "date", required: true };
const F_LOCATION: FormField = {
  name: "location", label: "Location", type: "select",
  optionsPath: "/warehouses/", optionLabelKeys: ["name", "code"], required: true,
};
const F_CUSTOMER: FormField = {
  name: "customer", label: "Customer", type: "select",
  optionsPath: "/customers/", optionLabelKeys: ["name", "code"], required: true,
};
const F_FARMER: FormField = {
  name: "farmer", label: "Farmer", type: "select",
  optionsPath: "/broiler/farmers/", optionLabelKeys: ["farmer_name"], required: true,
};
const F_MODE: FormField = { name: "mode", label: "Mode", type: "text" };
const F_ACCOUNT: FormField = {
  name: "receipt_account", label: "Receipt Account", type: "select",
  optionsPath: "/accounts/", optionLabelKeys: ["description", "code"], required: true,
};
const F_AMOUNT: FormField = { name: "amount", label: "Amount", type: "decimal", required: true };
const F_REF: FormField = { name: "reference_no", label: "Reference No.", type: "text" };
const F_REMARKS: FormField = { name: "remarks", label: "Remarks", type: "text" };

const str = (v: unknown) => (isEmpty(v) ? "" : String(v));
const idStr = (v: unknown) => (v === null || v === undefined || v === "" ? "" : String(v));

export function BirdSaleReceiptFormScreen({ route, navigation }: Props) {
  const styles = useStyles();
  const { mode, row } = route.params;

  const [saleType, setSaleType] = useState<SaleType>((row?.sale_type as SaleType) || "customer");
  const [values, setValues] = useState<Record<string, string>>(() => ({
    date: (row?.date as string) ?? new Date().toISOString().slice(0, 10),
    location: idStr(row?.location),
    customer: idStr(row?.customer),
    farmer: idStr(row?.farmer),
    mode: str(row?.mode) || "Cash",
    receipt_account: idStr(row?.receipt_account),
    amount: str(row?.amount),
    reference_no: str(row?.reference_no),
    remarks: str(row?.remarks),
  }));

  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useLayoutEffect(() => {
    navigation.setOptions({ title: mode === "create" ? "New Receipt" : "Edit Receipt" });
  }, [navigation, mode]);

  const set = (name: string) => (val: string) =>
    setValues((prev) => ({ ...prev, [name]: val }));

  const validate = (): boolean => {
    const errs: Record<string, string> = {};
    if (isEmpty(values.date)) errs.date = "Required";
    if (isEmpty(values.location)) errs.location = "Required";
    if (isEmpty(values.receipt_account)) errs.receipt_account = "Required";
    if (isEmpty(values.amount)) errs.amount = "Required";
    if (saleType === "customer" && isEmpty(values.customer)) errs.customer = "Required";
    if (saleType === "farmer" && isEmpty(values.farmer)) errs.farmer = "Required";
    setErrors(errs);
    return Object.keys(errs).length === 0;
  };

  const buildPayload = () => ({
    date: values.date,
    sale_type: saleType,
    location: values.location,
    customer: saleType === "customer" ? values.customer : null,
    farmer: saleType === "farmer" ? values.farmer : null,
    mode: values.mode || "Cash",
    receipt_account: values.receipt_account,
    amount: values.amount || "0",
    reference_no: values.reference_no || "",
    remarks: values.remarks || "",
  });

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
    Alert.alert("Delete", "Delete this receipt?", [
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

      {/* Sale type toggle — Customer / Farmer receipt */}
      <View style={styles.toggleRow}>
        {(["customer", "farmer"] as SaleType[]).map((t) => {
          const on = saleType === t;
          return (
            <Pressable key={t} onPress={() => setSaleType(t)} style={[styles.toggle, on && styles.toggleOn]}>
              <Text style={[styles.toggleText, on && styles.toggleTextOn]}>
                {t === "customer" ? "Customer" : "Farmer"}
              </Text>
            </Pressable>
          );
        })}
      </View>

      <FormControl field={F_DATE} value={values.date} error={errors.date} onChange={set("date")} />
      <FormControl
        field={F_LOCATION}
        value={values.location}
        fallbackLabel={str(row?.location_label)}
        error={errors.location}
        onChange={set("location")}
      />

      {saleType === "customer" ? (
        <FormControl
          field={F_CUSTOMER}
          value={values.customer}
          fallbackLabel={str(row?.customer_label)}
          error={errors.customer}
          onChange={set("customer")}
        />
      ) : (
        <FormControl
          field={F_FARMER}
          value={values.farmer}
          fallbackLabel={str(row?.farmer_label)}
          error={errors.farmer}
          onChange={set("farmer")}
        />
      )}

      <FormControl field={F_MODE} value={values.mode} onChange={set("mode")} />
      <FormControl
        field={F_ACCOUNT}
        value={values.receipt_account}
        fallbackLabel={str(row?.receipt_account_label)}
        error={errors.receipt_account}
        onChange={set("receipt_account")}
      />
      <FormControl field={F_AMOUNT} value={values.amount} error={errors.amount} onChange={set("amount")} />
      <FormControl field={F_REF} value={values.reference_no} onChange={set("reference_no")} />
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
}));
