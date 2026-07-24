/**
 * Form schemas for create/edit — the write-side companion to the read-side
 * `catalog.ts`. Each CRUD resource lists its editable fields; the generic
 * FormScreen renders them by type and POSTs/PATCHes through `resources.ts`.
 *
 * `select` fields load their options from a master endpoint (`optionsPath`) and
 * build each option's label from `optionLabelKeys` — the same reference data
 * now exposed for FK pickers (broiler masters, hatchery masters, and the shared
 * items/warehouses/customers/suppliers/accounts endpoints).
 */
export type FieldType = "text" | "textarea" | "number" | "decimal" | "date" | "boolean" | "select";

export interface FormField {
  name: string;
  label: string;
  type: FieldType;
  required?: boolean;
  optionsPath?: string;
  optionLabelKeys?: string[];
}

export interface FormSchema {
  fields: FormField[];
}

/* Concise field builders. */
const text = (name: string, label: string, required = false): FormField => ({ name, label, type: "text", required });
const area = (name: string, label: string): FormField => ({ name, label, type: "textarea" });
const num = (name: string, label: string, required = false): FormField => ({ name, label, type: "number", required });
const dec = (name: string, label: string, required = false): FormField => ({ name, label, type: "decimal", required });
const date = (name: string, label: string, required = false): FormField => ({ name, label, type: "date", required });
const bool = (name: string, label: string): FormField => ({ name, label, type: "boolean" });
const sel = (
  name: string,
  label: string,
  optionsPath: string,
  optionLabelKeys: string[],
  required = false
): FormField => ({ name, label, type: "select", optionsPath, optionLabelKeys, required });

// Reusable picker sources.
const SUPERVISOR = (r = false) => sel("supervisor", "Supervisor", "/broiler/supervisors/", ["name"], r);
const FARM = (r = false) => sel("farm", "Farm", "/broiler/farms/", ["farm_name", "farm_code"], r);
const BATCH = (r = false) => sel("batch", "Batch", "/broiler/batches/", ["batch_name", "lot_no"], r);
const FARMER = () => sel("farmer", "Farmer", "/broiler/farmers/", ["farmer_name"]);
const ITEM = (name: string, label: string, r = false) => sel(name, label, "/items/", ["description", "item_code"], r);
const CUSTOMER = () => sel("customer", "Customer", "/customers/", ["name", "code"]);
const SUPPLIER = () => sel("supplier", "Supplier", "/suppliers/", ["name", "code"]);
const WAREHOUSE = (name: string, label: string) => sel(name, label, "/warehouses/", ["name", "code"]);
const ACCOUNT = (name: string, label: string) => sel(name, label, "/accounts/", ["description", "code"]);

