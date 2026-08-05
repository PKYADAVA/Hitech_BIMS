/**
 * The one thing each module's header offers to create.
 *
 * The reference gives every module screen a single action beside its title —
 * "+ New Batch", "+ New Purchase" — rather than making someone walk into a
 * list first. This is that mapping.
 *
 * It lives here rather than on `ModuleConfig` so the module catalog stays a
 * description of what a module *contains*; what a header offers is a
 * navigation decision, and the two change for different reasons.
 */
import { ModuleKey } from "@/config/catalog";

export interface ModulePrimary {
  /** The resource whose create form the header opens. */
  resourceKey: string;
  /** Button text — the reference's wording, not the resource's title. */
  label: string;
}

export const MODULE_PRIMARY: Partial<Record<ModuleKey, ModulePrimary>> = {
  broiler: { resourceKey: "broiler-daily-entries", label: "New Entry" },
  hatchery: { resourceKey: "hatchery-hatch-settings", label: "New Batch" },
  inventory: { resourceKey: "inventory-stock-transfers", label: "New Transfer" },
  purchase: { resourceKey: "purchase-general-purchases", label: "New Purchase" },
  sales: { resourceKey: "sales-invoices", label: "New Invoice" },
  account: { resourceKey: "account-vouchers", label: "New Voucher" },
  // hr, user and change_requests have no single obvious thing to create from
  // the module header — an approval is raised from the record it concerns, not
  // from a menu — so they get no button rather than an arbitrary one.
};


/**
 * The one list each module's bottom bar reaches directly.
 *
 * The reference gives every module bar a shortcut of its own — "Farms" under
 * Farm Management, "Batches" under Broiler Production, "Incubators" under
 * Hatchery. This is that, one per module: the thing someone in this module
 * opens most often, which is not always the thing they create.
 *
 * A module with no obvious answer is left out and its bar stays short rather
 * than carrying a button chosen to fill the space.
 */
export interface ModuleShortcut {
  resourceKey: string;
  label: string;
  /** MaterialCommunityIcons name. */
  icon: string;
}

export const MODULE_SHORTCUT: Partial<Record<ModuleKey, ModuleShortcut>> = {
  broiler: { resourceKey: "broiler-farms", label: "Farms", icon: "home-city-outline" },
  hatchery: { resourceKey: "hatchery-hatch-entries", label: "Hatches", icon: "egg-outline" },
  inventory: { resourceKey: "inventory-items", label: "Items", icon: "package-variant-closed" },
  purchase: { resourceKey: "purchase-suppliers", label: "Suppliers", icon: "truck-outline" },
  sales: { resourceKey: "sales-invoices", label: "Invoices", icon: "file-document-outline" },
  account: { resourceKey: "account-vouchers", label: "Vouchers", icon: "book-outline" },
  hr: { resourceKey: "hr-employees", label: "Employees", icon: "account-group-outline" },
};
