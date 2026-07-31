import { NativeStackScreenProps } from "@react-navigation/native-stack";
import React, { useLayoutEffect, useMemo, useState } from "react";
import { Alert, Text, View } from "react-native";

import { createResource, deleteResource, updateResource } from "@/api/resources";
import { ApiError, Row } from "@/api/types";
import { appendImage, isLocalCapture } from "@/capture";
import { FormControl } from "@/components/form";
import { KeyboardAwareScrollView } from "@/components/KeyboardAwareScrollView";
import { Button } from "@/components/ui";
import { RESOURCES } from "@/config/catalog";
import { FORMS } from "@/config/forms";
import { ModuleStackParams } from "@/navigation/types";
import { queryClient } from "@/query/queryClient";
import { usePermissionsStore } from "@/store/permissionsStore";
import { colors, makeStyles, spacing, type } from "@/theme";
import { isEmpty } from "@/utils/format";

type Props = NativeStackScreenProps<ModuleStackParams, "Form">;

export function FormScreen({ route, navigation }: Props) {
  const { resourceKey, mode, row, preset, onDoneGoBack } = route.params;
  const config = RESOURCES[resourceKey];
  const canDelete = usePermissionsStore((s) => s.canAction)(config.module, "delete");
  const schema = FORMS[resourceKey];
  const styles = useStyles();

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
      // A geo control's coordinates are API fields with no control of their
      // own, so seed them here or an edit would drop the saved position.
      for (const coord of f.geoFields ?? []) {
        v[coord] = isEmpty(row?.[coord]) ? "" : String(row?.[coord]);
      }
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

  const set = (name: string) => (val: string) => {
    setValues((prev) => {
      const next = { ...prev, [name]: val };
      // Async auto-fill (e.g. Farm → active Batch + Age), on user change only.
      const af = schema.autofill;
      if (af && af.on === name) {
        af.run(val, next)
          .then((patch) => setValues((cur) => ({ ...cur, ...patch })))
          .catch(() => {});
      }
      return next;
    });
  };

  // Client-side derived values (amounts, totals, derived quantities) — recomputed
  // each render from the current inputs, mirroring the web forms' calc functions.
  const derived = useMemo(
    () => (schema.compute ? schema.compute(values) : {}),
    [schema, values]
  );
  // What each field shows: a computed field wins over any stored value.
  const shown = (name: string): string => derived[name] ?? values[name] ?? "";

  const buildPayload = () => {
    const payload: Record<string, unknown> = { ...(preset ?? {}) };
    for (const f of schema.fields) {
      // A geo control holds no value itself — it persists the coordinate pair
      // it writes, which are real API fields but never rendered on their own.
      if (f.type === "geo") {
        for (const coord of f.geoFields ?? []) {
          if (!isEmpty(values[coord])) payload[coord] = values[coord];
        }
        continue;
      }
      if (f.transient) continue; // display-only helper, never persisted
      const val = derived[f.name] ?? values[f.name];
      if (f.type === "boolean") payload[f.name] = val === "true";
      else if (!isEmpty(val)) payload[f.name] = val;
    }
    return payload;
  };

  /** Photo fields holding a freshly captured file — these force a multipart send. */
  const pendingPhotos = () =>
    schema.fields.filter(
      (f) => f.type === "photo" && !f.transient && isLocalCapture(values[f.name] ?? "")
    );

  /**
   * A JSON object normally; FormData when a photo was captured, since a file
   * can't be expressed in JSON. An untouched photo field is left out entirely
   * so an edit that doesn't retake the shot keeps the stored image — sending
   * its URL back as a string would make Django try to store the URL as a file.
   */
  const buildBody = async (): Promise<Record<string, unknown> | FormData> => {
    const photos = pendingPhotos();
    const payload = buildPayload();
    if (!photos.length) {
      for (const f of schema.fields) {
        if (f.type === "photo") delete payload[f.name];
      }
      return payload;
    }

    const form = new FormData();
    const photoNames = new Set(photos.map((f) => f.name));
    for (const [k, v] of Object.entries(payload)) {
      if (schema.fields.some((f) => f.type === "photo" && f.name === k)) continue;
      form.append(k, typeof v === "boolean" ? String(v) : String(v));
    }
    for (const f of photoNames) {
      await appendImage(form, f, values[f]);
    }
    return form;
  };

  const validate = (): boolean => {
    const errs: Record<string, string> = {};
    for (const f of schema.fields) {
      if (f.readOnly) continue; // computed — nothing to enter
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
      const body = await buildBody();
      if (mode === "create") await createResource(config.path, body);
      else await updateResource(config.path, (row as Row).id, body);
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
            value={shown(f.name)}
            values={values}
            fallbackLabel={row ? (row[`${f.name}_label`] as string) : undefined}
            error={errors[f.name]}
            onChange={set(f.name)}
            onPatch={(patch) => setValues((cur) => ({ ...cur, ...patch }))}
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
}));
