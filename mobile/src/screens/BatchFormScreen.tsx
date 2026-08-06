import { NativeStackScreenProps } from "@react-navigation/native-stack";
import React, { useEffect, useLayoutEffect, useMemo, useState } from "react";
import { Alert, Pressable, ScrollView, Text, View } from "react-native";

import { http } from "@/api/client";
import { Envelope, Row } from "@/api/types";
import { AppIcon } from "@/components/AppIcon";
import { FormControl } from "@/components/form";
import { FormField } from "@/config/forms";
import { ModuleStackParams } from "@/navigation/types";
import { queryClient } from "@/query/queryClient";
import { makeStyles, radius, spacing, type, useTheme } from "@/theme";

type Props = NativeStackScreenProps<ModuleStackParams, "BatchForm">;

/**
 * Batch Creation — a flock starting on a farm, in a shed.
 *
 * The same six fields the ERP's form has, in the same three groups, and the
 * save goes through the ERP's own batch API rather than a second copy of it:
 * the batch number is minted on save, a shed already holding an open batch is
 * refused, and an edit may change only the book number, lot number, breed and
 * shed. The phone showing different rules to the desktop is the failure this
 * screen exists to avoid.
 */

/** A shed of the chosen farm, and whether a batch is already growing in it. */
interface Shed {
  id: number;
  label: string;
  occupied: boolean;
  occupied_by: string;
}

const FARM: FormField = {
  name: "broiler_farm", label: "Broiler Farm", type: "select", required: true,
  optionsPath: "/broiler/farms/", optionLabelKeys: ["farm_name", "farm_code"],
  placeholder: "Select a broiler farm",
};
/** The farm a batch was started on, once it has been. Fixed at creation on the
 *  ERP side, so an edit shows it rather than offering to move the flock. */
const FARM_FIXED: FormField = {
  name: "broiler_farm_name", label: "Broiler Farm", type: "text", readOnly: true,
  placeholder: "—",
};
/**
 * The mockup marks this required; the ERP does not, and the ERP is the rule.
 * Batches without a shed already exist — the field was added after them — and
 * a phone refusing what the desktop accepts is the drift this screen exists to
 * prevent. Same for Breed below.
 */
const shedField = (options: Shed[], farmChosen: boolean): FormField => ({
  name: "shed", label: "Shed / Unit", type: "select", disabled: !farmChosen,
  placeholder: farmChosen
    ? (options.length ? "Select a shed / unit" : "This farm has no sheds")
    : "Select a farm first",
  options: options.map((s) => ({
    value: String(s.id),
    // Naming the batch in the way turns "why can't I pick this?" into an
    // answer read off the screen.
    label: s.occupied ? `${s.label} · occupied by ${s.occupied_by}` : s.label,
    disabled: s.occupied,
  })),
});
const BATCH_NO: FormField = {
  name: "batch_name", label: "Batch No.", type: "text", readOnly: true,
  placeholder: "Auto-generated (BAH-0201-1)",
};
const BOOK_NO: FormField = {
  name: "book_number", label: "Book Number", type: "text",
  placeholder: "Enter book number",
};
const LOT_NO: FormField = {
  name: "lot_no", label: "Lot No", type: "text", placeholder: "Enter lot no",
};
const BREED: FormField = {
  name: "breed", label: "Breed", type: "select",
  optionsPath: "/broiler/breeds/", optionLabelKeys: ["description", "code"],
  placeholder: "Select Breed",
};

const BLANK = {
  broiler_farm: "", broiler_farm_name: "", shed: "",
  batch_name: "", book_number: "", lot_no: "", breed: "",
};

