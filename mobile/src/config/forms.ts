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
import { http } from "@/api/client";
import { Envelope } from "@/api/types";
import { isDocumentForm } from "@/config/documents";

export type FieldType =
  | "text"
  | "textarea"
  | "number"
  | "decimal"
  | "date"
  | "boolean"
  | "select"
  /** Camera / gallery capture; the value is a local file URI or a stored URL. */
  | "photo"
  /** One-tap GPS stamp; writes the pair of lat/long fields named in `geoFields`. */
  | "geo";

export interface FormField {
  name: string;
  label: string;
  type: FieldType;
  required?: boolean;
  optionsPath?: string;
  optionLabelKeys?: string[];
  /** Computed/derived — rendered but not editable (value comes from `compute`). */
  readOnly?: boolean;
  /** Display-only helper (e.g. a running total) — shown but never sent to the API. */
  transient?: boolean;
  /** For `geo`: the [latitude, longitude] field names this control fills. */
  geoFields?: [string, string];
}

export interface FormSchema {
  fields: FormField[];
  /**
   * Client-side derivation, mirroring the web forms' calc functions: given the
   * current input values, return the derived values for `readOnly` fields
   * (amounts, totals, derived quantities). Re-runs on every keystroke.
   */
  compute?: (values: Record<string, string>) => Record<string, string>;
  /**
   * Async auto-fill: when the `on` field changes, derive related values and
   * merge them into the form (e.g. Farm → active Batch + Age), exactly like the
   * web forms' lookup handlers. Receives the new value and the current form
   * values (so it can avoid clobbering fields the user already set).
   */
  autofill?: {
    on: string;
    run: (value: string, values: Record<string, string>) => Promise<Record<string, string>>;
  };
}

interface FarmLookup {
  batch: number | null;
  batch_name: string;
  age_days: number;
  next_date: string;
}

/** Farm → active batch, age, and next entry date (shared by daily/medicine entry). */
const farmLookup = async (farmId: string): Promise<FarmLookup> =>
  (await http.get<Envelope<FarmLookup>>("/broiler/farm-lookup", { params: { farm: farmId } }))
    .data.data;

interface TraySettingLookup {
  setting_date: string | null;
  hatch_date: string | null;
  eggs_total: string;
  egg_rate: string;
  eggs_amount: string;
  eggs_set: string;
}

/** Tray setting → its dates + source purchase figures (Hatch Entry form). */
const traySettingLookup = async (id: string): Promise<TraySettingLookup> =>
  (await http.get<Envelope<TraySettingLookup>>("/hatchery/tray-setting-lookup", {
    params: { tray_setting: id },
  })).data.data;

/** Add `days` to an ISO date string (YYYY-MM-DD); "" if the date is unparseable. */
const addDays = (iso: string, days: number): string => {
  const p = iso.split("-").map(Number);
  if (p.length !== 3 || p.some(isNaN)) return "";
  const d = new Date(Date.UTC(p[0], p[1] - 1, p[2]));
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
};

/** Parse a form string to a number (blank/garbage → 0), for `compute`. */
const toNum = (s?: string): number => Number(s) || 0;
/** Mark a field as computed/read-only. */
const ro = (f: FormField): FormField => ({ ...f, readOnly: true });
/** A display-only computed field (shown, never persisted). */
const calc = (name: string, label: string): FormField => ({
  name, label, type: "decimal", readOnly: true, transient: true,
});

