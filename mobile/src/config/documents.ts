/**
 * Transaction *document* forms (header + line items) — the mobile counterpart
 * to the web's multi-row transaction forms. Unlike the flat `FORMS` schemas,
 * these submit a whole document to a `/save` endpoint that reuses the web
 * posting logic (stock movement, running-balance recompute, validation).
 *
 * A `location` field expands to three form keys — `<name>_type` (warehouse/farm),
 * `<name>_id`, and `<name>_batch` — and the per-document `build()` folds the
 * header + items into the exact payload each web API expects.
 */
export type DocFieldType =
  | "text" | "date" | "decimal" | "number" | "select" | "toggle" | "location";

export interface DocField {
  name: string;
  label: string;
  type: DocFieldType;
  required?: boolean;
  optionsPath?: string;
  optionLabelKeys?: string[];
  /** toggle options */
  options?: { value: string; label: string }[];
  /** location: allow a Farm (+ batch) as well as a Warehouse */
  allowFarm?: boolean;
  withBatch?: boolean;
}

type Dict = Record<string, string>;

export interface DocConfig {
  resourceKey: string;
  title: string;
  savePath: string;
  itemTitle: string;
  header: DocField[];
  itemFields: DocField[];
  build: (header: Dict, items: Dict[]) => Record<string, unknown>;
  /**
   * Payload for *edit* (PUT), when it differs from create. The row-based
   * transactions (stock transfer, sales receipt) create many via `{rows:[…]}`
   * but edit one flat record — this returns that flat shape.
   */
  buildEdit?: (header: Dict, items: Dict[]) => Record<string, unknown>;
}

/* ------------------------------- helpers -------------------------------- */

const has = (v: unknown) => v !== undefined && v !== null && String(v).trim() !== "";
/** Read a `location` field's three keys off a values dict. */
const loc = (v: Dict, name: string) => ({
  type: v[`${name}_type`] || "warehouse",
  id: v[`${name}_id`] || null,
  batch: v[`${name}_batch`] || null,
});

const WAREHOUSE_PATH = "/inventory/warehouses/";
const FARM_PATH = "/broiler/farms/";
const BATCH_PATH = "/broiler/batches/";
const ITEM_PATH = "/items/";
const ACCOUNT_PATH = "/accounts/";

const fLoc = (name: string, label: string, opts?: { withBatch?: boolean }): DocField => ({
  name, label, type: "location", allowFarm: true, withBatch: opts?.withBatch ?? true, required: true,
});
const fItem = (): DocField => ({
  name: "item", label: "Item", type: "select", optionsPath: ITEM_PATH,
  optionLabelKeys: ["description", "item_code"], required: true,
});
const fQty = (): DocField => ({ name: "quantity", label: "Quantity", type: "decimal", required: true });
const fRate = (): DocField => ({ name: "rate", label: "Rate", type: "decimal" });
const fRemarks = (): DocField => ({ name: "remarks", label: "Remarks", type: "text" });
const fDate = (): DocField => ({ name: "date", label: "Date", type: "date", required: true });
const fAccount = (name = "chart_of_account", label = "Account", required = false): DocField => ({
  name, label, type: "select", optionsPath: ACCOUNT_PATH, optionLabelKeys: ["description", "code"], required,
});
const fSupplier = (required = false): DocField => ({
  name: "supplier", label: "Supplier", type: "select",
  optionsPath: "/suppliers/", optionLabelKeys: ["name", "code"], required,
});
const fWarehouse = (name: string, label: string, required = false): DocField => ({
  name, label, type: "select", optionsPath: WAREHOUSE_PATH, optionLabelKeys: ["name", "code"], required,
});
const fFreightType = (): DocField => ({
  name: "freight_type", label: "Freight Type", type: "toggle",
  options: [{ value: "Extra", label: "Extra" }, { value: "Included in Bill", label: "Included in Bill" }],
});
const fText = (name: string, label: string): DocField => ({ name, label, type: "text" });
const fDec = (name: string, label: string, required = false): DocField => ({ name, label, type: "decimal", required });

/* ------------------------------ documents ------------------------------- */

