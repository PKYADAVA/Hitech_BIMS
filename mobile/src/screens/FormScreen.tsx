import { NativeStackScreenProps } from "@react-navigation/native-stack";
import React, { useLayoutEffect, useMemo, useState } from "react";
import { Alert, StyleSheet, Text, View } from "react-native";

import { createResource, deleteResource, updateResource } from "@/api/resources";
import { ApiError, Row } from "@/api/types";
import { FormControl } from "@/components/form";
import { KeyboardAwareScrollView } from "@/components/KeyboardAwareScrollView";
import { Button } from "@/components/ui";
import { RESOURCES } from "@/config/catalog";
import { FORMS } from "@/config/forms";
import { ModuleStackParams } from "@/navigation/types";
import { queryClient } from "@/query/queryClient";
import { usePermissionsStore } from "@/store/permissionsStore";
import { colors, spacing, type } from "@/theme";
import { isEmpty } from "@/utils/format";

type Props = NativeStackScreenProps<ModuleStackParams, "Form">;

export function FormScreen({ route, navigation }: Props) {
  const { resourceKey, mode, row, preset, onDoneGoBack } = route.params;
  const config = RESOURCES[resourceKey];
  const canDelete = usePermissionsStore((s) => s.canAction)(config.module, "delete");
  const schema = FORMS[resourceKey];

  const finish = () =>
    onDoneGoBack ? navigation.goBack() : navigation.navigate("List", { resourceKey });

  const initial = useMemo(() => {
    const v: Record<string, string> = {};
    for (const f of schema.fields) {
      const raw = row?.[f.name];
      v[f.name] =
        f.type === "boolean"
          ? raw === true || raw === "true"
            ? "true"
            : "false"
          : isEmpty(raw)
          ? ""
          : String(raw);
    }
    return v;
  }, [schema, row]);

  const [values, setValues] = useState<Record<string, string>>(initial);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useLayoutEffect(() => {
    navigation.setOptions({ title: `${mode === "create" ? "New" : "Edit"} ${config.singular}` });
  }, [navigation, mode, config.singular]);

  const set = (name: string) => (val: string) =>
    setValues((prev) => ({ ...prev, [name]: val }));

  const buildPayload = () => {
    const payload: Record<string, unknown> = { ...(preset ?? {}) };
    for (const f of schema.fields) {
      const val = values[f.name];
      if (f.type === "boolean") payload[f.name] = val === "true";
      else if (!isEmpty(val)) payload[f.name] = val;
    }
    return payload;
  };

  const validate = (): boolean => {
    const errs: Record<string, string> = {};
    for (const f of schema.fields) {
      if (f.required && isEmpty(values[f.name])) errs[f.name] = "Required";
    }
    setErrors(errs);
    return Object.keys(errs).length === 0;
  };

  const onSave = async () => {
    setFormError(null);
    if (!validate()) return;
    setSaving(true);
    try {
      if (mode === "create") await createResource(config.path, buildPayload());
      else await updateResource(config.path, (row as Row).id, buildPayload());
      queryClient.invalidateQueries({ queryKey: ["list", config.path] });
      finish();
    } catch (e) {
      handleApiError(e);
    } finally {
      setSaving(false);
    }
  };

  const onDelete = () => {
    Alert.alert("Delete", `Delete this ${config.singular.toLowerCase()}?`, [
      { text: "Cancel", style: "cancel" },
      {
        text: "Delete",
        style: "destructive",
        onPress: async () => {
          try {
            await deleteResource(config.path, (row as Row).id);
            queryClient.invalidateQueries({ queryKey: ["list", config.path] });
            navigation.navigate("List", { resourceKey });
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

        {schema.fields.map((f) => (
          <FormControl
            key={f.name}
            field={f}
            value={values[f.name] ?? ""}
            fallbackLabel={row ? (row[`${f.name}_label`] as string) : undefined}
            error={errors[f.name]}
            onChange={set(f.name)}
          />
        ))}

        <Button
          title={mode === "create" ? "Create" : "Save changes"}
          onPress={onSave}
          loading={saving}
        />
        {mode === "edit" && canDelete ? (
          <View style={{ marginTop: spacing.sm }}>
            <Button title="Delete" variant="danger" onPress={onDelete} />
          </View>
        ) : null}
        <View style={{ height: spacing.xxl }} />
    </KeyboardAwareScrollView>
  );
}

const styles = StyleSheet.create({
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
});
