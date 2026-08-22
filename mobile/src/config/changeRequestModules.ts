/**
 * resourceKey -> the module key registered in the web's
 * CHANGE_REQUEST_HANDLERS (hatchery/change_requests.py).
 *
 * Only a resource listed here gets the "Request deletion" fallback when the
 * signed-in user lacks the delete right on it — everything else keeps
 * showing nothing, the way it always did, rather than a button that would
 * 400 on a module the backend has no handler for.
 */
export const CHANGE_REQUEST_MODULE: Record<string, string> = {
  "broiler-bird-sales": "bird_sale",
  "broiler-sale-receipts": "bird_sale_receipt",
  "hatchery-egg-purchases": "egg_purchase",
  "hatchery-egg-gradings": "egg_grading",
  "hatchery-delivery-challans": "delivery_challan",
  "hatchery-hatch-entries": "hatch_entry",
  "hatchery-chick-sales": "chick_sale",
  "hatchery-hatch-settings": "hatchery",
  "hatchery-tray-settings": "tray_set",
};
