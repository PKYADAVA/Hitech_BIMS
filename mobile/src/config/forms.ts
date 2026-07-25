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
const REGION = (r = false) => sel("region", "Region", "/broiler/regions/", ["code", "description"], r);
const BRANCH = (r = false) => sel("branch", "Branch", "/broiler/branches/", ["branch_name", "code"], r);
const BREED = (r = false) => sel("breed", "Breed", "/broiler/breeds/", ["code", "description"], r);
const FARMER_GROUP = () => sel("farmer_group", "Farmer Group", "/broiler/farmer-groups/", ["code", "description"]);
const HATCHERY = (r = false) => sel("hatchery", "Hatchery", "/hatchery/hatcheries/", ["hatchery_name"], r);
const active = () => bool("is_active", "Active");

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

  /* ---------------------- Hatchery line items --------------------------- */
  // Parent FK (egg_purchase / sale / challan) is injected via the form `preset`.
  "hatchery-egg-purchase-items": {
    fields: [
      ITEM("item", "Item", true),
      dec("sent_qty", "Sent Qty"),
      dec("rcv_qty", "Received Qty"),
      dec("free_qty", "Free Qty"),
      dec("no_of_boxes", "No. of Boxes"),
      dec("rate", "Rate"),
      dec("discount_percent", "Discount %"),
      dec("discount_amount", "Discount Amount"),
      dec("amount", "Amount"),
      dec("total_amount", "Total Amount"),
    ],
  },
  "hatchery-chick-sale-items": {
    fields: [
      ITEM("item", "Item", true),
      text("farm", "Farm"),
      dec("total_qty", "Total Qty"),
      dec("mortality", "Mortality"),
      dec("culls", "Culls"),
      dec("sale_qty", "Sale Qty"),
      dec("free_qty", "Free Qty"),
      dec("net_qty", "Net Qty"),
      dec("sale_rate", "Sale Rate"),
      dec("discount_percent", "Discount %"),
      dec("discount_amount", "Discount Amount"),
      dec("amount", "Amount"),
    ],
  },
  "hatchery-delivery-challan-items": {
    fields: [
      ITEM("item", "Item", true),
      dec("packing_size", "Packing Size"),
      dec("units", "Units"),
      dec("quantity", "Quantity"),
      text("unit", "Unit"),
      dec("price", "Price"),
      dec("discount_percent", "Discount %"),
      dec("tax_percent", "Tax %"),
      dec("amount", "Amount"),
    ],
  },

  /* ------------------------- Broiler master data ------------------------ */
  "broiler-regions": { fields: [text("code", "Code", true), text("description", "Description"), active()] },
  "broiler-branches": {
    fields: [text("code", "Code", true), text("branch_name", "Branch Name", true), REGION(), text("prefix", "Prefix"), active()],
  },
  "broiler-lines": {
    fields: [text("code", "Code", true), text("description", "Description"), REGION(), BRANCH(), active()],
  },
  "broiler-supervisors": {
    fields: [text("name", "Name", true), text("phone_no", "Phone"), text("email", "Email"), BRANCH(), area("address", "Address")],
  },
  "broiler-farmer-groups": { fields: [text("code", "Code", true), text("description", "Description"), active()] },
  "broiler-farmers": {
    fields: [
      text("farmer_name", "Farmer Name", true),
      text("mobile_no", "Mobile"),
      text("phone_no", "Phone"),
      FARMER_GROUP(),
      text("pan_no", "PAN"),
      text("aadhar_no", "Aadhar"),
      text("account_holder_name", "A/C Holder"),
      text("acc_no", "Account No."),
      text("ifsc_code", "IFSC"),
      text("bank_name", "Bank"),
      area("address", "Address"),
    ],
  },
  "broiler-farms": {
    fields: [
      text("farm_code", "Farm Code", true),
      text("farm_name", "Farm Name", true),
      BRANCH(),
      SUPERVISOR(),
      sel("farmer", "Farmer", "/broiler/farmers/", ["farmer_name"]),
      text("region", "Region"),
      text("line", "Line"),
      num("farm_capacity", "Capacity"),
      text("farm_type", "Farm Type"),
      text("state", "State"),
      text("district", "District"),
      text("area", "Area"),
      text("farm_pincode", "Pincode"),
      area("farm_address", "Address"),
      area("remarks", "Remarks"),
    ],
  },
  "broiler-sheds": {
    fields: [
      sel("farm", "Farm", "/broiler/farms/", ["farm_name", "farm_code"], true),
      text("shed_code", "Shed Code", true),
      text("shed_name", "Shed Name"),
      text("shed_type", "Shed Type"),
      text("shed_no", "Shed No."),
      num("unit_no", "Unit No."),
      dec("length", "Length"),
      dec("width", "Width"),
      text("sq_feet", "Sq Feet"),
      num("capacity", "Capacity"),
      active(),
    ],
  },
  "broiler-batches": {
    fields: [
      sel("broiler_farm", "Farm", "/broiler/farms/", ["farm_name", "farm_code"], true),
      text("batch_name", "Batch Name", true),
      text("book_number", "Book Number"),
      text("lot_no", "Lot No."),
      BREED(),
      date("start_date", "Start Date"),
      date("end_date", "End Date"),
      bool("is_closed", "Closed"),
    ],
  },
  "broiler-breeds": { fields: [text("code", "Code", true), text("description", "Description"), active()] },
  "broiler-breed-standards": {
    fields: [
      text("code", "Code"),
      BREED(true),
      num("age", "Age (days)", true),
      dec("body_weight", "Body Weight"),
      dec("feed_intake", "Feed Intake"),
      dec("avg_daily_gain", "Avg Daily Gain"),
      dec("fcr", "FCR"),
      dec("cum_feed", "Cum. Feed"),
      active(),
    ],
  },
  "broiler-diseases": {
    fields: [
      text("disease_code", "Disease Code", true),
      text("disease_name", "Disease Name", true),
      sel("batch", "Batch", "/broiler/batches/", ["batch_name", "lot_no"]),
      area("symptoms", "Symptoms"),
      area("diagnosis", "Diagnosis"),
      date("diagnosed_date", "Diagnosed Date"),
    ],
  },
  "broiler-growing-charges": {
    fields: [
      text("scheme_code", "Scheme Code", true),
      text("schema_name", "Scheme Name"),
      REGION(),
      BRANCH(),
      date("from_date", "From Date"),
      date("to_date", "To Date"),
      dec("chick_cost", "Chick Cost"),
      dec("feed_cost", "Feed Cost"),
      dec("medicine_cost", "Medicine Cost"),
      dec("farmer_admin_cost", "Farmer Admin Cost"),
      dec("management_admin_cost", "Mgmt Admin Cost"),
      dec("standard_fcr", "Standard FCR"),
      dec("standard_mortality", "Standard Mortality"),
      active(),
    ],
  },

  /* ------------------------ Hatchery master data ------------------------ */
  "hatchery-hatch-settings": {
    fields: [
      text("setting_no", "Setting No.", true),
      text("batch_flock_no", "Batch / Flock No."),
      text("supplier_name", "Supplier Name"),
      date("received_date", "Received Date"),
      date("setting_date", "Setting Date"),
      date("transfer_date", "Transfer Date"),
      date("hatch_date", "Hatch Date"),
      num("received_qty", "Received Qty"),
      num("breakage_qty", "Breakage Qty"),
      num("crack_qty", "Crack Qty"),
      num("setting_qty", "Setting Qty"),
      text("setter_temperature", "Setter Temp"),
      text("setter_humidity", "Setter Humidity"),
      text("hatcher_temperature", "Hatcher Temp"),
      text("hatcher_humidity", "Hatcher Humidity"),
      text("avg_chick_weight", "Avg Chick Weight"),
      text("medicine_vaccine", "Medicine / Vaccine"),
      num("packing_boxes_used", "Packing Boxes"),
      area("remarks", "Remarks"),
      text("prepared_by", "Prepared By"),
      text("verified_by", "Verified By"),
    ],
  },
  "hatchery-tray-settings": {
    fields: [
      text("setting_no", "Setting No.", true),
      HATCHERY(),
      date("setting_date", "Setting Date"),
      date("transfer_date", "Transfer Date"),
      date("hatch_date", "Hatch Date"),
      text("loaded_by", "Loaded By"),
      sel("grading", "Egg Grading", "/hatchery/egg-gradings/", ["transaction_no"]),
    ],
  },
  "hatchery-hatcheries": {
    fields: [
      text("hatchery_name", "Hatchery Name", true),
      text("operation_type", "Operation Type"),
      text("owner_name", "Owner Name"),
      text("contact", "Contact"),
      text("email", "Email"),
      text("state", "State"),
      num("agreement_months", "Agreement Months"),
      active(),
    ],
  },
  "hatchery-setters": {
    fields: [HATCHERY(true), text("setter_no", "Setter No.", true), num("capacity", "Capacity"), active()],
  },
  "hatchery-hatchers": {
    fields: [HATCHERY(true), text("hatcher_no", "Hatcher No.", true), num("capacity", "Capacity"), active()],
  },
  "hatchery-expense-types": { fields: [text("name", "Name", true), active()] },

  /* --------------------------- SMS module ------------------------------- */
  "sms-templates": {
    fields: [
      text("key", "Key", true),
      text("name", "Name", true),
      { name: "body", label: "Message Body", type: "textarea", required: true },
      text("module", "Module"),
      text("transaction", "Transaction"),
      text("category", "Category"),
      text("sms_type", "SMS Type"),
      text("sender_id", "Sender ID"),
      text("dlt_template_id", "DLT Template ID"),
      text("description", "Description"),
      active(),
    ],
  },
  "sms-settings": {
    fields: [
      bool("enabled", "Enabled"),
      bool("mock", "Mock mode (no real SMS)"),
      text("sender_id", "Sender ID"),
      text("entity_id", "Entity ID"),
      text("api_key", "API Key (leave blank to keep)"),
      text("default_country_code", "Default Country Code"),
    ],
  },

  /* -------------------------- Account masters --------------------------- */
  "account-financial-years": {
    fields: [
      date("start_date", "Start Date", true),
      date("end_date", "End Date", true),
      active(),
    ],
  },
  "account-terms": {
    fields: [
      text("type", "Type", true),
      text("party_type", "Party Type"),
      area("condition", "Condition"),
    ],
  },

  /* ------------------------- Inventory masters -------------------------- */
  "inventory-item-categories": { fields: [text("name", "Name", true)] },
  "inventory-uom": {
    fields: [text("name", "Name", true), text("symbol", "Symbol")],
  },
  "inventory-sectors": { fields: [text("name", "Name", true)] },
  "inventory-warehouses": {
    fields: [
      text("name", "Name", true),
      sel("sector", "Sector", "/inventory/sectors/", ["name"]),
      area("address", "Address"),
      text("location", "Location"),
    ],
  },
  "inventory-price-list": {
    fields: [
      sel("item", "Item", "/inventory/items/", ["description", "item_code"], true),
      dec("price", "Price", true),
      date("effective_date", "Effective Date", true),
    ],
  },
};

/** Whether a resource supports create/edit (has a schema + a CRUD endpoint). */
export function isEditable(resourceKey: string): boolean {
  return resourceKey in FORMS;
}
