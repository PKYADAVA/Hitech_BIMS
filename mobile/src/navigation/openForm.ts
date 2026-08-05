import { Row } from "@/api/types";
import { isDocumentForm } from "@/config/documents";
import { isEditable, isRecordEditable } from "@/config/forms";
import { ModuleStackParams } from "@/navigation/types";

/** Resources whose create/edit uses a bespoke screen instead of the generic Form. */
const CUSTOM_FORM_SCREEN: Record<string, "BirdSaleForm" | "BirdSaleReceiptForm"> = {
  "broiler-bird-sales": "BirdSaleForm",
  "broiler-sale-receipts": "BirdSaleReceiptForm",
};

/**
 * Resources handled by a bespoke screen that takes the row as `row` rather than
 * the generic `{resourceKey, mode, row}`.
 *
 * Daily Entry uses the Day Record screen for both: creating walks a round of
 * farms, editing opens one saved row on the same layout. Editing has to be the
 * same screen — the flock panel, the breed standards and the mandatory GPS
 * stamp are what make a day's numbers judgeable, and a correction made without
 * them is exactly as unverified as an original made without them.
 */
const ROW_FORM_SCREEN: Record<string,
  "DailyEntryGrid" | "MedicineEntryForm" | "FarmCaptureForm"
  | "SupervisorTripForm"> = {
  "broiler-daily-entries": "DailyEntryGrid",
  // One supervisor, farm, batch and date over several consumption lines.
  "broiler-medicine-vaccine": "MedicineEntryForm",
  // The pin, the pictures and the scans are all taken standing on the farm.
  "broiler-farm-location-capture": "FarmCaptureForm",
  // Photographs, GPS stamps and odometer shots, all taken on the road.
  "hr-supervisor-trips": "SupervisorTripForm",
};

/**
 * Bespoke screens that only write new records, so a correction stays on the
 * generic form.
 *
 * The Medicine screen writes a *document* — one header over several
 * consumption lines — which is the right shape for recording a round of doses
 * and the wrong shape for fixing the quantity on one saved line.
 */
const CREATE_ONLY = new Set(["broiler-medicine-vaccine"]);

/**
 * Whether an existing record can be corrected.
 *
 * Same reasoning as hasCreateForm: a bespoke screen that handles edit is
 * invisible to `isRecordEditable`, which only knows the generic and document
 * forms, so the register would offer no Edit at all.
 */
export function hasEditForm(resourceKey: string): boolean {
  if (CREATE_ONLY.has(resourceKey)) return isRecordEditable(resourceKey);
  return resourceKey in ROW_FORM_SCREEN
    || resourceKey in CUSTOM_FORM_SCREEN
    || isRecordEditable(resourceKey);
}

/**
 * Whether a new record can be started for this resource at all.
 *
 * `isEditable` alone answers only for the generic and document forms, so a
 * resource served by a bespoke screen — Farm Location Capture, Medicine
 * Consumption — had its list render with no New button and no way in. The
 * bespoke screens are registered right here, so the question is answered here
 * too rather than by a second list kept in step by hand.
 */
export function hasCreateForm(resourceKey: string): boolean {
  return resourceKey in ROW_FORM_SCREEN
    || resourceKey in CUSTOM_FORM_SCREEN
    || isEditable(resourceKey);
}

/** Anything that can push a screen in the module stack (screen props or header options). */
type Nav = { navigate: (screen: any, params?: any) => void };

/**
 * Navigate to the right create/edit form for a resource: a bespoke screen when
 * one is registered (Bird Sale), the header+items document form for a
 * transaction document (stock moves, etc.), otherwise the generic Form. Keeps
 * the "which form?" decision in one place instead of every call site.
 */
export function openRecordForm(
  navigation: Nav,
  resourceKey: string,
  mode: "create" | "edit",
  row?: Row,
) {
  const rowForm = mode === "edit" && CREATE_ONLY.has(resourceKey)
    ? undefined
    : ROW_FORM_SCREEN[resourceKey];
  const custom = CUSTOM_FORM_SCREEN[resourceKey];
  if (rowForm) {
    // Create carries no row; edit carries the one being corrected.
    const params: ModuleStackParams["DailyEntryGrid"] = mode === "edit" ? { row } : undefined;
    navigation.navigate(rowForm, params);
  } else if (custom) {
    const params: ModuleStackParams["BirdSaleForm"] = { mode, row };
    navigation.navigate(custom, params);
  } else if (isDocumentForm(resourceKey)) {
    const params: ModuleStackParams["DocumentForm"] = { resourceKey, mode, row };
    navigation.navigate("DocumentForm", params);
  } else {
    const params: ModuleStackParams["Form"] = { resourceKey, mode, row };
    navigation.navigate("Form", params);
  }
}