export function BatchFormScreen({ navigation, route }: Props) {
  const styles = useStyles();
  const { colors } = useTheme();
  const editing = route.params?.row;
  const batchId = editing?.id;

  const [values, setValues] = useState<Record<string, string>>({ ...BLANK });
  const [sheds, setSheds] = useState<Shed[]>([]);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  // The mockup gives this screen its own chrome rather than the module's
  // orange bar: a white header, the title in the page's own text colour, and a
  // close cross instead of a back arrow — it is a form you finish or abandon,
  // not a place you navigated to.
  useLayoutEffect(() => {
    navigation.setOptions({
      title: batchId ? "Edit Batch" : "Add New Batch",
      headerStyle: { backgroundColor: colors.surface },
      headerTitleStyle: { color: colors.text, fontWeight: "800" },
      headerTintColor: colors.text,
      headerShadowVisible: true,
      headerBackVisible: false,
      headerLeft: () => (
        <Pressable onPress={() => navigation.goBack()} hitSlop={12}
                   accessibilityRole="button" accessibilityLabel="Close">
          <AppIcon name="close" size={24} color={colors.text} />
        </Pressable>
      ),
    });
  }, [navigation, batchId, colors]);

  // An existing batch is loaded from the write endpoint rather than read off
  // the list row: the list carries display names, and this form needs the ids
  // its pickers are keyed on.
  useEffect(() => {
    if (!batchId) return;
    http.get<Envelope<Record<string, string>>>(`/broiler/batches/save/${batchId}`)
      .then(({ data }) => setValues({ ...BLANK, ...data.data }))
      .catch(() => setError("That batch could not be loaded."));
  }, [batchId]);

  // The farm decides the sheds, so they are fetched per farm rather than the
  // whole estate filtered on the phone. Occupancy is a server answer for the
  // same reason the refusal is: it changes while this form is open.
  useEffect(() => {
    if (!values.broiler_farm) return setSheds([]);
    let live = true;
    http.get<Envelope<Shed[]>>("/broiler/batch-sheds",
                               { params: { farm: values.broiler_farm } })
      .then(({ data }) => { if (live) setSheds(data.data); })
      .catch(() => { if (live) setSheds([]); });
    return () => { live = false; };
  }, [values.broiler_farm]);

  const onChange = (name: string) => (v: string) =>
    setValues((prev) => {
      // Changing the farm invalidates the shed under it — leaving the old one
      // selected would post a shed belonging to a different farm.
      const next = { ...prev, [name]: v };
      if (name === "broiler_farm" && v !== prev.broiler_farm) next.shed = "";
      return next;
    });

  const shedOptions = useMemo(
    () => shedField(sheds, !!values.broiler_farm),
    [sheds, values.broiler_farm]);

  const save = async () => {
    setError("");
    // The farm is the ERP's one required field, and the only one a batch
    // cannot be numbered without.
    if (!batchId && !values.broiler_farm) return setError("Choose the broiler farm.");

    setSaving(true);
    try {
      const body = {
        // The web API reads the farm under this name; the rest match.
        broiler_farm_id: values.broiler_farm,
        shed: values.shed,
        book_number: values.book_number,
        lot_no: values.lot_no,
        breed: values.breed,
      };
      if (batchId) {
        await http.put(`/broiler/batches/save/${batchId}`, body);
      } else {
        await http.post("/broiler/batches/save", body);
      }
      queryClient.invalidateQueries({ queryKey: ["resource", "/broiler/batches/"] });
      navigation.goBack();
    } catch (e: unknown) {
      const err = e as { message?: string; fields?: Record<string, string[]> };
      const detail = Object.values(err.fields ?? {}).flat().join(" ");
      const message = detail || err.message || "Could not save the batch.";
      setError(message);
      Alert.alert("Could not save", message);
    } finally {
      setSaving(false);
    }
  };

  const SectionHead = ({ icon, title, tint }: {
    icon: string; title: string; tint: string;
  }) => (
    <View style={[styles.sectionHead, { backgroundColor: `${tint}14` }]}>
      <AppIcon name={icon as never} size={18} color={tint} />
      <Text style={[styles.sectionTitle, { color: tint }]}>{title}</Text>
    </View>
  );

  return (
    <View style={styles.screen}>
      <ScrollView contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
        {error ? <Text style={styles.error}>{error}</Text> : null}

        <View style={styles.card}>
          <SectionHead icon="barn" title="1. FARM & SHED SELECTION"
                       tint={colors.tint} />
          <View style={styles.cardBody}>
            {batchId ? (
              <FormControl field={FARM_FIXED} value={values.broiler_farm_name}
                           values={values} onChange={() => {}} />
            ) : (
              <FormControl field={FARM} value={values.broiler_farm}
                           values={values} onChange={onChange("broiler_farm")} />
            )}
            <FormControl field={shedOptions} value={values.shed}
                         values={values} onChange={onChange("shed")} />
          </View>
        </View>

        <View style={styles.card}>
          <SectionHead icon="clipboard-text-outline" title="2. BATCH IDENTIFIERS"
                       tint={colors.success} />
          <View style={styles.cardBody}>
            <View style={styles.row}>
              <View style={styles.cell}>
                <FormControl field={BATCH_NO} value={values.batch_name}
                             values={values} onChange={() => {}} />
              </View>
              <View style={styles.cell}>
                <FormControl field={BOOK_NO} value={values.book_number}
                             values={values} onChange={onChange("book_number")} />
              </View>
            </View>
            <FormControl field={LOT_NO} value={values.lot_no}
                         values={values} onChange={onChange("lot_no")} />
          </View>
        </View>

        <View style={styles.card}>
          <SectionHead icon="dna" title="3. BREED SPECIFICATION"
                       tint={colors.user} />
          <View style={styles.cardBody}>
            <FormControl field={BREED} value={values.breed}
                         values={values} onChange={onChange("breed")} />
          </View>
        </View>
      </ScrollView>

      <View style={styles.footer}>
        <Pressable style={[styles.cancelButton, { borderColor: colors.danger }]}
                   onPress={() => navigation.goBack()} disabled={saving}>
          <AppIcon name="close" size={18} color={colors.danger} />
          <Text style={[styles.cancelText, { color: colors.danger }]}>Cancel</Text>
        </Pressable>
        <Pressable style={[styles.saveButton, { backgroundColor: colors.tint },
                           saving && { opacity: 0.55 }]}
                   onPress={save} disabled={saving}>
          <AppIcon name="content-save-outline" size={18} color={colors.onDark} />
          <Text style={styles.saveText}>{saving ? "Saving…" : "Save Batch"}</Text>
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
    borderWidth: 1, borderColor: colors.border, overflow: "hidden",
  },
  cardBody: { padding: spacing.md },
  sectionHead: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
  },
  sectionTitle: { ...type.label, letterSpacing: 0.4, fontWeight: "800" },
  row: { flexDirection: "row", gap: spacing.sm, alignItems: "flex-start" },
  cell: { flex: 1, minWidth: 0 },
  error: { ...type.caption, color: colors.danger },
  footer: {
    flexDirection: "row", gap: spacing.sm, padding: spacing.md,
    borderTopWidth: 1, borderTopColor: colors.border, backgroundColor: colors.surface,
  },
  cancelButton: {
    flex: 1, height: 48, borderRadius: radius.md, borderWidth: 1,
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.xs,
  },
  cancelText: { ...type.title },
  saveButton: {
    flex: 1.2, height: 48, borderRadius: radius.md,
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.xs,
  },
  saveText: { ...type.title, color: colors.onDark },
}));
