import { NativeStackScreenProps } from "@react-navigation/native-stack";
import React, { useEffect, useLayoutEffect, useMemo, useState } from "react";
import { Alert, Text, View } from "react-native";

import { createResource, deleteResource, updateResource } from "@/api/resources";
import { ApiError, Row } from "@/api/types";
import { appendImage, isLocalCapture } from "@/capture";
import { FormControl } from "@/components/form";
import { KeyboardAwareScrollView } from "@/components/KeyboardAwareScrollView";
import { Button } from "@/components/ui";
import { RESOURCES } from "@/config/catalog";
import { FORMS } from "@/config/forms";
import { Hint } from "@/domain/dailyEntry";
import { ModuleStackParams } from "@/navigation/types";
import { queryClient } from "@/query/queryClient";
import { usePermissionsStore } from "@/store/permissionsStore";
import { colors, makeStyles, spacing, type } from "@/theme";
import { isEmpty } from "@/utils/format";

type Props = NativeStackScreenProps<ModuleStackParams, "Form">;

export function FormScreen({ route, navigation }: Props) {
  const { resourceKey, mode, row, preset, onDoneGoBack } = route.params;
  const config = RESOURCES[resourceKey];
  const canDelete = usePermissionsStore((s) => s.canResource)(config.key, config.module, "delete");
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

  // Server context behind the advisory hints (breed standards, feed phase, live
  // birds). Reloaded only when one of the declared trigger fields changes, so
  // typing a quantity re-advises instantly off data already in hand.
  const [ctx, setCtx] = useState<unknown>(null);
  const ctxKey = (schema.context?.on ?? []).map((n) => values[n] ?? "").join("|");
  useEffect(() => {
    const cfg = schema.context;
    if (!cfg) return;
    let cancelled = false;
    cfg
      .load(values)
      .then((c) => {
        if (!cancelled) setCtx(c);
      })
      // Advisories are a bonus, never a blocker: if the lookup fails the form
      // stays fully usable, just without hints.
      .catch(() => {
        if (!cancelled) setCtx(null);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ctxKey, schema]);

  // Client-side derived values (amounts, totals, derived quantities) — recomputed
  // each render from the current inputs, mirroring the web forms' calc functions.
  const derived = useMemo(
    () => (schema.compute ? schema.compute(values) : {}),
    [schema, values]
  );

  const advice = useMemo(
    () => (schema.advise ? schema.advise(ctx, values) : null),
    [schema, ctx, values]
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
    // Advisory issues (wrong feed for the age, feed over standard, weight off
    // the breed curve) are confirmed, not blocked — the person in the shed
    // knows why a day looks unusual, and refusing the save would just lose it.
    if (advice?.issues.length) {
      const proceed = await new Promise<boolean>((resolve) =>
        Alert.alert(
          "Check before saving",
          `${advice.issues.map((i) => `• ${i}`).join("\n")}\n\nSave anyway?`,
          [
            { text: "Go back", style: "cancel", onPress: () => resolve(false) },
            { text: "Save anyway", onPress: () => resolve(true) },
          ],
          { cancelable: false }
        )
      );
      if (!proceed) return;
    }
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
          <View key={f.name}>
            <FormControl
              field={f}
              value={shown(f.name)}
              values={values}
              fallbackLabel={row ? (row[`${f.name}_label`] as string) : undefined}
              error={errors[f.name]}
              onChange={set(f.name)}
              onPatch={(patch) => setValues((cur) => ({ ...cur, ...patch }))}
            />
            {advice?.fieldHints[f.name] ? (
              <HintLine hint={advice.fieldHints[f.name]} />
            ) : null}
          </View>
        ))}

        {advice && (advice.notes.length > 0 || advice.statusLabel) ? (
          <View style={styles.adviceCard}>
            {advice.statusLabel ? (
              <Text style={[styles.statusPill, styles[`pill_${advice.status}`]]}>
                {advice.statusLabel}
              </Text>
            ) : null}
            {advice.notes.map((n, i) => (
              <HintLine key={i} hint={n} />
            ))}
          </View>
        ) : null}

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

/** One advisory line, coloured by tone. */
function HintLine({ hint }: { hint: Hint }) {
  const styles = useStyles();
  return <Text style={[styles.hint, styles[`hint_${hint.tone}`]]}>{hint.text}</Text>;
}

const useStyles = makeStyles((colors) => ({
  screen: { flex: 1, backgroundColor: colors.bg },
  content: { padding: spacing.md },
  hint: { ...type.label, marginTop: -spacing.xs, marginBottom: spacing.sm },
  hint_ok: { color: colors.success },
  hint_warn: { color: colors.warning },
  hint_bad: { color: colors.danger },
  hint_info: { color: colors.textMuted },
  adviceCard: {
    backgroundColor: colors.surfaceAlt,
    borderRadius: 12,
    padding: spacing.md,
    marginBottom: spacing.md,
    gap: spacing.xs,
  },
  statusPill: {
    ...type.label,
    alignSelf: "flex-start",
    overflow: "hidden",
    borderRadius: 999,
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    marginBottom: spacing.xs,
  },
  pill_ok: { backgroundColor: colors.successLight, color: colors.success },
  pill_near: { backgroundColor: colors.warningLight, color: colors.warning },
  pill_warn: { backgroundColor: colors.dangerLight, color: colors.danger },
  formError: {
    ...type.label,
    color: colors.danger,
    backgroundColor: colors.dangerLight,
    padding: spacing.md,
    borderRadius: 12,
    marginBottom: spacing.md,
  },
}));
