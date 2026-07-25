import { http } from "./client";
import { Envelope } from "./types";

export interface ModuleActions {
  add: boolean;
  edit: boolean;
  delete: boolean;
}

export interface Permissions {
  unrestricted: boolean;
  nav_groups: string[];
  tabs: string[];
  module_actions: Record<string, ModuleActions>;
}

export type ActionKind = keyof ModuleActions;

export async function fetchPermissions(): Promise<Permissions> {
  const resp = await http.get<Envelope<Permissions>>("/auth/permissions");
  return resp.data.data;
}

/**
 * Mobile resource key → backend tab_code, for finer per-tab view gating of hub
 * tiles. Resources without an entry fall back to module-level access (shown
 * whenever the module itself is accessible). Line-item children aren't listed
 * (they render inside a parent, not the hub).
 */
export const RESOURCE_TABS: Record<string, string> = {
  // Broiler
  "broiler-daily-entries": "daily_entry_list",
  "broiler-medicine-vaccine": "medicine_entry_list",
  "broiler-bird-sales": "bird_sale_list",
  "broiler-sale-receipts": "bird_sale_receipt_list",
  "broiler-farms": "branch_farm",
  "broiler-sheds": "broiler_farm_shed",
  "broiler-batches": "broiler_batch",
  "broiler-farmer-groups": "farmer_group",
  "broiler-regions": "region",
  "broiler-branches": "branch_template",
  "broiler-lines": "broiler_line",
  "broiler-supervisors": "supervisor_template",
  "broiler-breeds": "breed",
  "broiler-breed-standards": "breed_standard",
  "broiler-diseases": "broiler_disease",
  "broiler-growing-charges": "growing_charge",
  "broiler-gc-settlements": "gc_settlement",
  // Hatchery
  "hatchery-egg-purchases": "egg_purchase_list",
  "hatchery-egg-gradings": "egg_grading_list",
  "hatchery-hatch-settings": "hatchery_list",
  "hatchery-tray-settings": "tray_set_list",
  "hatchery-hatch-entries": "hatch_entry_list",
  "hatchery-chick-sales": "chick_sale_list",
  "hatchery-delivery-challans": "delivery_challan_list",
  "hatchery-expenses": "hatchery_expense_list",
  "hatchery-expense-types": "expense_type_list",
  "hatchery-hatcheries": "hatchery_master_list",
  "hatchery-setters": "setter_list",
  "hatchery-hatchers": "hatcher_list",
  // Sales
  "sales-invoices": "sales_invoice_list",
  "sales-customers": "customer",
  "sales-customer-groups": "customer_groups",
  "sales-prices": "sales_price_master",
  // Purchase
  "purchase-general-purchases": "general_purchase_list",
  "purchase-chicks-purchases": "chicks_purchase_list",
  "purchase-supplier-payments": "payment_list",
  "purchase-debit-notes": "debit_note_list",
  "purchase-credit-notes": "credit_note_list",
  "purchase-suppliers": "supplier",
  "purchase-vendor-groups": "vendor_groups",
  "purchase-tax-masters": "tax_master",
  // HR
  "hr-employees": "employee_list",
  "hr-attendance": "employee_attendance",
  "hr-leaves": "leave_employee",
  "hr-payroll": "payroll",
  "hr-designations": "designation",
  "hr-groups": "employee_group",
  // Users
  "user-users": "create_user",
  "user-groups": "user_groups",
  "user-group-permissions": "assign_groups",
  // SMS
  "sms-templates": "sms_templates",
  "sms-messages": "sms_history",
  "sms-settings": "sms_settings",
};

/** Mobile module key → backend nav group key (SMS lives under "notifications"). */
export const MODULE_NAV: Record<string, string> = {
  broiler: "broiler",
  hatchery: "hatchery",
  sms: "notifications",
  account: "account",
  inventory: "inventory",
  sales: "sales",
  purchase: "purchase",
  hr: "hr",
  user: "user",
};
