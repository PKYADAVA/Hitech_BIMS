import { NativeStackScreenProps } from "@react-navigation/native-stack";
import React, { useEffect, useLayoutEffect, useMemo, useState } from "react";
import { Alert, Pressable, Text, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { loadDocument } from "@/api/documents";
import { writeThrough } from "@/net/writeThrough";
import { farmBatches } from "@/api/lookups";
import { ApiError } from "@/api/types";
import { AppIcon, IconName } from "@/components/AppIcon";
import { FormControl } from "@/components/form";
import { KeyboardAwareScrollView } from "@/components/KeyboardAwareScrollView";
import { Button, Card, Loading } from "@/components/ui";
import { RESOURCES } from "@/config/catalog";
import {
  DOCUMENTS,
  DocConfig,
  DocField,
  DocSection,
  FARM_OPTIONS_PATH,
  WAREHOUSE_OPTIONS_PATH,
} from "@/config/documents";
import { FormField } from "@/config/forms";
import { ModuleStackParams } from "@/navigation/types";
import { queryClient } from "@/query/queryClient";
import { usePickerOptions } from "@/query/usePickerOptions";
import { makeStyles, radius, spacing, type, useTheme } from "@/theme";
import { isEmpty } from "@/utils/format";
import { confirm, notify } from "@/ui/confirm";

type Props = NativeStackScreenProps<ModuleStackParams, "DocumentForm">;
type Dict = Record<string, string>;

/** Map a plain DocField (text/date/number/decimal/select) to a FormField. */
const asFormField = (f: DocField): FormField => ({
  name: f.name,
  label: f.label,
  type: f.type as FormField["type"],
  required: f.required,
  optionsPath: f.optionsPath,
  optionLabelKeys: f.optionLabelKeys,
  placeholder: f.placeholder,
});

/**
 * Lay a field list out, pairing neighbours marked `half`.
 *
 * A date beside a document number, a UOM beside a stock figure: short fields
 * read as a pair and stacking them turns a six-line card into a twelve-line
 * one. Anything not marked `half`, and an odd one at the end, takes the full
 * width on its own.
 */
function FieldRows({
  fields,
  values,
  set,
  setMany,
  dynamic,
  rowIndex,
}: {
  fields: DocField[];
  values: Dict;
  set: (key: string, val: string) => void;
  setMany?: (patch: Dict) => void;
  /** Options for pickers whose choices depend on another field, keyed
   *  `<rowIndex>:<field>`. Absent for the header, which has none. */
  dynamic?: Record<string, { value: string; label: string }[]>;
  rowIndex?: number;
}) {
  const styles = useStyles();
  const opts = (f: DocField) =>
    f.dynamicOptions && dynamic ? (dynamic[`${rowIndex}:${f.name}`] ?? []) : undefined;
  const out: React.ReactNode[] = [];
  for (let i = 0; i < fields.length; i += 1) {
    const f = fields[i];
    const next = fields[i + 1];
    if (f.half && next?.half) {
      out.push(
        <View key={f.name} style={styles.pair}>
          <View style={styles.pairHalf}>
            <DocFieldControl field={f} values={values} set={set} setMany={setMany} dynamic={opts(f)} />
          </View>
          <View style={styles.pairHalf}>
            <DocFieldControl field={next} values={values} set={set} setMany={setMany} dynamic={opts(next)} />
          </View>
        </View>
      );
      i += 1;
      continue;
    }
    out.push(<DocFieldControl key={f.name} field={f} values={values} set={set} setMany={setMany} dynamic={opts(f)} />);
  }
  return <>{out}</>;
}

/** One grouped Warehouse/Farm picker (+ batch when a farm), as the ERP has. */
function LocationControl({
  field,
  values,
  set,
  setMany,
}: {
  field: DocField;
  values: Dict;
  set: (key: string, val: string) => void;
  /** All three of a location's values as one edit — see setItemKeys. */
  setMany?: (patch: Dict) => void;
}) {
  const { colors } = useTheme();
  const styles = useStyles();
  const idKey = `${field.name}_id`;
  const typeKey = `${field.name}_type`;
  const batchKey = `${field.name}_batch`;
  const type = values[typeKey] || "warehouse";
  const onFarm = type === "farm";

  // One list of both kinds, the way the ERP's single dropdown groups Warehouse
  // and Farm under one control — rather than making the user first say which
  // kind it is and then pick. Same "type:id" encoding the web form posts.
  const warehouses = usePickerOptions(WAREHOUSE_OPTIONS_PATH, ["name", "code"]);
  const farms = usePickerOptions(field.allowFarm ? FARM_OPTIONS_PATH : undefined,
                                 ["farm_name", "farm_code"]);
  // The chosen farm's own flocks. The whole batch master was offered here, so
  // a transfer to one farm listed every other farm's batches beside its own —
  // and picking one attached the movement to a flock somewhere else entirely.
  const [batches, setBatches] = useState<{ value: string; label: string }[]>([]);
  const farmId = onFarm ? values[idKey] : "";
  useEffect(() => {
    if (!farmId) { setBatches([]); return; }
    let live = true;
    farmBatches(farmId)
      .then((rows) => {
        if (!live) return;
        setBatches(rows.map((b) => ({
          value: String(b.id),
          // Which flock is running now is the one thing that tells them apart.
          label: b.is_active ? `${b.batch_name} (Active)` : b.batch_name,
        })));
      })
      .catch(() => { if (live) setBatches([]); });
    return () => { live = false; };
  }, [farmId]);

  const options = useMemo(() => {
    const w = warehouses.options.map((o) => ({
      value: `warehouse:${o.value}`, label: `Warehouse · ${o.label}`,
    }));
    const f = farms.options.map((o) => ({
      value: `farm:${o.value}`, label: `Farm · ${o.label}`,
    }));
    return field.allowFarm ? [...w, ...f] : w;
  }, [warehouses.options, farms.options, field.allowFarm]);

  const selected = values[idKey] ? `${type}:${values[idKey]}` : "";

  return (
    <View style={styles.locBlock}>
      <FormControl
        field={{
          name: idKey,
          label: field.label,
          type: "select",
          options,
          required: field.required,
          placeholder: field.placeholder,
        }}
        value={selected}
        onChange={(v) => {
          const [kind, id] = v.split(":");
          // One edit, not three. Set separately, the stock lookup fired on the
          // id while the kind was still the previous one — so choosing a farm
          // asked for a warehouse's balance.
          const patch = {
            [typeKey]: kind || "warehouse",
            [idKey]: id || "",
            // A batch belongs to the farm that was chosen; keeping the old one
            // would attach this movement to a flock on a different farm.
            [batchKey]: "",
          };
          if (setMany) setMany(patch);
          else Object.entries(patch).forEach(([k, val]) => set(k, val));
        }}
      />
      {field.withBatch && onFarm ? (
        <FormControl
          field={{
            name: batchKey,
            label: "Batch",
            type: "select",
            options: batches,
            placeholder: batches.length
              ? "Select batch"
              : farmId ? "This farm has no batches" : "Choose a farm first",
          }}
          value={values[batchKey] ?? ""}
          onChange={(v) => set(batchKey, v)}
        />
      ) : null}
    </View>
  );
}


/** Add/Less style segmented toggle for a plain-choice field. */
function ToggleControl({
  field,
  value,
  onChange,
}: {
  field: DocField;
  value: string;
  onChange: (v: string) => void;
}) {
  const { colors } = useTheme();
  const styles = useStyles();
  return (
    <View style={{ marginBottom: spacing.lg }}>
      <Text style={styles.locLabel}>
        {field.label}
        {field.required ? <Text style={{ color: colors.danger }}> *</Text> : null}
      </Text>
      <View style={styles.chipRow}>
        {(field.options ?? []).map((o) => {
          const on = value === o.value;
          return (
            <Pressable
              key={o.value}
              onPress={() => onChange(o.value)}
              style={[styles.chip, on && styles.chipOn]}
            >
              <Text style={[styles.chipText, on && styles.chipTextOn]}>{o.label}</Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

/** Renders any DocField by type (delegating plain types to FormControl). */
function DocFieldControl({
  field,
  values,
  set,
  setMany,
  error,
  dynamic,
}: {
  field: DocField;
  values: Dict;
  set: (key: string, val: string) => void;
  /** Several keys as one edit — only a location needs it. */
  setMany?: (patch: Dict) => void;
  error?: string;
  /** Choices for a `dynamicOptions` picker; undefined for every other field. */
  dynamic?: { value: string; label: string }[];
}) {
  if (field.type === "location")
    return <LocationControl field={field} values={values} set={set} setMany={setMany} />;
  if (field.type === "toggle")
    return <ToggleControl field={field} value={values[field.name] ?? ""} onChange={(v) => set(field.name, v)} />;
  if (field.type === "readonly")
    return <ReadonlyControl field={field} value={values[field.name] ?? ""} />;
  if (field.type === "textarea")
    return (
      <NotesControl
        field={field}
        value={values[field.name] ?? ""}
        onChange={(v) => set(field.name, v)}
      />
    );
  const asked = asFormField(field);
  if (field.dynamicOptions) {
    // No path to fetch from: the choices arrive already loaded, and an empty
    // set says why it is empty rather than looking like a broken picker.
    asked.options = dynamic ?? [];
    asked.optionsPath = undefined;
    if (!values[field.dynamicOptions.on] && field.dynamicOptions.emptyHint) {
      asked.placeholder = field.dynamicOptions.emptyHint;
    }
  }
  return (
    <FormControl
      field={asked}
      value={values[field.name] ?? ""}
      error={error}
      onChange={(v) => set(field.name, v)}
    />
  );
}

/** A value the row derives rather than asks for. Shown so the row reads
 *  complete, greyed so it is plainly not an input. */
function ReadonlyControl({ field, value }: { field: DocField; value: string }) {
  const styles = useStyles();
  return (
    <View style={styles.field}>
      <Text style={styles.fieldLabel}>{field.label}</Text>
      <View style={[styles.input, styles.readonly]}>
        <Text style={value ? styles.readonlyValue : styles.readonlyHint}>
          {value || field.placeholder || "auto"}
        </Text>
      </View>
    </View>
  );
}

/** Multi-line notes with the remaining budget shown, so the limit is visible
 *  before it is hit rather than as silently truncated text afterwards. */
function NotesControl({
  field,
  value,
  onChange,
}: {
  field: DocField;
  value: string;
  onChange: (v: string) => void;
}) {
  const styles = useStyles();
  const { colors } = useTheme();
  const max = field.maxLength ?? 200;
  return (
    <View style={styles.field}>
      <Text style={styles.fieldLabel}>{field.label}</Text>
      <TextInput
        style={[styles.input, styles.notes]}
        value={value}
        onChangeText={(t) => onChange(t.slice(0, max))}
        placeholder={field.placeholder}
        placeholderTextColor={colors.textFaint}
        multiline
        maxLength={max}
      />
      <Text style={styles.counter}>{value.length}/{max}</Text>
    </View>
  );
}

/** Seed a values dict for a field set: toggle defaults + warehouse location type.
 *  Defaults only fill keys `extra` doesn't already set (so edit prefill wins). */
const initValues = (fields: DocField[], extra: Dict = {}): Dict => {
  const v: Dict = { ...extra };
  for (const f of fields) {
    if (f.type === "toggle" && f.options?.length && v[f.name] === undefined) {
      v[f.name] = f.options[0].value;
    }
    if (f.type === "location" && v[`${f.name}_type`] === undefined) {
      v[`${f.name}_type`] = "warehouse";
    }
    // A row carrying its own date starts on today, as the web grid's rows do —
    // a document whose date lives on the header has this seeded there instead.
    if (f.type === "date" && v[f.name] === undefined) {
      v[f.name] = new Date().toISOString().slice(0, 10);
    }
  }
  return v;
};

/** The item fields a document actually renders — its sections when it has
 *  them, the flat list otherwise. Seeding walked only the flat list, so a
 *  sectioned document's dates and toggles started empty. */
const itemFieldsOf = (d: DocConfig): DocField[] =>
  d.itemSections ? d.itemSections.flatMap((s) => s.fields) : d.itemFields;

export function DocumentFormScreen({ route, navigation }: Props) {
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const { resourceKey, mode, row } = route.params;
  const doc = DOCUMENTS[resourceKey];
  const config = RESOURCES[resourceKey];
  const editId = mode === "edit" ? (row?.id as number | undefined) : undefined;

  const [header, setHeader] = useState<Dict>(() =>
    initValues(doc.header, { date: new Date().toISOString().slice(0, 10) })
  );
  const [items, setItems] = useState<Dict[]>(() => [initValues(itemFieldsOf(doc))]);
  const [loading, setLoading] = useState(editId != null);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useLayoutEffect(() => {
    navigation.setOptions({
      title: `${editId != null ? "Edit" : "Add"} ${doc.title}`,
      headerRight: () => (
        <Pressable
          onPress={() => navigation.navigate("List", { resourceKey })}
          style={styles.registerBtn}
          accessibilityRole="button"
          accessibilityLabel={`${doc.title} register`}
        >
          <AppIcon name="format-list-bulleted" size={16} color={colors.onDark} />
          <Text style={styles.registerText}>Register</Text>
        </Pressable>
      ),
    });
  }, [navigation, doc.title, editId, resourceKey, styles, colors.onDark]);

  // Edit: fetch the existing document (already in form-field shape) and prefill.
  useEffect(() => {
    if (editId == null) return;
    let alive = true;
    (async () => {
      try {
        const detail = await loadDocument(doc.savePath, editId);
        if (!alive) return;
        setHeader(initValues(doc.header, detail.header));
        setItems(detail.items.length ? detail.items : [initValues(itemFieldsOf(doc))]);
      } catch (e) {
        if (alive) setFormError((e as Error)?.message ?? "Could not load this record.");
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [editId, doc]);

  const setHeaderKey = (key: string, val: string) => setHeader((p) => ({ ...p, [key]: val }));
  /**
   * Change several of a row's fields as one edit.
   *
   * A location is three values — its kind, which one, and the batch under it —
   * and setting them one at a time meant the lookups fired against a row that
   * still held the last one. Choosing a *farm* asked the server for a
   * *warehouse* balance, because the id had changed and the kind had not yet.
   */
  const setItemKeys = (idx: number, patch: Dict) => {
    setItems((prev) => prev.map((it, i) => {
      if (i !== idx) return it;
      const next = { ...it, ...patch };
      // Arithmetic the row owns — placement quantity, amount — recomputed in
      // the same update that changed its inputs, so what a readonly box shows
      // and what the payload carries can never be a keystroke apart.
      return doc.compute ? { ...next, ...doc.compute(next, header) } : next;
    }));
    // A picker whose options come from another field is reloaded, and its
    // value dropped: a batch left over from the farm before it would post
    // these chicks onto a flock on someone else's farm.
    for (const f of itemFieldList) {
      const on = f.dynamicOptions?.on;
      if (on && on in patch) void reloadDynamic(idx, f, patch[on]);
    }
    // The derived half of the row — price, what is actually in stock — is
    // declared by the document rather than switched on its key here, which is
    // what stopped any second document from having lookups at all. It is given
    // the whole patch, so it sees every value this edit changed.
    if (doc.derive?.on.some((k) => k in patch)) void refreshDerived(idx, patch);
  };

  const setItemKey = (idx: number, key: string, val: string) => {
    setItemKeys(idx, { [key]: val });
  };

  /** Every item field, sections or flat — the list both hooks above walk. */
  const itemFieldList = React.useMemo(
    () => (doc.itemSections ? doc.itemSections.flatMap((s) => s.fields) : doc.itemFields),
    [doc]
  );

  /** Options for one row's dependent picker, keyed `<rowIndex>:<field>`. */
  const [dynamic, setDynamic] = useState<Record<string, { value: string; label: string }[]>>({});

  const reloadDynamic = async (idx: number, field: DocField, on: string) => {
    const key = `${idx}:${field.name}`;
    setItems((prev) => prev.map((it, i) => (i === idx ? { ...it, [field.name]: "" } : it)));
    if (!on) {
      setDynamic((d) => ({ ...d, [key]: [] }));
      return;
    }
    try {
      const options = await field.dynamicOptions!.load(on);
      setDynamic((d) => ({ ...d, [key]: options }));
      // One choice is not a question. The web form pre-selects the active
      // batch for the same reason.
      if (options.length === 1) {
        setItems((prev) => prev.map((it, i) => (i === idx ? { ...it, [field.name]: options[0].value } : it)));
      }
    } catch {
      setDynamic((d) => ({ ...d, [key]: [] }));
    }
  };

  /**
   * Fill a row's UOM, rate and available stock from the server.
   *
   * Advisory: a lookup that fails leaves the row usable rather than blocking
   * the sheet, and the save re-checks the stock anyway.
   */
  const refreshDerived = async (idx: number, patch: Dict) => {
    if (!doc.derive) return;
    const row = { ...(items[idx] ?? {}), ...patch };
    let found: Dict;
    try {
      found = await doc.derive.run(row, header);
    } catch {
      return;                                   // advisory; the save re-checks
    }
    if (!Object.keys(found).length) return;
    setItems((prev) => prev.map((it, i) => {
      if (i !== idx) return it;
      const next = { ...it, ...found };
      return doc.compute ? { ...next, ...doc.compute(next, header) } : next;
    }));
  };

  const addItem = () => setItems((prev) => [...prev, initValues(itemFieldsOf(doc))]);
  const removeItem = (idx: number) => setItems((prev) => prev.filter((_, i) => i !== idx));

  const onSave = async () => {
    setFormError(null);
    // Header required checks.
    for (const f of doc.header) {
      if (!f.required) continue;
      const missing =
        f.type === "location" ? isEmpty(header[`${f.name}_id`]) : isEmpty(header[f.name]);
      if (missing) {
        setFormError(`${f.label} is required.`);
        return;
      }
    }
    // Edit of a row-based doc updates one record (flat); otherwise header+items.
    const payload =
      editId != null && doc.buildEdit ? doc.buildEdit(header, items) : doc.build(header, items);
    // Guard: at least one usable line (skip for flat single-record edits).
    const lineKey = Object.keys(payload).find((k) => Array.isArray((payload as never)[k]));
    if (lineKey) {
      const lines = (payload as Record<string, unknown[]>)[lineKey] as unknown[];
      if (!lines || lines.length === 0) {
        setFormError("Add at least one complete line.");
        return;
      }
    }

    setSaving(true);
    try {
      const written = await writeThrough(
        editId != null
          ? { label: doc.title, method: "PUT",
              path: `${doc.savePath}/${editId}`, body: { fields: payload } }
          : { label: doc.title, method: "POST",
              path: doc.savePath, body: { fields: payload } });
      queryClient.invalidateQueries({ queryKey: ["list", config.path] });
      if (written.queued) {
        await notify("Saved on this phone",
          `No signal — this ${doc.title.toLowerCase()} is waiting to send, ` +
            "and will go to the ERP by itself once you are back in range.");
      }
      navigation.navigate("List", { resourceKey });
    } catch (e) {
      if (e instanceof ApiError) setFormError(e.message || "Could not save.");
      else setFormError((e as Error)?.message ?? "Something went wrong.");
    } finally {
      setSaving(false);
    }
  };

  const onDelete = async () => {
    if (editId == null) return;
    if (!(await confirm({
      title: "Delete",
      message: `Delete this ${doc.title.toLowerCase()}?`,
      confirmLabel: "Delete",
      destructive: true,
    }))) return;
    try {
      await writeThrough({ label: doc.title, method: "DELETE",
                           path: `${doc.savePath}/${editId}` });
      queryClient.invalidateQueries({ queryKey: ["list", config.path] });
      navigation.navigate("List", { resourceKey });
    } catch (e) {
      setFormError((e as Error)?.message ?? "Could not delete.");
    }
  };

  if (loading) return <Loading label={`Loading ${doc.title.toLowerCase()}…`} />;

  return (
    <View style={styles.screen}>
      <KeyboardAwareScrollView contentContainerStyle={styles.content}>
      {formError ? <Text style={styles.formError}>{formError}</Text> : null}

      {/* Header */}
      {doc.headerTitle ? (
        <Text style={styles.groupHeading}>{doc.headerTitle.toUpperCase()}</Text>
      ) : null}
      <Card style={styles.section}>
        <FieldRows fields={doc.header} values={header} set={setHeaderKey} />
      </Card>

      {/* Line items. Row-based docs edit a single record, so no add/remove there. */}
      <View style={styles.itemsHeader}>
        {/* Count on its own line: beside a long title it was what pushed the
            Add button off the right edge. */}
        <View style={styles.itemsHeading}>
          <Text style={styles.itemsTitle}>{doc.itemTitle.toUpperCase()}</Text>
          {doc.itemNoun ? (
            <Text style={styles.itemsCount}>
              {items.length} {doc.itemNoun}{items.length === 1 ? "" : "s"}
            </Text>
          ) : null}
        </View>
        {editId != null && doc.buildEdit ? null : (
          <Pressable hitSlop={8} onPress={addItem} style={styles.addRowButton}>
            <Text style={styles.addLink}>＋ Add {doc.itemNoun ?? "line"}</Text>
          </Pressable>
        )}
      </View>

      {items.map((it, idx) => (
        <Card key={idx} style={styles.itemCard}>
          {doc.itemSections ? (
            doc.itemSections.map((section, sIdx) => (
              <View key={section.title}>
                <View style={[styles.sectionHead, styles[`tone_${section.tone}`]]}>
                  {section.icon ? (
                    <View style={[styles.sectionChip, styles[`chip_${section.tone}`]]}>
                      <AppIcon name={section.icon as IconName} size={15} color="#fff" />
                    </View>
                  ) : null}
                  <Text style={[styles.sectionTitle, styles[`toneText_${section.tone}`]]}>
                    {section.icon ? `${sIdx + 1}. ` : ""}{section.title.toUpperCase()}
                  </Text>
                  {/* Pushes the delete to the far end without letting a
                      section that has none right-align its own title. */}
                  <View style={styles.sectionSpacer} />
                  {/* Only the first heading carries the delete, so a row has
                      one obvious way out rather than three. */}
                  {sIdx === 0 && items.length > 1 ? (
                    <Pressable
                      hitSlop={8}
                      onPress={() => removeItem(idx)}
                      accessibilityRole="button"
                      accessibilityLabel={`Remove ${doc.itemNoun ?? "line"} ${idx + 1}`}
                    >
                      <AppIcon name="trash-can-outline" size={18} color={colors.danger} />
                    </Pressable>
                  ) : null}
                </View>
                <FieldRows
                  fields={section.fields}
                  values={it}
                  set={(key, val) => setItemKey(idx, key, val)}
                  setMany={(patch) => setItemKeys(idx, patch)}
                  dynamic={dynamic}
                  rowIndex={idx}
                />
              </View>
            ))
          ) : (
            <>
              <View style={styles.itemCardHead}>
                <Text style={styles.itemCardTitle}>Line {idx + 1}</Text>
                {items.length > 1 ? (
                  <Pressable hitSlop={8} onPress={() => removeItem(idx)}>
                    <Text style={styles.removeLink}>Remove</Text>
                  </Pressable>
                ) : null}
              </View>
              {doc.itemFields.map((f) => (
                <DocFieldControl
                  key={f.name}
                  field={f}
                  values={it}
                  set={(key, val) => setItemKey(idx, key, val)}
                  setMany={(patch) => setItemKeys(idx, patch)}
                />
              ))}
            </>
          )}
        </Card>
      ))}

      {/* A second way to add, at the end of the list where the last row ends —
          the top button is out of sight by then on a long sheet. */}
      {doc.itemSections && !(editId != null && doc.buildEdit) ? (
        <Pressable onPress={addItem} style={styles.addItemDashed}>
          <Text style={styles.addLink}>＋ Add {doc.itemNoun ?? "line"}</Text>
        </Pressable>
      ) : null}

      {/* Delete stays in the sheet rather than the footer: it destroys the
          record, and a destructive button pinned beside Submit is one it will
          eventually be hit instead of. */}
      {editId != null ? (
        <View style={{ marginTop: spacing.sm }}>
          <Button title="Delete" variant="danger" onPress={onDelete} />
        </View>
      ) : null}
      <View style={{ height: spacing.xxl }} />
      </KeyboardAwareScrollView>

      {/* Cancel and Submit stay on screen: these sheets run to several
          hundred points, and a footer scrolled off the end is a footer
          nobody finds. */}
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
          onPress={onSave}
          disabled={saving}
          accessibilityRole="button"
        >
          <AppIcon name="check" size={18} color="#fff" />
          <Text style={styles.submitText}>
            {saving ? "Saving…" : editId != null ? "Save changes" : "Submit"}
          </Text>
        </Pressable>
      </View>
    </View>
  );
}

const useStyles = makeStyles((colors) => ({
  screen: { flex: 1, backgroundColor: colors.bg },
  footer: {
    flexDirection: "row", gap: spacing.sm, padding: spacing.md,
    borderTopWidth: 1, borderTopColor: colors.border, backgroundColor: colors.surface,
  },
  cancelBtn: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: spacing.xs, borderWidth: 1, borderColor: colors.danger,
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
  content: { padding: spacing.md },
  section: { marginBottom: spacing.md },
  formError: {
    ...type.label,
    color: colors.danger,
    backgroundColor: colors.dangerLight,
    padding: spacing.md,
    borderRadius: 12,
    marginBottom: spacing.md,
  },
  itemsHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: spacing.sm,
    marginBottom: spacing.sm,
  },
  // The title yields and the button keeps its width: a long document name
  // ("Chicks Placement Records") was pushing Add off the right edge, which is
  // the one control the header exists for.
  itemsHeading: { flexShrink: 1 },
  // White on the module-coloured header bar; in the module colour it would be
  // there and invisible.
  registerBtn: {
    flexDirection: "row", alignItems: "center", gap: spacing.xs,
    borderWidth: 1, borderColor: colors.onDark, borderRadius: radius.sm,
    paddingHorizontal: spacing.sm, paddingVertical: 5, marginRight: spacing.xs,
  },
  registerText: { ...type.label, color: colors.onDark, fontWeight: "700" },
  itemsTitle: { ...type.h3, color: colors.text },
  itemsCount: { ...type.body, color: colors.textMuted, fontWeight: "400" },
  pair: { flexDirection: "row", gap: spacing.md },
  pairHalf: { flex: 1 },
  groupHeading: {
    ...type.label,
    fontWeight: "700",
    color: colors.textMuted,
    letterSpacing: 0.6,
    marginBottom: spacing.sm,
  },
  addRowButton: {
    flexShrink: 0,
    borderWidth: 1,
    borderColor: colors.tint,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
  },
  addItemDashed: {
    borderWidth: 1,
    borderStyle: "dashed",
    borderColor: colors.tint,
    borderRadius: radius.md,
    alignItems: "center",
    paddingVertical: spacing.md,
    marginBottom: spacing.md,
  },
  addLink: { ...type.title, color: colors.tint },

  /* Section headings inside an item card. The tones separate what is moving
     from where it goes from who is driving it, so ten fields read as three
     short groups rather than one long list. */
  sectionHead: {
    flexDirection: "row",
    alignItems: "center",
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    borderRadius: radius.md,
    marginTop: spacing.md,
    marginBottom: spacing.sm,
  },
  sectionTitle: { ...type.label, fontWeight: "700", letterSpacing: 0.6 },
  sectionSpacer: { flex: 1 },
  // Chicks Placement's three: where they came from, how many, what they cost.
  tone_source: { backgroundColor: "rgba(234,88,12,0.10)" },
  tone_quantity: { backgroundColor: "rgba(22,163,74,0.10)" },
  tone_pricing: { backgroundColor: "rgba(37,99,235,0.10)" },
  toneText_source: { color: "#c2410c" },
  toneText_quantity: { color: "#15803d" },
  toneText_pricing: { color: "#1d4ed8" },
  sectionChip: {
    width: 26, height: 26, borderRadius: 8,
    alignItems: "center", justifyContent: "center", marginRight: spacing.xs,
  },
  chip_source: { backgroundColor: "#ea580c" },
  chip_quantity: { backgroundColor: "#16a34a" },
  chip_pricing: { backgroundColor: "#2563eb" },
  chip_item: { backgroundColor: "#4f46e5" },
  chip_location: { backgroundColor: "#16a34a" },
  chip_logistics: { backgroundColor: "#ea580c" },
  tone_item: { backgroundColor: "rgba(99,102,241,0.10)" },
  tone_location: { backgroundColor: "rgba(22,163,74,0.10)" },
  tone_logistics: { backgroundColor: "rgba(234,88,12,0.10)" },
  toneText_item: { color: "#4f46e5" },
  toneText_location: { color: "#15803d" },
  toneText_logistics: { color: "#c2410c" },

  /* Derived values and notes. */
  field: { marginBottom: spacing.md },
  fieldLabel: { ...type.label, color: colors.textMuted, marginBottom: spacing.xs },
  input: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    minHeight: 44,
    justifyContent: "center",
    color: colors.text,
  },
  readonly: { backgroundColor: "rgba(0,0,0,0.04)" },
  readonlyValue: { ...type.body, color: colors.text },
  readonlyHint: { ...type.body, color: colors.textFaint },
  notes: { minHeight: 96, textAlignVertical: "top", paddingTop: spacing.sm },
  counter: { ...type.caption, color: colors.textFaint, alignSelf: "flex-end", marginTop: 2 },
  itemCard: { marginBottom: spacing.md },
  itemCardHead: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: spacing.sm,
  },
  itemCardTitle: { ...type.label, color: colors.textMuted, textTransform: "uppercase", letterSpacing: 0.5 },
  removeLink: { ...type.label, color: colors.danger },

  locBlock: { marginBottom: spacing.lg },
  locLabel: { ...type.label, color: colors.text, marginBottom: spacing.xs },
  toggleRow: {
    flexDirection: "row",
    gap: spacing.sm,
    backgroundColor: colors.surfaceAlt,
    padding: 4,
    borderRadius: radius.md,
    marginBottom: spacing.sm,
  },
  toggle: { flex: 1, paddingVertical: spacing.sm, borderRadius: radius.sm, alignItems: "center" },
  toggleOn: { backgroundColor: colors.surface },
  toggleText: { ...type.label, color: colors.textMuted },
  toggleTextOn: { color: colors.tint, fontWeight: "800" },

  // Wrapping chip group (for choice fields with several options, e.g. pay mode).
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, marginBottom: spacing.sm },
  chip: {
    paddingVertical: spacing.xs,
    paddingHorizontal: spacing.md,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  chipOn: { backgroundColor: colors.primaryLight, borderColor: colors.tint },
  chipText: { ...type.label, color: colors.textMuted },
  chipTextOn: { color: colors.tint, fontWeight: "800" },
}));