export const DOCUMENTS: Record<string, DocConfig> = {
  // Stock Transfer — one From/To for the doc; each item becomes a transfer row.
  "inventory-stock-transfers": {
    resourceKey: "inventory-stock-transfers",
    title: "Stock Transfer",
    savePath: "/inventory/stock-transfers/save",
    itemTitle: "Items",
    header: [
      fDate(),
      { name: "dc_no", label: "DC No.", type: "text" },
      fLoc("from", "From"),
      fLoc("to", "To"),
      { name: "vehicle_no", label: "Vehicle No.", type: "text" },
      { name: "driver_name", label: "Driver", type: "text" },
    ],
    itemFields: [fItem(), fQty(), fRate(), fRemarks()],
    build: (h, items) => {
      const from = loc(h, "from");
      const to = loc(h, "to");
      return {
        rows: items
          .filter((it) => has(it.item))
          .map((it) => ({
            date: h.date,
            dc_no: h.dc_no || "",
            item: it.item,
            quantity: it.quantity || "0",
            rate: it.rate || "0",
            purchase_rate: it.rate || "0",
            from_location_type: from.type,
            from_location_id: from.id,
            from_batch: from.batch,
            to_location_type: to.type,
            to_location_id: to.id,
            to_batch: to.batch,
            vehicle_no: h.vehicle_no || "",
            driver_name: h.driver_name || "",
            remarks: it.remarks || "",
          })),
      };
    },
    // Edit updates one transfer record — flat row, not `{rows:[…]}`.
    buildEdit: (h, items) => {
      const from = loc(h, "from");
      const to = loc(h, "to");
      const it = items[0] ?? {};
      return {
        date: h.date,
        dc_no: h.dc_no || "",
        item: it.item,
        quantity: it.quantity || "0",
        rate: it.rate || "0",
        purchase_rate: it.rate || "0",
        from_location_type: from.type,
        from_location_id: from.id,
        from_batch: from.batch,
        to_location_type: to.type,
        to_location_id: to.id,
        to_batch: to.batch,
        vehicle_no: h.vehicle_no || "",
        driver_name: h.driver_name || "",
        remarks: it.remarks || "",
      };
    },
  },

  // Medicine Transfer — From/To header + simple item lines.
  "inventory-medicine-transfers": {
    resourceKey: "inventory-medicine-transfers",
    title: "Medicine Transfer",
    savePath: "/inventory/medicine-transfers/save",
    itemTitle: "Items",
    header: [
      fDate(),
      { name: "dc_no", label: "DC No.", type: "text" },
      fLoc("from", "From"),
      fLoc("to", "To"),
      { name: "vehicle_no", label: "Vehicle No.", type: "text" },
      { name: "driver_name", label: "Driver", type: "text" },
      { name: "transport_cost", label: "Transport Cost", type: "decimal" },
      fAccount("paid_by", "Paid By (Account)"),
    ],
    itemFields: [fItem(), fQty(), fRate(), fRemarks()],
    build: (h, items) => {
      const from = loc(h, "from");
      const to = loc(h, "to");
      return {
        date: h.date,
        dc_no: h.dc_no || "",
        from_location_type: from.type,
        from_location_id: from.id,
        from_batch: from.batch,
        to_location_type: to.type,
        to_location_id: to.id,
        to_batch: to.batch,
        vehicle_no: h.vehicle_no || "",
        driver_name: h.driver_name || "",
        transport_cost: h.transport_cost || "0",
        paid_by: h.paid_by || null,
        items: items
          .filter((it) => has(it.item))
          .map((it) => ({ item: it.item, quantity: it.quantity || "0", rate: it.rate || "0", remarks: it.remarks || "" })),
      };
    },
  },

  // Inventory Adjustment — single location header + Add/Less item lines.
  "inventory-adjustments": {
    resourceKey: "inventory-adjustments",
    title: "Inventory Adjustment",
    savePath: "/inventory/adjustments/save",
    itemTitle: "Adjustment Lines",
    header: [
      fDate(),
      { name: "bill_no", label: "Bill No.", type: "text" },
      fLoc("loc", "Location"),
      fAccount(),
    ],
    itemFields: [
      fItem(),
      {
        name: "adjustment_type", label: "Type", type: "toggle", required: true,
        options: [{ value: "Add", label: "Add" }, { value: "Less", label: "Less" }],
      },
      fQty(),
      fRate(),
      fRemarks(),
    ],
    build: (h, items) => {
      const l = loc(h, "loc");
      return {
        date: h.date,
        bill_no: h.bill_no || "",
        location_type: l.type,
        location_id: l.id,
        batch: l.batch,
        chart_of_account: h.chart_of_account || null,
        items: items
          .filter((it) => has(it.item) && has(it.adjustment_type))
          .map((it) => ({
            item: it.item,
            adjustment_type: it.adjustment_type,
            quantity: it.quantity || "0",
            rate: it.rate || "0",
            remarks: it.remarks || "",
          })),
      };
    },
  },

  // Stock Issue — per-line location (consumed from warehouse/farm).
  "inventory-stock-issues": {
    resourceKey: "inventory-stock-issues",
    title: "Stock Issue",
    savePath: "/inventory/stock-issues/save",
    itemTitle: "Issued Items",
    header: [fDate(), fAccount()],
    itemFields: [fItem(), fLoc("loc", "From Location"), fQty(), fRate(), fRemarks()],
    build: (h, items) => ({
      date: h.date,
      chart_of_account: h.chart_of_account || null,
      items: items
        .filter((it) => has(it.item) && has(it.loc_id))
        .map((it) => {
          const l = loc(it, "loc");
          return {
            item: it.item,
            location_type: l.type,
            location_id: l.id,
            batch: l.batch,
            quantity: it.quantity || "0",
            rate: it.rate || "0",
            remarks: it.remarks || "",
          };
        }),
    }),
  },

  // General Purchase — supplier bill with per-warehouse item lines.
  "purchase-general-purchases": {
    resourceKey: "purchase-general-purchases",
    title: "General Purchase",
    savePath: "/purchase/general-purchases/save",
    itemTitle: "Items",
    header: [
      fDate(),
      fSupplier(true),
      fText("bill_no", "Bill No."),
      fText("dc_no", "DC No."),
      {
        name: "calculation_based_on", label: "Calculate On", type: "toggle",
        options: [
          { value: "Sent Quantity", label: "Sent Qty" },
          { value: "Received Quantity", label: "Received Qty" },
        ],
      },
      fFreightType(),
      fDec("freight_amount", "Freight Amount"),
      fText("remarks", "Remarks"),
    ],
    itemFields: [
      fItem(),
      fWarehouse("farm_warehouse", "Store", true),
      fText("unit", "Unit"),
      fDec("sent_qty", "Sent Qty"),
      fDec("rcv_qty", "Received Qty"),
      fDec("free_qty", "Free Qty"),
      fDec("rate", "Rate"),
      fDec("discount_percent", "Discount %"),
      fDec("gst_percent", "GST %"),
    ],
    build: (h, items) => ({
      date: h.date,
      supplier: h.supplier || null,
      bill_no: h.bill_no || "",
      dc_no: h.dc_no || "",
      calculation_based_on: h.calculation_based_on || "Sent Quantity",
      freight_type: h.freight_type || "Extra",
      freight_amount: h.freight_amount || "0",
      remarks: h.remarks || "",
      items: items
        .filter((it) => has(it.item) && has(it.farm_warehouse))
        .map((it) => ({
          item: it.item,
          farm_warehouse: it.farm_warehouse,
          unit: it.unit || "",
          sent_qty: it.sent_qty || "0",
          rcv_qty: it.rcv_qty || "0",
          free_qty: it.free_qty || "0",
          rate: it.rate || "0",
          discount_percent: it.discount_percent || "0",
          discount_amount: "0",
          gst_percent: it.gst_percent || "0",
        })),
    }),
  },

  // Chicks Purchase — one item/hatchery, per-warehouse receiving lines.
  "purchase-chicks-purchases": {
    resourceKey: "purchase-chicks-purchases",
    title: "Chicks Purchase",
    savePath: "/purchase/chicks-purchases/save",
    itemTitle: "Receiving Lines",
    header: [
      fDate(),
      fSupplier(true),
      { name: "hatchery", label: "Hatchery", type: "select", optionsPath: "/hatchery/hatcheries/", optionLabelKeys: ["hatchery_name"] },
      { ...fItem(), required: false },
      fText("bill_no", "Bill No."),
      fText("dc_no", "DC No."),
      fFreightType(),
      fDec("freight_amount", "Freight Amount"),
      fText("remarks", "Remarks"),
    ],
    itemFields: [
      fWarehouse("farm_warehouse", "Store", true),
      fDec("sent_qty", "Sent Qty"),
      fDec("mortality", "Mortality"),
      fDec("shortage", "Shortage"),
      fDec("weaks", "Weaks"),
      fDec("excess_qty", "Excess Qty"),
      fDec("rate", "Rate"),
      fText("batch", "Batch"),
    ],
    build: (h, items) => ({
      date: h.date,
      supplier: h.supplier || null,
      hatchery: h.hatchery || null,
      item: h.item || null,
      bill_no: h.bill_no || "",
      dc_no: h.dc_no || "",
      freight_type: h.freight_type || "Extra",
      freight_amount: h.freight_amount || "0",
      remarks: h.remarks || "",
      items: items
        .filter((it) => has(it.farm_warehouse))
        .map((it) => ({
          farm_warehouse: it.farm_warehouse,
          sent_qty: it.sent_qty || "0",
          sent_free_percent: "0",
          rcv_free_percent: "0",
          mortality: it.mortality || "0",
          shortage: it.shortage || "0",
          weaks: it.weaks || "0",
          excess_qty: it.excess_qty || "0",
          rate: it.rate || "0",
          batch: it.batch || "",
        })),
    }),
  },

  // Supplier Payment — a voucher with one or more allocation lines.
  "purchase-supplier-payments": {
    resourceKey: "purchase-supplier-payments",
    title: "Supplier Payment",
    savePath: "/purchase/supplier-payments/save",
    itemTitle: "Payment Lines",
    header: [fDate(), fWarehouse("location", "Location", true)],
    itemFields: [
      fSupplier(true),
      {
        name: "mode", label: "Mode", type: "toggle",
        options: [
          { value: "Cash", label: "Cash" },
          { value: "Bank Transfer", label: "Bank Transfer" },
          { value: "Cheque", label: "Cheque" },
          { value: "UPI", label: "UPI" },
          { value: "Card", label: "Card" },
        ],
      },
      fAccount("pay_account", "Pay Account", true),
      fDec("amount", "Amount", true),
      fDec("bank_charges", "Bank Charges"),
      fText("reference_no", "Reference No."),
      fText("remarks", "Remarks"),
    ],
    build: (h, items) => ({
      date: h.date,
      location: h.location || null,
      lines: items
        .filter((it) => has(it.supplier) && has(it.pay_account) && has(it.amount))
        .map((it) => ({
          supplier: it.supplier,
          mode: it.mode || "Cash",
          pay_account: it.pay_account,
          amount: it.amount || "0",
          bank_charges: it.bank_charges || "0",
          reference_no: it.reference_no || "",
          remarks: it.remarks || "",
        })),
    }),
  },

  // Sales Invoice — customer bill with taxable item lines (GST computed server-side).
  "sales-invoices": {
    resourceKey: "sales-invoices",
    title: "Sales Invoice",
    savePath: "/sales/invoices/save",
    itemTitle: "Items",
    header: [
      fDate(),
      { name: "customer", label: "Customer", type: "select", optionsPath: "/customers/", optionLabelKeys: ["name", "code"], required: true },
      fText("reference_no", "Reference No."),
      fText("place_of_supply", "Place of Supply"),
      fText("vehicle_no", "Vehicle No."),
      fDec("other_charges_amount", "Other Charges"),
      fText("remarks", "Remarks"),
    ],
    itemFields: [
      fItem(),
      fText("uom", "UOM"),
      fDec("quantity", "Quantity"),
      fDec("free_qty", "Free Qty"),
      fDec("rate", "Rate"),
      fDec("discount_percent", "Discount %"),
      fDec("gst_percent", "GST %"),
      fText("batch_no", "Batch No."),
      fText("hsn_sac", "HSN/SAC"),
    ],
    build: (h, items) => ({
      transaction_type: "Sales Invoice",
      date: h.date,
      customer: h.customer || null,
      reference_no: h.reference_no || "",
      place_of_supply: h.place_of_supply || "",
      vehicle_no: h.vehicle_no || "",
      other_charges_amount: h.other_charges_amount || "0",
      remarks: h.remarks || "",
      items: items
        .filter((it) => has(it.item))
        .map((it) => ({
          item: it.item,
          uom: it.uom || "",
          quantity: it.quantity || "0",
          free_qty: it.free_qty || "0",
          rate: it.rate || "0",
          discount_percent: it.discount_percent || "0",
          gst_percent: it.gst_percent || "0",
          batch_no: it.batch_no || "",
          hsn_sac: it.hsn_sac || "",
        })),
    }),
  },

  // Sales Receipt — money received; each line is its own receipt voucher.
  "sales-receipts": {
    resourceKey: "sales-receipts",
    title: "Sales Receipt",
    savePath: "/sales/receipts/save",
    itemTitle: "Receipts",
    header: [fDate(), fWarehouse("location", "Location", true)],
    itemFields: [
      { name: "customer", label: "Customer", type: "select", optionsPath: "/customers/", optionLabelKeys: ["name", "code"], required: true },
      {
        name: "mode", label: "Mode", type: "toggle",
        options: [
          { value: "Cash", label: "Cash" },
          { value: "Bank Transfer", label: "Bank Transfer" },
          { value: "Cheque", label: "Cheque" },
          { value: "UPI", label: "UPI" },
          { value: "Card", label: "Card" },
        ],
      },
      fAccount("receipt_account", "Receipt Account", true),
      fDec("amount", "Amount", true),
      fText("reference_no", "Reference No."),
      fText("remarks", "Remarks"),
    ],
    build: (h, items) => ({
      rows: items
        .filter((it) => has(it.customer))
        .map((it) => ({
          date: h.date,
          location: h.location || null,
          customer: it.customer,
          mode: it.mode || "Cash",
          receipt_account: it.receipt_account || null,
          amount: it.amount || "0",
          reference_no: it.reference_no || "",
          remarks: it.remarks || "",
        })),
    }),
    // Edit updates one receipt — flat, not `{rows:[…]}`.
    buildEdit: (h, items) => {
      const it = items[0] ?? {};
      return {
        date: h.date,
        location: h.location || null,
        customer: it.customer,
        mode: it.mode || "Cash",
        receipt_account: it.receipt_account || null,
        amount: it.amount || "0",
        reference_no: it.reference_no || "",
        remarks: it.remarks || "",
      };
    },
  },

  // Stock Receive — per-line location (received into warehouse/farm).
  "inventory-stock-receives": {
    resourceKey: "inventory-stock-receives",
    title: "Stock Receive",
    savePath: "/inventory/stock-receives/save",
    itemTitle: "Received Items",
    header: [fDate(), fAccount()],
    itemFields: [fItem(), fLoc("loc", "Into Location"), fQty(), fRate(), fRemarks()],
    build: (h, items) => ({
      date: h.date,
      chart_of_account: h.chart_of_account || null,
      items: items
        .filter((it) => has(it.item) && has(it.loc_id))
        .map((it) => {
          const l = loc(it, "loc");
          return {
            item: it.item,
            location_type: l.type,
            location_id: l.id,
            batch: l.batch,
            quantity: it.quantity || "0",
            rate: it.rate || "0",
            remarks: it.remarks || "",
          };
        }),
    }),
  },
};

export const WAREHOUSE_OPTIONS_PATH = WAREHOUSE_PATH;
export const FARM_OPTIONS_PATH = FARM_PATH;
export const BATCH_OPTIONS_PATH = BATCH_PATH;

/** Whether a resource is authored via the document (header+items) form. */
export function isDocumentForm(resourceKey: string): boolean {
  return resourceKey in DOCUMENTS;
}
