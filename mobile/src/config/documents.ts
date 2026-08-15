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
import { farmBatches, stockTransferItem, stockTransferStock } from "@/api/lookups";

export type DocFieldType =
  | "text" | "date" | "decimal" | "number" | "select" | "toggle" | "location"
  /** Multi-line, with a character budget shown as you type. */
  | "textarea"
  /** Derived and not editable — shown so the row reads complete. */
  | "readonly";

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
  /** textarea: character budget, shown as a counter. */
  maxLength?: number;
  /** Placeholder for a field the user does not fill in. */
  placeholder?: string;
  /** Lay this field beside the previous one instead of under it. */
  half?: boolean;
  /**
   * Options that depend on another field of the same row.
   *
   * A farm's batches are not a list endpoint the picker can be pointed at —
   * they only exist once a farm is chosen. `on` names the field that decides
   * them; the screen reloads and clears the value whenever it moves, so a
   * batch can never be left over from the farm before it.
   */
  dynamicOptions?: {
    on: string;
    load: (value: string) => Promise<{ value: string; label: string }[]>;
    /** Prompt while `on` is still empty. */
    emptyHint?: string;
  };
}

/**
 * A titled group inside an item card.
 *
 * A stock transfer row carries three unrelated things — what is moving, where
 * it is going, and who is driving it — and read as one flat list of ten fields
 * they blur together. `tone` picks the heading colour so the groups are
 * distinguishable at a glance rather than by reading each label.
 */
export interface DocSection {
  title: string;
  tone: DocTone;
  fields: DocField[];
  /** MaterialCommunityIcons name shown in the heading's chip. Sections are
   *  numbered wherever one is given, so a long card can be talked about. */
  icon?: string;
}

export type DocTone = "item" | "location" | "logistics" | "source" | "quantity" | "pricing";

type Dict = Record<string, string>;

