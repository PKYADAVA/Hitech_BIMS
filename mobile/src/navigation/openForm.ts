import { Row } from "@/api/types";
import { ModuleStackParams } from "@/navigation/types";

/** Resources whose create/edit uses a bespoke screen instead of the generic Form. */
const CUSTOM_FORM_SCREEN: Record<string, "BirdSaleForm"> = {
  "broiler-bird-sales": "BirdSaleForm",
};

/** Anything that can push a screen in the module stack (screen props or header options). */
type Nav = { navigate: (screen: any, params?: any) => void };

/**
 * Navigate to the right create/edit form for a resource: a bespoke screen when
 * one is registered (e.g. Bird Sale), otherwise the generic Form. Keeps the
 * "which form?" decision in one place instead of every call site.
 */
export function openRecordForm(
  navigation: Nav,
  resourceKey: string,
  mode: "create" | "edit",
  row?: Row,
) {
  const custom = CUSTOM_FORM_SCREEN[resourceKey];
  if (custom) {
    const params: ModuleStackParams["BirdSaleForm"] = { mode, row };
    navigation.navigate(custom, params);
  } else {
    const params: ModuleStackParams["Form"] = { resourceKey, mode, row };
    navigation.navigate("Form", params);
  }
}
