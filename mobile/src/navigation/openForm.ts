import { Row } from "@/api/types";
import { isDocumentForm } from "@/config/documents";
import { ModuleStackParams } from "@/navigation/types";

/** Resources whose create/edit uses a bespoke screen instead of the generic Form. */
const CUSTOM_FORM_SCREEN: Record<string, "BirdSaleForm" | "BirdSaleReceiptForm"> = {
  "broiler-bird-sales": "BirdSaleForm",
  "broiler-sale-receipts": "BirdSaleReceiptForm",
};

/**
 * Resources whose *new* record has its own screen but whose edit does not.
 *
 * Daily Entry is written on the Add Day Record screen — the flock panel, the
 * standards, the photo columns and the mandatory GPS stamp all belong to
 * recording a day in the shed. Correcting a saved row afterwards is a desk job
 * with no round to walk, so editing stays on the generic form.
 */
const CUSTOM_CREATE_SCREEN: Record<string, "DailyEntryGrid"> = {
  "broiler-daily-entries": "DailyEntryGrid",
};

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
  const createOnly = mode === "create" ? CUSTOM_CREATE_SCREEN[resourceKey] : undefined;
  const custom = CUSTOM_FORM_SCREEN[resourceKey];
  if (createOnly) {
    navigation.navigate(createOnly);
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