export const FORMS: Record<string, FormSchema> = {
  /* ------------------------------- Broiler ------------------------------ */
  "broiler-daily-entries": {
    fields: [
      date("date", "Date", true),
      SUPERVISOR(),
      FARM(true),
      BATCH(true),
      num("age_days", "Age (days)"),
      num("mortality", "Mortality"),
      num("culls", "Culls"),
      ITEM("feed_1", "Feed 1"),
      dec("feed_1_qty", "Feed 1 Qty"),
      ITEM("feed_2", "Feed 2"),
      dec("feed_2_qty", "Feed 2 Qty"),
      dec("avg_weight_gms", "Avg Weight (g)"),
      text("remarks", "Remarks"),
    ],
  },
  "broiler-medicine-vaccine": {
    fields: [
      date("date", "Date", true),
      SUPERVISOR(),
      FARM(true),
      BATCH(true),
      num("age_days", "Age (days)"),
      ITEM("item", "Medicine / Vaccine", true),
      dec("qty", "Quantity"),
      text("remarks", "Remarks"),
    ],
  },
  "broiler-bird-sales": {
    fields: [
      date("date", "Date", true),
      text("doc_no", "Doc No."),
      text("sale_type", "Sale Type"),
      CUSTOMER(),
      FARMER(),
      FARM(),
      BATCH(),
      num("birds", "Birds"),
      dec("net_weight", "Net Weight"),
      dec("avg_weight", "Avg Weight"),
      dec("rate", "Rate"),
      dec("amount", "Amount"),
      text("vehicle", "Vehicle"),
      text("driver", "Driver"),
      text("remarks", "Remarks"),
    ],
  },
  "broiler-sale-receipts": {
    fields: [
      date("date", "Date", true),
      text("sale_type", "Sale Type"),
      CUSTOMER(),
      FARMER(),
      text("mode", "Mode"),
      ACCOUNT("receipt_account", "Receipt Account"),
      dec("amount", "Amount", true),
      text("reference_no", "Reference No."),
      text("remarks", "Remarks"),
    ],
  },

  /* ------------------------------ Hatchery ------------------------------ */
  "hatchery-egg-purchases": {
    fields: [
      date("date", "Date", true),
      SUPPLIER(),
      WAREHOUSE("warehouse", "Warehouse"),
      text("dc_no", "DC No."),
      text("vehicle", "Vehicle"),
      text("driver", "Driver"),
      text("freight_type", "Freight Type"),
      text("payment_mode", "Payment Mode"),
      dec("freight_amount", "Freight Amount"),
      area("remarks", "Remarks"),
    ],
  },
  "hatchery-egg-gradings": {
    fields: [
      date("date", "Date", true),
      WAREHOUSE("storage_location", "Storage Location"),
      SUPPLIER(),
      ITEM("item", "Item"),
      dec("quantity", "Quantity"),
      dec("broken_eggs", "Broken Eggs"),
      dec("damage_eggs", "Damage Eggs"),
      dec("misshapped_eggs", "Misshapped Eggs"),
      dec("dirty_eggs", "Dirty Eggs"),
    ],
  },
  "hatchery-hatch-entries": {
    fields: [
      text("transaction_no", "Transaction No."),
      sel("tray_setting", "Tray Setting", "/hatchery/tray-settings/", ["setting_no"], true),
      date("hatch_date", "Hatch Date", true),
      dec("eggs_total", "Eggs Total"),
      dec("egg_rate", "Egg Rate"),
      dec("chicks_total", "Chicks Total"),
      dec("chick_rate", "Chick Rate"),
      dec("net_amount", "Net Amount"),
      area("remarks", "Remarks"),
    ],
  },
  "hatchery-chick-sales": {
    fields: [
      date("date", "Date", true),
      text("bill_no", "Bill No."),
      CUSTOMER(),
      WAREHOUSE("warehouse", "Warehouse"),
      text("vehicle", "Vehicle"),
      text("driver", "Driver"),
      text("payment_mode", "Payment Mode"),
      dec("freight_amount", "Freight Amount"),
      dec("final_amount", "Final Amount"),
      area("remarks", "Remarks"),
    ],
  },
  "hatchery-delivery-challans": {
    fields: [
      date("date", "Date", true),
      CUSTOMER(),
      text("place_of_supply", "Place of Supply"),
      text("transport_mode", "Transport Mode"),
      text("vehicle_no", "Vehicle No."),
      text("driver_name", "Driver Name"),
      text("driver_mobile", "Driver Mobile"),
      text("eway_bill_no", "E-way Bill No."),
      area("terms", "Terms"),
    ],
  },
  "hatchery-expenses": {
    fields: [
      date("date", "Date", true),
      sel("hatchery", "Hatchery", "/hatchery/hatcheries/", ["hatchery_name"]),
      text("stage", "Stage"),
      sel("expense_type", "Expense Type", "/hatchery/expense-types/", ["name"]),
      dec("amount", "Amount", true),
    ],
  },
};

/** Whether a resource supports create/edit (has a schema + a CRUD endpoint). */
export function isEditable(resourceKey: string): boolean {
  return resourceKey in FORMS;
}