export interface DocConfig {
  resourceKey: string;
  title: string;
  savePath: string;
  itemTitle: string;
  /** Heading above the header card; omitted leaves it untitled. */
  headerTitle?: string;
  /** Singular noun for the row counter — "1 Row", "2 Rows". */
  itemNoun?: string;
  header: DocField[];
  itemFields: DocField[];
  /**
   * Item fields grouped under titled headings. When present the card renders
   * these instead of `itemFields`, which stays the flat fallback every other
   * document still uses.
   */
  itemSections?: DocSection[];
  /**
   * Derived values for a row, recomputed on every edit to it.
   *
   * The web forms carry the same arithmetic in a `recalc` handler — placement
   * quantity from what was ordered less what did not arrive, amount from
   * quantity by rate. Returning the fields rather than mutating keeps a
   * readonly box and the figure that will be saved the same number.
   */
  compute?: (row: Dict, header: Dict) => Dict;
  /**
   * Server-side fill for a row: what an item costs, what is in stock.
   *
   * `on` names the fields that invalidate it, so a document says what its own
   * lookups depend on instead of the screen hard-coding a resourceKey — which
   * is what it did, and meant a second document with lookups could not have
   * them. Advisory: a failure leaves the row usable and the save re-checks.
   */
  derive?: {
    on: string[];
    run: (row: Dict, header: Dict) => Promise<Dict>;
  };
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
// Three states now, so a toggle no longer covers it. The values are the ones
// the server stores: "Extra" and "Included in Bill" were retired, and a form
// still posting either is rejected rather than quietly filed under a freight
// arrangement nobody chose.
const fFreightType = (): DocField => ({
  name: "freight_type", label: "Freight Type", type: "select",
  options: [
    { value: "No Freight", label: "No Freight" },
    { value: "Freight Included", label: "Freight Included" },
    { value: "Freight Extra", label: "Freight Extra" },
  ],
});
// Which bill the carriage lands on. Only meaningful for freight charged on
// top — the server forces it back for the other two, so a phone that sends
// the default does no harm.
const fFreightSettlement = (): DocField => ({
  name: "freight_settlement", label: "Freight Settlement", type: "select",
  options: [
    { value: "In Purchase Bill", label: "Included in Purchase Bill" },
    { value: "Separate Bill", label: "Separate Freight Bill" },
  ],
});
const fText = (name: string, label: string): DocField => ({ name, label, type: "text" });
const fDec = (name: string, label: string, required = false): DocField => ({ name, label, type: "decimal", required });

/* ------------------------------ documents ------------------------------- */

/** Whole chicks, floored at zero — a placement cannot be negative, and the
 *  web form clamps the same way. */
const chicksInt = (v: string) => Math.max(Math.trunc(Number(v) || 0), 0);

export const DOCUMENTS: Record<string, DocConfig> = {
  /**
   * Chicks Placement — day-old chicks arriving from a hatchery or supplier and
   * going onto a farm.
   *
   * Saved as a Stock Transfer, which is what it is: stock leaving a warehouse
   * and landing on a flock. The dedicated form exists because the transfer
   * grid cannot ask the questions a placement needs — how many were ordered
   * against how many actually walked off the lorry — and because the four
   * shortfall columns are the whole point of recording a placement separately.
   *
   * Every record carries its own date and DC number, as the web grid's rows
   * do: one run of the form files several lorries, and they did not all arrive
   * on the same challan.
   */
  "broiler-chicks-placement": {
    resourceKey: "broiler-chicks-placement",
    title: "Chicks Placement",
    savePath: "/inventory/stock-transfers/save",
    itemTitle: "Chicks Placement Records",
    itemNoun: "Entry",
    header: [],
    itemSections: [
      {
        title: "Source & Destination",
        tone: "source",
        icon: "bird",
        fields: [
          { ...fDate(), half: true },
          { name: "dc_no", label: "DC No.", type: "text", placeholder: "Enter DC No.", half: true },
          { name: "source", label: "Source Hatchery / Supplier", type: "select",
            optionsPath: "/broiler/chicks-sources", optionLabelKeys: ["name"], required: true,
            placeholder: "Select Supplier / Hatchery" },
          { ...fWarehouse("from_id", "From Warehouse", true), placeholder: "Select Warehouse" },
          { name: "to_id", label: "To Farm", type: "select", optionsPath: FARM_PATH,
            optionLabelKeys: ["farm_name", "farm_code"], required: true,
            placeholder: "Select Farm", half: true },
          { name: "to_batch", label: "Batch", type: "select", half: true,
            placeholder: "Select Batch",
            dynamicOptions: {
              on: "to_id",
              emptyHint: "Select a farm first",
              load: async (farmId) => (await farmBatches(farmId)).map((b) => ({
                value: String(b.id),
                label: b.is_active ? `${b.batch_name} (Active)` : b.batch_name,
              })),
            } },
        ],
      },
      {
        title: "Chicks & Quantities",
        tone: "quantity",
        icon: "package-variant-closed",
        fields: [
          { name: "item", label: "Chicks Item", type: "select",
            optionsPath: "/broiler/chick-items", optionLabelKeys: ["description", "item_code"],
            required: true, placeholder: "Select Item", half: true },
          { name: "stock_label", label: "Item Stock", type: "readonly",
            placeholder: "—", half: true },
          { name: "chicks_ordered", label: "Chicks Ordered", type: "number",
            required: true, half: true },
          { name: "transit_mortality", label: "Transit Mortality", type: "number", half: true },
          { name: "shortage", label: "Shortage", type: "number", half: true },
          { name: "culls", label: "Culls", type: "number", half: true },
          { name: "quantity", label: "Placement Qty (Auto)", type: "readonly", placeholder: "0" },
        ],
      },
      {
        title: "Pricing & Logistics",
        tone: "pricing",
        icon: "currency-inr",
        fields: [
          { name: "rate", label: "Rate (₹ per Chick)", type: "decimal",
            placeholder: "Rate per Chick", half: true },
          { name: "amount_label", label: "Amount (Auto)", type: "readonly",
            placeholder: "0.00", half: true },
          { name: "vehicle_no", label: "Vehicle No.", type: "text",
            placeholder: "Vehicle No.", half: true },
          { name: "driver_name", label: "Driver Name", type: "text",
            placeholder: "Driver Name", half: true },
          { name: "remarks", label: "Remarks", type: "textarea", maxLength: 200,
            placeholder: "Add placement / chick notes…" },
        ],
      },
    ],
    itemFields: [fDate(), fItem(), fQty(), fRate(), fRemarks()],

    // Placement Qty is the only figure that reaches stock: what was ordered,
    // less what died in transit, went missing, or was culled on arrival. The
    // other three are recorded for the claim against the hatchery, never
    // posted. Mirrors the web form's recalcPlacementQty/recalcAmount.
    compute: (row) => {
      const qty = Math.max(
        chicksInt(row.chicks_ordered) - chicksInt(row.transit_mortality)
          - chicksInt(row.shortage) - chicksInt(row.culls),
        0
      );
      return {
        quantity: String(qty),
        amount_label: (qty * (Number(row.rate) || 0)).toFixed(2),
      };
    },

    derive: {
      on: ["item", "from_id", "date"],
      run: async (row) => {
        const out: Dict = {};
        if (!row.item) return out;
        try {
          const info = await stockTransferItem(row.item, row.date);
          // The price master's rate for that date, as the web form fills it —
          // left editable, because a lorry is sometimes billed differently.
          if (!row.rate && !info.price_missing) out.rate = info.rate || "";
        } catch {
          /* advisory */
        }
        if (row.from_id && row.date) {
          try {
            out.stock_label = await stockTransferStock("warehouse", row.from_id, row.item, row.date);
          } catch {
            /* advisory */
          }
        }
        return out;
      },
    },

    build: (_h, items) => ({
      rows: items
        .filter((it) => has(it.item) && has(it.source) && has(it.from_id) && has(it.to_id))
        .map((it) => ({
          date: it.date,
          dc_no: it.dc_no || "",
          source: it.source,
          item: it.item,
          chicks_ordered: it.chicks_ordered || "0",
          transit_mortality: it.transit_mortality || "0",
          shortage: it.shortage || "0",
          culls: it.culls || "0",
          quantity: it.quantity || "0",
          rate: it.rate || "0",
          purchase_rate: it.rate || "0",
          from_location_type: "warehouse",
          from_location_id: it.from_id,
          to_location_type: "farm",
          to_location_id: it.to_id,
          to_batch: it.to_batch || null,
          vehicle_no: it.vehicle_no || "",
          driver_name: it.driver_name || "",
          remarks: it.remarks || "",
        })),
    }),
  },

  // Stock Transfer — every row carries its own locations and logistics, as the
  // ERP grid does: one sheet can move different items between different pairs
  // of stores on the same day. Only the date and DC number are shared.
  "inventory-stock-transfers": {
    resourceKey: "inventory-stock-transfers",
    title: "Stock Transfer",
    savePath: "/inventory/stock-transfers/save",
    headerTitle: "Transaction Header",
    itemTitle: "Transfer Items",
    itemNoun: "Row",
    header: [
      { ...fDate(), half: true },
      { name: "dc_no", label: "DC No.", type: "text", placeholder: "Enter DC#", half: true },
    ],
    itemSections: [
      {
        title: "Item Details",
        tone: "item",
        fields: [
          fItem(),
          { name: "uom_label", label: "UOM", type: "readonly", placeholder: "auto", half: true },
          { name: "stock_label", label: "Available Stock", type: "readonly", placeholder: "auto", half: true },
          { ...fRate(), half: true },
          { ...fQty(), half: true },
        ],
      },
      {
        title: "Location & Movement",
        tone: "location",
        fields: [fLoc("from", "From Location"), fLoc("to", "To Location")],
      },
      {
        title: "Logistics & Remarks",
        tone: "logistics",
        fields: [
          { name: "vehicle_no", label: "Vehicle No.", type: "text",
            placeholder: "UP53 XX 1234", half: true },
          { name: "driver_name", label: "Driver Name", type: "text",
            placeholder: "Driver Name", half: true },
          { name: "remarks", label: "Remarks", type: "textarea", maxLength: 200,
            placeholder: "Add transport / transfer notes" },
        ],
      },
    ],
    itemFields: [fItem(), fQty(), fRate(), fRemarks()],

    /**
     * UOM and Available Stock, which this form declared and never filled.
     *
     * Both boxes sat on their "auto" placeholder however the row was completed,
     * so the one figure that decides whether a transfer can be made — what is
     * actually at the source — was never on screen. Medicine Transfer has had
     * this since it was written; Stock Transfer simply never got it.
     *
     * The source may be a farm as well as a warehouse, so the stock is asked
     * for by the location's own type rather than assuming a warehouse.
     */
    derive: {
      on: ["item", "from_type", "from_id"],
      run: async (row, header) => {
        const out: Dict = {};
        if (!row.item) return out;
        // The date is the document's, not the row's — this form carries one
        // Date in its header. Reading row.date left it undefined, so the
        // balance was never asked for and the box kept its placeholder.
        const on = row.date || header?.date || "";
        try {
          const info = await stockTransferItem(row.item, on);
          out.uom_label = info.unit || "";
          if (!row.rate && !info.price_missing) out.rate = info.rate || "";
        } catch {
          /* advisory — a missing price must not block the row */
        }
        if (row.from_id && on) {
          try {
            out.stock_label = await stockTransferStock(
              row.from_type || "warehouse", row.from_id, row.item, on);
          } catch {
            /* advisory */
          }
        }
        return out;
      },
    },

    build: (h, items) => ({
      rows: items
        .filter((it) => has(it.item))
        .map((it) => {
          const from = loc(it, "from");
          const to = loc(it, "to");
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
            vehicle_no: it.vehicle_no || "",
            driver_name: it.driver_name || "",
            remarks: it.remarks || "",
          };
        }),
    }),
    // Edit updates one transfer record — flat row, not `{rows:[…]}`.
    buildEdit: (h, items) => {
      // Editing touches one transfer, and its locations and logistics now live
      // on the row like they do on create — reading them off the header would
      // silently blank them.
      const it = items[0] ?? {};
      const from = loc(it, "from");
      const to = loc(it, "to");
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
        vehicle_no: it.vehicle_no || "",
        driver_name: it.driver_name || "",
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
      fFreightSettlement(),
      fText("freight_transporter", "Transporter"),
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
      calculation_based_on: h.calculation_based_on || "Received Quantity",
      // No Freight, not the old "Extra": a header that never had the field
      // filled in is one where nobody said there was any carriage.
      freight_type: h.freight_type || "No Freight",
      freight_settlement: h.freight_settlement || "In Purchase Bill",
      freight_transporter: h.freight_transporter || "",
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
      fFreightSettlement(),
      fText("freight_transporter", "Transporter"),
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
      // No Freight, not the old "Extra": a header that never had the field
      // filled in is one where nobody said there was any carriage.
      freight_type: h.freight_type || "No Freight",
      freight_settlement: h.freight_settlement || "In Purchase Bill",
      freight_transporter: h.freight_transporter || "",
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
