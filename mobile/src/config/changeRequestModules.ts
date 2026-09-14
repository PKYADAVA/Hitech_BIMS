/**
 * resourceKey -> the module key registered in the web's
 * CHANGE_REQUEST_HANDLERS (hatchery/change_requests.py).
 *
 * A resource listed here gets the approval-queue fallbacks when the signed-in
 * user lacks the matching right: "Request Deletion" instead of Delete, and —
 * for the modules in REQUEST_EDIT_MODULES below — "Request Edit" instead of
 * Edit. Everything else keeps showing nothing rather than a button that would
 * 400 on a module the backend has no handler for.
 *
 * Kept in step with the web by user/tests/test_mobile_change_requests.py,
 * which walks the registered handlers and fails when this map falls behind —
 * it was written for the first nine modules and quietly missed the sixteen
 * added since.
 */
export const CHANGE_REQUEST_MODULE: Record<string, string> = {
  // Broiler
  "broiler-bird-sales": "bird_sale",
  "broiler-sale-receipts": "bird_sale_receipt",
  "broiler-chicks-placement": "chicks_placement",
  "broiler-daily-entries": "daily_entry",
  "broiler-farm-location-capture": "farm_location_capture",
  "broiler-medicine-vaccine": "medicine_entry",
  // Hatchery
  "hatchery-egg-purchases": "egg_purchase",
  "hatchery-egg-gradings": "egg_grading",
  "hatchery-delivery-challans": "delivery_challan",
  "hatchery-hatch-entries": "hatch_entry",
  "hatchery-chick-sales": "chick_sale",
  "hatchery-hatch-settings": "hatchery",
  "hatchery-tray-settings": "tray_set",
  // Inventory
  "inventory-adjustments": "inventory_adjustment",
  "inventory-medicine-transfers": "medicine_transfer",
  "inventory-stock-issues": "stock_issue",
  "inventory-stock-receives": "stock_receive",
  "inventory-stock-transfers": "stock_transfer",
  // Purchase
  "purchase-chicks-purchases": "chicks_purchase",
  "purchase-credit-notes": "purchase_credit_note",
  "purchase-debit-notes": "purchase_debit_note",
  "purchase-general-purchases": "general_purchase",
  "purchase-supplier-payments": "supplier_payment",
  // Sales
  "sales-invoices": "sales_invoice",
  "sales-receipts": "sales_receipt",
};

/**
 * The modules whose web register offers "Request modification" as well as
 * "Request deletion".
 *
 * Mirrored from the web rather than decided here: a proposed edit is stored as
 * a payload and replayed by the module's own save when a reviewer approves it,
 * and which modules can take that is a judgement the web register has already
 * made. Deciding it again on the phone risks queueing a request nobody can
 * safely approve.
 *
 * Seven were missing — Daily Entry, Chicks Placement, Medicine Entry and four
 * of the five inventory registers — and the test meant to catch that was
 * looking for the wrong thing. It searched each web template for the string
 * "request-edit", which is the href of the registers whose button is a link;
 * the ones that open a modal on the same page carry no such href, so the
 * check found seven of the fourteen and called the rest deliberate. It now
 * matches the button's title, which all of them share.
 */
export const REQUEST_EDIT_MODULES = new Set<string>([
  "bird_sale",
  "bird_sale_receipt",
  "chicks_placement",
  "daily_entry",
  "farm_location_capture",
  "inventory_adjustment",
  "medicine_entry",
  "medicine_transfer",
  "stock_issue",
  "stock_receive",
  "chick_sale",
  "delivery_challan",
  "egg_grading",
  "egg_purchase",
  "hatch_entry",
  "hatchery",
  "tray_set",
  "stock_transfer",
  "chicks_purchase",
  "purchase_credit_note",
  "purchase_debit_note",
  "general_purchase",
  "supplier_payment",
  "sales_invoice",
  "sales_receipt",
]);

/** The module key to raise an edit request against, or undefined if this
 *  resource has no edit-approval route. */
export function editRequestModule(resourceKey: string): string | undefined {
  const module = CHANGE_REQUEST_MODULE[resourceKey];
  return module && REQUEST_EDIT_MODULES.has(module) ? module : undefined;
}