/* Concise field builders. */
const text = (name: string, label: string, required = false): FormField => ({ name, label, type: "text", required });
const area = (name: string, label: string): FormField => ({ name, label, type: "textarea" });
const num = (name: string, label: string, required = false): FormField => ({ name, label, type: "number", required });
const dec = (name: string, label: string, required = false): FormField => ({ name, label, type: "decimal", required });
const date = (name: string, label: string, required = false): FormField => ({ name, label, type: "date", required });
/** Camera / gallery capture. */
const photo = (name: string, label: string): FormField => ({ name, label, type: "photo" });
/** GPS stamp writing a [latitude, longitude] pair; holds no value of its own. */
const geo = (name: string, label: string, fields: [string, string]): FormField => ({
  name, label, type: "geo", transient: true, geoFields: fields,
});
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
      // Field capture — the model reserves these for the mobile app; the web
      // form has no equivalent. All optional: a refused camera/GPS prompt must
      // still leave the entry saveable.
      photo("mort_image", "Mortality Photo"),
      photo("cull_image", "Culls Photo"),
      photo("feed_image", "Feed Photo"),
      geo("entry_location", "Location", ["entry_latitude", "entry_longitude"]),
    ],
    // Farm → active batch, age, and next entry date (web daily_entry_farm_lookup).
    autofill: {
      on: "farm",
      run: async (farmId): Promise<Record<string, string>> => {
        if (!farmId) return { batch: "", age_days: "" };
        const d = await farmLookup(farmId);
        return {
          batch: d.batch != null ? String(d.batch) : "",
          age_days: String(d.age_days ?? ""),
          date: d.next_date,
        };
      },
    },
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
    // Farm → active batch + age (web medicine_entry_farm_lookup).
    autofill: {
      on: "farm",
      run: async (farmId) => {
        if (!farmId) return { batch: "", age_days: "" };
        const d = await farmLookup(farmId);
        return {
          batch: d.batch != null ? String(d.batch) : "",
          age_days: String(d.age_days ?? ""),
        };
      },
    },
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
      calc("total_rejections", "Total Rejections"),
      calc("eggs_to_stock", "Eggs to Stock"),
    ],
    // Mirrors egg_grading_form.js: rejections summed, stock = quantity − rejections.
    compute: (v) => {
      const rejections =
        toNum(v.broken_eggs) + toNum(v.damage_eggs) + toNum(v.misshapped_eggs) + toNum(v.dirty_eggs);
      return {
        total_rejections: rejections.toFixed(2),
        eggs_to_stock: Math.max(toNum(v.quantity) - rejections, 0).toFixed(2),
      };
    },
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
    // Tray Setting → hatch date + source purchase eggs/rate (web applySetting()).
    autofill: {
      on: "tray_setting",
      run: async (id) => {
        if (!id) return { hatch_date: "", eggs_total: "", egg_rate: "" };
        const d = await traySettingLookup(id);
        return {
          hatch_date: d.hatch_date ?? "",
          eggs_total: d.eggs_total ?? "",
          egg_rate: d.egg_rate ?? "",
        };
      },
    },
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
      ro(dec("amount", "Amount")),
      ro(dec("total_amount", "Total Amount")),
    ],
    // Mirrors egg_purchase_form.js calcRow: amount = rate × (received|sent),
    // less percentage and flat discount.
    compute: (v) => {
      const basis = toNum(v.rcv_qty) || toNum(v.sent_qty);
      const amount = toNum(v.rate) * basis;
      const total = amount - (amount * toNum(v.discount_percent)) / 100 - toNum(v.discount_amount);
      return { amount: amount.toFixed(2), total_amount: total.toFixed(2) };
    },
  },
  "hatchery-chick-sale-items": {
    fields: [
      ITEM("item", "Item", true),
      text("farm", "Farm"),
      dec("total_qty", "Total Qty"),
      dec("mortality", "Mortality"),
      dec("culls", "Culls"),
      ro(dec("sale_qty", "Sale Qty")),
      dec("free_qty", "Free Qty"),
      ro(dec("net_qty", "Net Qty")),
      dec("sale_rate", "Sale Rate"),
      dec("discount_percent", "Discount %"),
      dec("discount_amount", "Discount Amount"),
      ro(dec("amount", "Amount")),
    ],
    // Mirrors chick_sale_form.js calcRow: saleable = total − mortality − culls;
    // net (billed) = saleable − free; amount = net × rate − flat discount.
    compute: (v) => {
      const saleQty = Math.max(0, Math.round(toNum(v.total_qty) - toNum(v.mortality) - toNum(v.culls)));
      const net = Math.max(0, saleQty - toNum(v.free_qty));
      const amount = net * toNum(v.sale_rate) - toNum(v.discount_amount);
      return { sale_qty: String(saleQty), net_qty: String(net), amount: amount.toFixed(2) };
    },
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
      ro(dec("amount", "Amount")),
    ],
    // Mirrors delivery_challan_form.js: amount = qty × price × (1 − disc%) × (1 + tax%).
    compute: (v) => {
      const amount =
        toNum(v.quantity) * toNum(v.price) * (1 - toNum(v.discount_percent) / 100) *
        (1 + toNum(v.tax_percent) / 100);
      return { amount: amount.toFixed(2) };
    },
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
      ro(text("sq_feet", "Sq Feet")),
      num("capacity", "Capacity"),
      active(),
    ],
    // Sq Feet = length × width (web broiler_farm_shed calcSqFeet).
    compute: (v) => {
      const area = toNum(v.length) * toNum(v.width);
      return { sq_feet: area ? (Number.isInteger(area) ? String(area) : area.toFixed(2)) : "" };
    },
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
    // Setting Date → Transfer (+18) and Hatch (+21) dates (web tray_set_form).
    autofill: {
      on: "setting_date",
      run: async (settingDate): Promise<Record<string, string>> => {
        if (!settingDate) return {};
        return { transfer_date: addDays(settingDate, 18), hatch_date: addDays(settingDate, 21) };
      },
    },
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

  /* ------------------------------- Sales -------------------------------- */
  "sales-customer-groups": {
    fields: [
      text("code", "Code", true),
      text("description", "Description"),
      text("currency", "Currency"),
      ACCOUNT("control_account", "Control Account"),
      ACCOUNT("advance_account", "Advance Account"),
    ],
  },
  "sales-customers": {
    fields: [
      text("code", "Code"),
      text("name", "Name", true),
      text("mobile", "Mobile"),
      text("phone", "Phone"),
      text("email", "Email"),
      sel("customer_group", "Customer Group", "/sales/customer-groups/", ["code", "description"]),
      text("gstin", "GSTIN"),
      text("pan_tin", "PAN / TIN"),
      text("place", "Place"),
      text("state", "State"),
      area("address", "Address"),
      dec("credit_limit", "Credit Limit"),
      num("credit_period", "Credit Period (days)"),
      dec("opening_balance", "Opening Balance"),
      text("note", "Note"),
    ],
  },
  "sales-prices": {
    fields: [
      sel("item_category", "Item Category", "/inventory/item-categories/", ["code", "name"]),
      ITEM("item", "Item"),
      dec("price", "Price", true),
      date("date", "Date", true),
    ],
  },
  "sales-shipping-addresses": {
    fields: [
      CUSTOMER(),
      text("label", "Label", true),
      area("address", "Address"),
      text("contact_person", "Contact Person"),
      text("mobile", "Mobile"),
      bool("is_default", "Default address"),
    ],
  },

  /* ------------------------------ Purchase ------------------------------ */
  "purchase-vendor-groups": {
    fields: [
      text("code", "Code", true),
      text("description", "Description"),
      text("currency", "Currency"),
      ACCOUNT("control_account", "Control Account"),
      ACCOUNT("prepayment_account", "Prepayment Account"),
    ],
  },
  "purchase-suppliers": {
    fields: [
      text("code", "Code"),
      text("name", "Name", true),
      text("mobile", "Mobile"),
      text("email", "Email"),
      text("supplier_group", "Supplier Group"),
      text("gstin", "GSTIN"),
      text("pan", "PAN"),
      text("place", "Place"),
      text("state", "State"),
      area("address", "Address"),
      dec("credit_limit", "Credit Limit"),
      dec("opening_balance", "Opening Balance"),
      text("note", "Note"),
    ],
  },
  "purchase-credit-terms": {
    fields: [text("term", "Term", true)],
  },
  "purchase-tax-masters": {
    fields: [
      text("tax_code", "Tax Code", true),
      text("description", "Description"),
      dec("tax_percentage", "Tax %"),
      text("rule", "Rule"),
      text("coa", "COA"),
    ],
  },
  "purchase-shipping-addresses": {
    fields: [
      SUPPLIER(),
      text("label", "Label", true),
      area("address", "Address"),
      text("contact_person", "Contact Person"),
      text("mobile", "Mobile"),
      bool("is_default", "Default address"),
    ],
  },
  "purchase-debit-notes": {
    fields: [
      text("note_no", "Note No.", true),
      date("date", "Date", true),
      SUPPLIER(),
      text("against_bill", "Against Bill"),
      text("reason", "Reason"),
      dec("amount", "Amount", true),
      ACCOUNT("account", "Account"),
      text("remarks", "Remarks"),
    ],
  },
  "purchase-credit-notes": {
    fields: [
      text("note_no", "Note No.", true),
      date("date", "Date", true),
      SUPPLIER(),
      text("against_bill", "Against Bill"),
      text("reason", "Reason"),
      dec("amount", "Amount", true),
      ACCOUNT("account", "Account"),
      text("remarks", "Remarks"),
    ],
  },

  /* -------------------------------- HR ---------------------------------- */
  "hr-departments": {
    fields: [text("code", "Code", true), text("name", "Name", true), active()],
  },
  "hr-designations": {
    fields: [
      text("code", "Code", true),
      text("title", "Title", true),
      text("description", "Description"),
      dec("base_salary", "Base Salary"),
    ],
  },
  "hr-shifts": {
    fields: [
      text("name", "Name", true),
      text("start_time", "Start Time (HH:MM)"),
      text("end_time", "End Time (HH:MM)"),
      active(),
    ],
  },
  "hr-groups": {
    fields: [
      text("name", "Name", true),
      WAREHOUSE("warehouse", "Warehouse"),
    ],
  },
};

/** Whether a resource can be *created* on mobile (flat form or document form). */
export function isEditable(resourceKey: string): boolean {
  return resourceKey in FORMS || isDocumentForm(resourceKey);
}

/**
 * Whether a resource supports *edit* on mobile — the generic flat forms plus
 * the transaction documents (which now prefill header + line items).
 */
export function isRecordEditable(resourceKey: string): boolean {
  return resourceKey in FORMS || isDocumentForm(resourceKey);
}
