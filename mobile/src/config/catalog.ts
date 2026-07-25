/**
 * Resource catalog — the single source of truth that maps the web app's
 * broiler & hatchery modules onto the mobile API.
 *
 * Each entry declares how a resource is listed (icon, accent, the card view for
 * one row) and searched. List + detail screens are fully generic and read from
 * here, so adding a screen is a config entry — no new component.
 *
 * FKs come back from the `__all__` serializers as raw ids (no `_name` fields),
 * so cards lead with each record's own rich scalar data (numbers, dates,
 * amounts) — the meaningful, self-contained parts of a transaction.
 */
import { Row } from "@/api/types";
import { BadgeTone } from "@/components/ui";
import { colors } from "@/theme";
import { formatDate, formatMoney, formatNumber, joinParts, pick } from "@/utils/format";

export type ModuleKey = "broiler" | "hatchery" | "sms" | "account" | "inventory";

export interface CardView {
  title: string;
  subtitle?: string;
  trailing?: { value: string; caption?: string };
  badge?: { label: string; tone: BadgeTone };
}

/** A child collection shown inside a parent's detail (line items), filtered by FK. */
export interface ChildConfig {
  resourceKey: string;
  fkParam: string; // e.g. "egg_purchase" → /child/?egg_purchase=<parentId>
}

export interface ResourceConfig {
  key: string;
  module: ModuleKey;
  path: string;
  title: string; // plural, e.g. "Daily Entries"
  singular: string;
  icon: string;
  accent: string;
  emptyMessage: string;
  searchKeys: string[];
  card: (row: Row) => CardView;
  children?: ChildConfig[];
}

export interface ModuleSection {
  title: string;
  resourceKeys: string[];
}

export interface ModuleConfig {
  key: ModuleKey;
  title: string;
  tagline: string;
  icon: string;
  color: string;
  colorLight: string;
  sections: ModuleSection[];
}

/* ----------------------------- Broiler ---------------------------------- */

const B = colors.broiler;

const broilerResources: ResourceConfig[] = [
  {
    key: "broiler-daily-entries",
    module: "broiler",
    path: "/broiler/daily-entries/",
    title: "Daily Entries",
    singular: "Daily Entry",
    icon: "📋",
    accent: B,
    emptyMessage: "No daily entries yet.",
    searchKeys: ["entry_no", "remarks"],
    card: (r) => ({
      title: pick(r, ["entry_no"], `Entry #${r.id}`),
      subtitle: joinParts([pick(r, ["farm_label"]), formatDate(r.date)]),
      trailing: !isBlank(r.avg_weight_gms)
        ? { value: `${formatNumber(r.avg_weight_gms)} g`, caption: "avg wt" }
        : undefined,
      badge:
        Number(r.mortality) > 0
          ? { label: `${r.mortality} mort`, tone: "danger" }
          : { label: "0 mort", tone: "success" },
    }),
  },
  {
    key: "broiler-medicine-vaccine",
    module: "broiler",
    path: "/broiler/medicine-vaccine-entries/",
    title: "Medicine & Vaccine",
    singular: "Medicine / Vaccine Entry",
    icon: "💉",
    accent: B,
    emptyMessage: "No medicine / vaccine entries yet.",
    searchKeys: ["entry_no", "remarks"],
    card: (r) => ({
      title: pick(r, ["entry_no"], `Entry #${r.id}`),
      subtitle: joinParts([pick(r, ["farm_label", "item_label"]), formatDate(r.date)]),
      trailing: !isBlank(r.qty) ? { value: formatNumber(r.qty), caption: "qty" } : undefined,
    }),
  },
  {
    key: "broiler-bird-sales",
    module: "broiler",
    path: "/broiler/bird-sales/",
    title: "Bird Sales",
    singular: "Bird Sale",
    icon: "🚚",
    accent: B,
    emptyMessage: "No bird sales yet.",
    searchKeys: ["sale_no", "doc_no", "vehicle", "driver"],
    card: (r) => ({
      title: pick(r, ["sale_no"], `Sale #${r.id}`),
      subtitle: joinParts([
        pick(r, ["customer_label", "farmer_label"]),
        formatDate(r.date),
        !isBlank(r.birds) ? `${formatNumber(r.birds)} birds` : "",
      ]),
      trailing: !isBlank(r.amount) ? { value: formatMoney(r.amount) } : undefined,
      badge: !isBlank(r.sale_type)
        ? { label: String(r.sale_type), tone: "info" }
        : undefined,
    }),
  },
  {
    key: "broiler-sale-receipts",
    module: "broiler",
    path: "/broiler/bird-sale-receipts/",
    title: "Sale Receipts",
    singular: "Bird Sale Receipt",
    icon: "🧾",
    accent: B,
    emptyMessage: "No sale receipts yet.",
    searchKeys: ["receipt_no", "reference_no"],
    card: (r) => ({
      title: pick(r, ["receipt_no"], `Receipt #${r.id}`),
      subtitle: joinParts([pick(r, ["customer_label", "farmer_label"]), formatDate(r.date), pick(r, ["mode"])]),
      trailing: !isBlank(r.amount) ? { value: formatMoney(r.amount) } : undefined,
    }),
  },
  {
    key: "broiler-farms",
    module: "broiler",
    path: "/broiler/farms/",
    title: "Farms",
    singular: "Farm",
    icon: "🏠",
    accent: B,
    emptyMessage: "No farms found.",
    searchKeys: ["farm_name", "farm_code", "district", "area"],
    card: (r) => ({
      title: pick(r, ["farm_name", "farm_code"], `Farm #${r.id}`),
      subtitle: joinParts([pick(r, ["district"]), pick(r, ["area"]), pick(r, ["line"])]),
      trailing: !isBlank(r.farm_capacity)
        ? { value: formatNumber(r.farm_capacity), caption: "capacity" }
        : undefined,
    }),
  },
  {
    key: "broiler-batches",
    module: "broiler",
    path: "/broiler/batches/",
    title: "Batches",
    singular: "Batch",
    icon: "📦",
    accent: B,
    emptyMessage: "No batches found.",
    searchKeys: ["batch_name", "lot_no", "book_number"],
    card: (r) => ({
      title: pick(r, ["batch_name"], `Batch #${r.id}`),
      subtitle: joinParts([pick(r, ["broiler_farm_label"]), formatDate(r.start_date)]),
      badge: r.is_closed
        ? { label: "Closed", tone: "neutral" }
        : { label: "Active", tone: "success" },
    }),
  },
  {
    key: "broiler-farmers",
    module: "broiler",
    path: "/broiler/farmers/",
    title: "Farmers",
    singular: "Farmer",
    icon: "👨‍🌾",
    accent: B,
    emptyMessage: "No farmers found.",
    searchKeys: ["farmer_name", "mobile_no", "phone_no"],
    card: (r) => ({
      title: pick(r, ["farmer_name"], `Farmer #${r.id}`),
      subtitle: joinParts([pick(r, ["mobile_no", "phone_no"]), pick(r, ["usc"])]),
    }),
  },
  {
    key: "broiler-gc-settlements",
    module: "broiler",
    path: "/broiler/gc-settlements/",
    title: "GC Settlements",
    singular: "Growing Charge Settlement",
    icon: "🧾",
    accent: B,
    emptyMessage: "No settlements yet.",
    searchKeys: ["settlement_code"],
    card: (r) => ({
      title: pick(r, ["settlement_code"], `Settlement #${r.id}`),
      subtitle: joinParts([pick(r, ["batch_label", "farm_label"]), formatDate(r.gc_date)]),
      trailing: !isBlank(r.farmer_payable)
        ? { value: formatMoney(r.farmer_payable), caption: "payable" }
        : undefined,
    }),
  },
  {
    key: "broiler-farmer-groups",
    module: "broiler",
    path: "/broiler/farmer-groups/",
    title: "Farmer Groups",
    singular: "Farmer Group",
    icon: "👥",
    accent: B,
    emptyMessage: "No farmer groups found.",
    searchKeys: ["code", "description"],
    card: (r) => ({
      title: pick(r, ["code", "description"], `Group #${r.id}`),
      subtitle: pick(r, ["description"]),
      badge: activeBadge(r),
    }),
  },
  {
    key: "broiler-sheds",
    module: "broiler",
    path: "/broiler/sheds/",
    title: "Farm Sheds",
    singular: "Farm Shed",
    icon: "🏘️",
    accent: B,
    emptyMessage: "No sheds found.",
    searchKeys: ["shed_code", "shed_name", "shed_type"],
    card: (r) => ({
      title: pick(r, ["shed_name", "shed_code"], `Shed #${r.id}`),
      subtitle: joinParts([pick(r, ["shed_type"]), pick(r, ["unit_no"]) && `Unit ${pick(r, ["unit_no"])}`]),
      trailing: !isBlank(r.sq_feet) ? { value: formatNumber(r.sq_feet), caption: "sq ft" } : undefined,
    }),
  },
  {
    key: "broiler-regions",
    module: "broiler",
    path: "/broiler/regions/",
    title: "Regions",
    singular: "Region",
    icon: "🗺️",
    accent: B,
    emptyMessage: "No regions found.",
    searchKeys: ["code", "description"],
    card: (r) => ({
      title: pick(r, ["code", "description"], `Region #${r.id}`),
      subtitle: pick(r, ["description"]),
      badge: activeBadge(r),
    }),
  },
  {
    key: "broiler-branches",
    module: "broiler",
    path: "/broiler/branches/",
    title: "Branches",
    singular: "Branch",
    icon: "🏢",
    accent: B,
    emptyMessage: "No branches found.",
    searchKeys: ["code", "branch_name", "prefix"],
    card: (r) => ({
      title: pick(r, ["branch_name", "code"], `Branch #${r.id}`),
      subtitle: joinParts([pick(r, ["code"]), pick(r, ["prefix"]) && `Prefix ${pick(r, ["prefix"])}`]),
      badge: activeBadge(r),
    }),
  },
  {
    key: "broiler-lines",
    module: "broiler",
    path: "/broiler/lines/",
    title: "Broiler Lines",
    singular: "Broiler Line",
    icon: "🧭",
    accent: B,
    emptyMessage: "No lines found.",
    searchKeys: ["code", "description"],
    card: (r) => ({
      title: pick(r, ["code", "description"], `Line #${r.id}`),
      subtitle: pick(r, ["description"]),
      badge: activeBadge(r),
    }),
  },
  {
    key: "broiler-supervisors",
    module: "broiler",
    path: "/broiler/supervisors/",
    title: "Supervisors",
    singular: "Supervisor",
    icon: "🧑‍💼",
    accent: B,
    emptyMessage: "No supervisors found.",
    searchKeys: ["name", "phone_no", "email"],
    card: (r) => ({
      title: pick(r, ["name"], `Supervisor #${r.id}`),
      subtitle: joinParts([pick(r, ["phone_no"]), pick(r, ["email"])]),
    }),
  },
  {
    key: "broiler-breeds",
    module: "broiler",
    path: "/broiler/breeds/",
    title: "Breeds",
    singular: "Breed",
    icon: "🐣",
    accent: B,
    emptyMessage: "No breeds found.",
    searchKeys: ["code", "description"],
    card: (r) => ({
      title: pick(r, ["code", "description"], `Breed #${r.id}`),
      subtitle: pick(r, ["description"]),
      badge: activeBadge(r),
    }),
  },
  {
    key: "broiler-breed-standards",
    module: "broiler",
    path: "/broiler/breed-standards/",
    title: "Breed Standards",
    singular: "Breed Standard",
    icon: "📈",
    accent: B,
    emptyMessage: "No breed standards found.",
    searchKeys: ["code"],
    card: (r) => ({
      title: joinParts([pick(r, ["code"], `Standard #${r.id}`), !isBlank(r.age) ? `Age ${formatNumber(r.age)}` : ""]),
      subtitle: joinParts([
        !isBlank(r.body_weight) ? `${formatNumber(r.body_weight)} g` : "",
        !isBlank(r.feed_intake) ? `Feed ${formatNumber(r.feed_intake)}` : "",
      ]),
      trailing: !isBlank(r.fcr) ? { value: formatNumber(r.fcr), caption: "fcr" } : undefined,
    }),
  },
  {
    key: "broiler-diseases",
    module: "broiler",
    path: "/broiler/diseases/",
    title: "Diseases",
    singular: "Disease",
    icon: "🦠",
    accent: B,
    emptyMessage: "No diseases found.",
    searchKeys: ["disease_code", "disease_name", "symptoms"],
    card: (r) => ({
      title: pick(r, ["disease_name", "disease_code"], `Disease #${r.id}`),
      subtitle: joinParts([pick(r, ["disease_code"]), formatDate(r.diagnosed_date)]),
    }),
  },
  {
    key: "broiler-growing-charges",
    module: "broiler",
    path: "/broiler/growing-charges/",
    title: "Growing Charges",
    singular: "Growing Charge Scheme",
    icon: "💵",
    accent: B,
    emptyMessage: "No growing charge schemes found.",
    searchKeys: ["scheme_code", "schema_name"],
    card: (r) => ({
      title: pick(r, ["schema_name", "scheme_code"], `Scheme #${r.id}`),
      subtitle: joinParts([pick(r, ["scheme_code"]), rangeText(r.from_date, r.to_date)]),
    }),
  },
];

/* ----------------------------- Hatchery --------------------------------- */

const H = colors.hatchery;

const hatcheryResources: ResourceConfig[] = [
  {
    key: "hatchery-egg-purchases",
    module: "hatchery",
    path: "/hatchery/egg-purchases/",
    title: "Egg Purchases",
    singular: "Egg Purchase",
    icon: "🥚",
    accent: H,
    emptyMessage: "No egg purchases yet.",
    searchKeys: ["transaction_no", "dc_no", "vehicle", "driver"],
    card: (r) => ({
      title: pick(r, ["transaction_no"], `Purchase #${r.id}`),
      subtitle: joinParts([pick(r, ["supplier_label"]), formatDate(r.date)]),
      trailing: !isBlank(r.freight_amount)
        ? { value: formatMoney(r.freight_amount), caption: "freight" }
        : undefined,
      badge: !isBlank(r.payment_mode)
        ? { label: String(r.payment_mode), tone: "brand" }
        : undefined,
    }),
    children: [{ resourceKey: "hatchery-egg-purchase-items", fkParam: "egg_purchase" }],
  },
  {
    key: "hatchery-egg-gradings",
    module: "hatchery",
    path: "/hatchery/egg-gradings/",
    title: "Egg Grading",
    singular: "Egg Grading",
    icon: "🔬",
    accent: H,
    emptyMessage: "No egg gradings yet.",
    searchKeys: ["transaction_no"],
    card: (r) => ({
      title: pick(r, ["transaction_no"], `Grading #${r.id}`),
      subtitle: joinParts([
        pick(r, ["supplier_label"]),
        formatDate(r.date),
        !isBlank(r.broken_eggs) ? `${formatNumber(r.broken_eggs)} broken` : "",
      ]),
      trailing: !isBlank(r.quantity)
        ? { value: formatNumber(r.quantity), caption: "eggs" }
        : undefined,
    }),
  },
  {
    key: "hatchery-delivery-challans",
    module: "hatchery",
    path: "/hatchery/delivery-challans/",
    title: "Delivery Challans",
    singular: "Delivery Challan",
    icon: "🚚",
    accent: H,
    emptyMessage: "No delivery challans yet.",
    searchKeys: ["challan_no", "vehicle_no", "driver_name", "eway_bill_no"],
    card: (r) => ({
      title: pick(r, ["challan_no"], `Challan #${r.id}`),
      subtitle: joinParts([pick(r, ["customer_label"]), formatDate(r.date), pick(r, ["vehicle_no"])]),
      badge: !isBlank(r.transport_mode)
        ? { label: String(r.transport_mode), tone: "info" }
        : undefined,
    }),
    children: [{ resourceKey: "hatchery-delivery-challan-items", fkParam: "challan" }],
  },
  {
    key: "hatchery-hatch-entries",
    module: "hatchery",
    path: "/hatchery/hatch-entries/",
    title: "Hatch Entries",
    singular: "Hatch Entry",
    icon: "🐣",
    accent: H,
    emptyMessage: "No hatch entries yet.",
    searchKeys: ["transaction_no", "remarks"],
    card: (r) => ({
      title: pick(r, ["transaction_no"], `Hatch #${r.id}`),
      subtitle: joinParts([
        formatDate(r.hatch_date),
        !isBlank(r.eggs_total) ? `${formatNumber(r.eggs_total)} eggs` : "",
      ]),
      trailing: !isBlank(r.chicks_total)
        ? { value: formatNumber(r.chicks_total), caption: "chicks" }
        : undefined,
    }),
  },
  {
    key: "hatchery-chick-sales",
    module: "hatchery",
    path: "/hatchery/chick-sales/",
    title: "Chick Sales",
    singular: "Chick Sale",
    icon: "🐥",
    accent: H,
    emptyMessage: "No chick sales yet.",
    searchKeys: ["bill_no", "vehicle", "driver"],
    card: (r) => ({
      title: pick(r, ["bill_no"], `Bill #${r.id}`),
      subtitle: joinParts([pick(r, ["customer_label"]), formatDate(r.date)]),
      trailing: !isBlank(r.final_amount) ? { value: formatMoney(r.final_amount) } : undefined,
      badge: !isBlank(r.payment_mode)
        ? { label: String(r.payment_mode), tone: "brand" }
        : undefined,
    }),
    children: [{ resourceKey: "hatchery-chick-sale-items", fkParam: "sale" }],
  },
  {
    key: "hatchery-hatch-settings",
    module: "hatchery",
    path: "/hatchery/hatch-settings/",
    title: "Hatch Settings",
    singular: "Hatch Setting",
    icon: "⚙️",
    accent: H,
    emptyMessage: "No hatch settings yet.",
    searchKeys: ["setting_no", "batch_flock_no", "supplier_name"],
    card: (r) => ({
      title: pick(r, ["setting_no"], `Setting #${r.id}`),
      subtitle: joinParts([formatDate(r.setting_date), pick(r, ["batch_flock_no"])]),
      trailing: !isBlank(r.setting_qty)
        ? { value: formatNumber(r.setting_qty), caption: "set" }
        : undefined,
    }),
  },
  {
    key: "hatchery-tray-settings",
    module: "hatchery",
    path: "/hatchery/tray-settings/",
    title: "Tray Settings",
    singular: "Tray Setting",
    icon: "🧺",
    accent: H,
    emptyMessage: "No tray settings yet.",
    searchKeys: ["setting_no", "loaded_by"],
    card: (r) => ({
      title: pick(r, ["setting_no"], `Tray #${r.id}`),
      subtitle: joinParts([formatDate(r.setting_date), pick(r, ["loaded_by"])]),
    }),
  },
  {
    key: "hatchery-expenses",
    module: "hatchery",
    path: "/hatchery/expenses/",
    title: "Hatchery Expenses",
    singular: "Hatchery Expense",
    icon: "💸",
    accent: H,
    emptyMessage: "No expenses yet.",
    searchKeys: ["stage"],
    card: (r) => ({
      title: pick(r, ["expense_type_label", "stage"], `Expense #${r.id}`),
      subtitle: joinParts([pick(r, ["hatchery_label"]), pick(r, ["stage"]), formatDate(r.date)]),
      trailing: !isBlank(r.amount) ? { value: formatMoney(r.amount) } : undefined,
    }),
  },
  {
    key: "hatchery-hatcheries",
    module: "hatchery",
    path: "/hatchery/hatcheries/",
    title: "Hatcheries",
    singular: "Hatchery",
    icon: "🏭",
    accent: H,
    emptyMessage: "No hatcheries found.",
    searchKeys: ["hatchery_name", "owner_name", "state"],
    card: (r) => ({
      title: pick(r, ["hatchery_name"], `Hatchery #${r.id}`),
      subtitle: joinParts([pick(r, ["owner_name"]), pick(r, ["operation_type"])]),
      badge: activeBadge(r),
    }),
  },
  {
    key: "hatchery-setters",
    module: "hatchery",
    path: "/hatchery/setters/",
    title: "Setters",
    singular: "Setter",
    icon: "🌡️",
    accent: H,
    emptyMessage: "No setters found.",
    searchKeys: ["setter_no"],
    card: (r) => ({
      title: pick(r, ["setter_no"], `Setter #${r.id}`),
      subtitle: pick(r, ["hatchery_label"]),
      trailing: !isBlank(r.capacity)
        ? { value: formatNumber(r.capacity), caption: "cap" }
        : undefined,
      badge: activeBadge(r),
    }),
  },
  {
    key: "hatchery-hatchers",
    module: "hatchery",
    path: "/hatchery/hatchers/",
    title: "Hatchers",
    singular: "Hatcher",
    icon: "♨️",
    accent: H,
    emptyMessage: "No hatchers found.",
    searchKeys: ["hatcher_no"],
    card: (r) => ({
      title: pick(r, ["hatcher_no"], `Hatcher #${r.id}`),
      subtitle: pick(r, ["hatchery_label"]),
      trailing: !isBlank(r.capacity)
        ? { value: formatNumber(r.capacity), caption: "cap" }
        : undefined,
      badge: activeBadge(r),
    }),
  },
  {
    key: "hatchery-expense-types",
    module: "hatchery",
    path: "/hatchery/expense-types/",
    title: "Expense Types",
    singular: "Expense Type",
    icon: "🏷️",
    accent: H,
    emptyMessage: "No expense types found.",
    searchKeys: ["name"],
    card: (r) => ({
      title: pick(r, ["name"], `Type #${r.id}`),
      badge: activeBadge(r),
    }),
  },
  {
    key: "hatchery-change-requests",
    module: "hatchery",
    path: "/hatchery/change-requests/",
    title: "Change Requests",
    singular: "Change Request",
    icon: "📝",
    accent: H,
    emptyMessage: "No change requests.",
    searchKeys: ["object_label", "module"],
    card: (r) => ({
      title: pick(r, ["object_label"], `Request #${r.id}`),
      subtitle: joinParts([pick(r, ["module"]), pick(r, ["action"])]),
      badge: changeStatusBadge(r),
    }),
  },
  // --- Line items (rendered inside their parent's detail, not in the hub) ---
  {
    key: "hatchery-egg-purchase-items",
    module: "hatchery",
    path: "/hatchery/egg-purchase-items/",
    title: "Purchase Items",
    singular: "Purchase Item",
    icon: "🥚",
    accent: H,
    emptyMessage: "No line items.",
    searchKeys: [],
    card: (r) => ({
      title: pick(r, ["item_label"], `Item #${r.id}`),
      subtitle: joinParts([
        !isBlank(r.rcv_qty) ? `Rcv ${formatNumber(r.rcv_qty)}` : "",
        !isBlank(r.rate) ? `@ ${formatMoney(r.rate)}` : "",
      ]),
      trailing: !isBlank(r.total_amount) ? { value: formatMoney(r.total_amount) } : undefined,
    }),
  },
  {
    key: "hatchery-chick-sale-items",
    module: "hatchery",
    path: "/hatchery/chick-sale-items/",
    title: "Sale Items",
    singular: "Sale Item",
    icon: "🐥",
    accent: H,
    emptyMessage: "No line items.",
    searchKeys: [],
    card: (r) => ({
      title: pick(r, ["item_label"], `Item #${r.id}`),
      subtitle: joinParts([
        !isBlank(r.sale_qty) ? `Qty ${formatNumber(r.sale_qty)}` : "",
        !isBlank(r.sale_rate) ? `@ ${formatMoney(r.sale_rate)}` : "",
      ]),
      trailing: !isBlank(r.amount) ? { value: formatMoney(r.amount) } : undefined,
    }),
  },
  {
    key: "hatchery-delivery-challan-items",
    module: "hatchery",
    path: "/hatchery/delivery-challan-items/",
    title: "Challan Items",
    singular: "Challan Item",
    icon: "📦",
    accent: H,
    emptyMessage: "No line items.",
    searchKeys: [],
    card: (r) => ({
      title: pick(r, ["item_label"], `Item #${r.id}`),
      subtitle: joinParts([
        !isBlank(r.quantity) ? `Qty ${formatNumber(r.quantity)}` : "",
        !isBlank(r.price) ? `@ ${formatMoney(r.price)}` : "",
      ]),
      trailing: !isBlank(r.amount) ? { value: formatMoney(r.amount) } : undefined,
    }),
  },
];

/* ------------------------------- SMS ------------------------------------ */

const S = colors.sms;

/** Map an SMS message status to a badge tone. */
function smsStatusBadge(r: Row): CardView["badge"] {
  const status = String(r.status ?? "").toLowerCase();
  if (!status) return undefined;
  const tone: BadgeTone = /deliver|sent|success/.test(status)
    ? "success"
    : /fail|error|reject/.test(status)
    ? "danger"
    : /pending|queue|submit/.test(status)
    ? "warning"
    : "neutral";
  return { label: String(r.status), tone };
}

const smsResources: ResourceConfig[] = [
  {
    key: "sms-templates",
    module: "sms",
    path: "/sms/templates/",
    title: "Templates",
    singular: "SMS Template",
    icon: "📝",
    accent: S,
    emptyMessage: "No SMS templates found.",
    searchKeys: ["key", "name", "module", "transaction"],
    card: (r) => ({
      title: pick(r, ["name", "key"], `Template #${r.id}`),
      subtitle: joinParts([pick(r, ["module"]), pick(r, ["transaction"]), pick(r, ["sms_type"])]),
      badge: activeBadge(r),
    }),
  },
  {
    key: "sms-messages",
    module: "sms",
    path: "/sms/messages/",
    title: "History",
    singular: "SMS Message",
    icon: "✉️",
    accent: S,
    emptyMessage: "No SMS sent yet.",
    searchKeys: ["party_name", "mobile", "document_no", "template_name"],
    card: (r) => ({
      title: pick(r, ["party_name", "mobile"], `Message #${r.id}`),
      subtitle: joinParts([pick(r, ["mobile"]), pick(r, ["document_no"]), pick(r, ["module"])]),
      badge: smsStatusBadge(r),
    }),
  },
  {
    key: "sms-settings",
    module: "sms",
    path: "/sms/settings/",
    title: "Settings",
    singular: "SMS Settings",
    icon: "⚙️",
    accent: S,
    emptyMessage: "SMS settings not configured.",
    searchKeys: [],
    card: (r) => ({
      title: "SMS Gateway",
      subtitle: joinParts([pick(r, ["sender_id"]) && `Sender ${pick(r, ["sender_id"])}`, pick(r, ["default_country_code"])]),
      badge: r.enabled
        ? { label: r.mock ? "Enabled · Mock" : "Enabled", tone: r.mock ? "warning" : "success" }
        : { label: "Disabled", tone: "neutral" },
    }),
  },
];

/* ------------------------------ Account --------------------------------- */

const A = colors.account;

const accountResources: ResourceConfig[] = [
  {
    key: "account-financial-years",
    module: "account",
    path: "/account/financial-years/",
    title: "Financial Years",
    singular: "Financial Year",
    icon: "📅",
    accent: A,
    emptyMessage: "No financial years found.",
    searchKeys: ["state"],
    card: (r) => ({
      title: rangeText(r.start_date, r.end_date) || `FY #${r.id}`,
      subtitle: pick(r, ["state"]),
      badge: r.is_active
        ? { label: "Active", tone: "success" }
        : { label: String(r.state ?? "—"), tone: "neutral" },
    }),
  },
  {
    key: "account-chart-of-accounts",
    module: "account",
    path: "/account/chart-of-accounts/",
    title: "Chart of Accounts",
    singular: "Account",
    icon: "🗂️",
    accent: A,
    emptyMessage: "No accounts found.",
    searchKeys: ["code", "description"],
    card: (r) => ({
      title: pick(r, ["description", "code"], `Account #${r.id}`),
      subtitle: joinParts([pick(r, ["code"]), pick(r, ["type", "account_type_label"])]),
      trailing: !isBlank(r.opening_balance)
        ? { value: formatMoney(r.opening_balance), caption: "opening" }
        : undefined,
      badge: r.is_group
        ? { label: "Group", tone: "info" }
        : { label: "Ledger", tone: "neutral" },
    }),
  },
  {
    key: "account-bank-cash",
    module: "account",
    path: "/account/bank-cash/",
    title: "Bank / Cash",
    singular: "Bank / Cash Master",
    icon: "🏦",
    accent: A,
    emptyMessage: "No bank / cash masters found.",
    searchKeys: ["code", "name"],
    card: (r) => ({
      title: pick(r, ["name", "code"], `Master #${r.id}`),
      subtitle: joinParts([pick(r, ["code"]), pick(r, ["contact_person"])]),
      badge: r.is_cash
        ? { label: "Cash", tone: "success" }
        : { label: "Bank", tone: "brand" },
    }),
  },
  {
    key: "account-organization-centres",
    module: "account",
    path: "/account/organization-centres/",
    title: "Organization Centres",
    singular: "Organization Centre",
    icon: "🏛️",
    accent: A,
    emptyMessage: "No organization centres found.",
    searchKeys: ["code", "name", "category"],
    card: (r) => ({
      title: pick(r, ["name", "code"], `Centre #${r.id}`),
      subtitle: joinParts([pick(r, ["code"]), pick(r, ["centre_type_label"]), pick(r, ["category"])]),
      badge: activeBadge(r),
    }),
  },
  {
    key: "account-company-profiles",
    module: "account",
    path: "/account/company-profiles/",
    title: "Company Profile",
    singular: "Company Profile",
    icon: "🏢",
    accent: A,
    emptyMessage: "No company profile found.",
    searchKeys: ["name", "gstin", "pan"],
    card: (r) => ({
      title: pick(r, ["name"], `Company #${r.id}`),
      subtitle: joinParts([pick(r, ["state"]), pick(r, ["gstin"]) && `GSTIN ${pick(r, ["gstin"])}`]),
    }),
  },
  {
    key: "account-terms",
    module: "account",
    path: "/account/terms/",
    title: "Terms & Conditions",
    singular: "Terms & Conditions",
    icon: "📄",
    accent: A,
    emptyMessage: "No terms & conditions found.",
    searchKeys: ["type", "party_type"],
    card: (r) => ({
      title: pick(r, ["type"], `Terms #${r.id}`),
      subtitle: joinParts([pick(r, ["party_type"]), pick(r, ["condition"])]),
    }),
  },
  {
    key: "account-vouchers",
    module: "account",
    path: "/account/vouchers/",
    title: "Journal Vouchers",
    singular: "Voucher",
    icon: "📒",
    accent: A,
    emptyMessage: "No vouchers yet.",
    searchKeys: ["voucher_no", "reference"],
    card: (r) => ({
      title: pick(r, ["voucher_no"], `Voucher #${r.id}`),
      subtitle: joinParts([pick(r, ["voucher_type"]), formatDate(r.date), pick(r, ["reference"])]),
      trailing: !isBlank(r.total_debit) ? { value: formatMoney(r.total_debit) } : undefined,
      badge: !isBlank(r.status)
        ? { label: String(r.status), tone: /post/.test(String(r.status).toLowerCase()) ? "success" : "neutral" }
        : undefined,
    }),
  },
];

/* ----------------------------- Inventory -------------------------------- */

const I = colors.inventory;

const inventoryResources: ResourceConfig[] = [
  {
    key: "inventory-item-categories",
    module: "inventory",
    path: "/inventory/item-categories/",
    title: "Item Categories",
    singular: "Item Category",
    icon: "📁",
    accent: I,
    emptyMessage: "No item categories found.",
    searchKeys: ["code", "name"],
    card: (r) => ({
      title: pick(r, ["name"], `Category #${r.id}`),
      subtitle: pick(r, ["code"]),
    }),
  },
  {
    key: "inventory-uom",
    module: "inventory",
    path: "/inventory/uom/",
    title: "Units of Measurement",
    singular: "Unit of Measurement",
    icon: "📏",
    accent: I,
    emptyMessage: "No units found.",
    searchKeys: ["name", "symbol"],
    card: (r) => ({
      title: pick(r, ["name"], `Unit #${r.id}`),
      subtitle: pick(r, ["symbol"]),
    }),
  },
  {
    key: "inventory-sectors",
    module: "inventory",
    path: "/inventory/sectors/",
    title: "Sectors",
    singular: "Sector",
    icon: "🧭",
    accent: I,
    emptyMessage: "No sectors found.",
    searchKeys: ["code", "name"],
    card: (r) => ({
      title: pick(r, ["name"], `Sector #${r.id}`),
      subtitle: pick(r, ["code"]),
    }),
  },
  {
    key: "inventory-warehouses",
    module: "inventory",
    path: "/inventory/warehouses/",
    title: "Offices",
    singular: "Office",
    icon: "🏬",
    accent: I,
    emptyMessage: "No offices found.",
    searchKeys: ["code", "name", "location"],
    card: (r) => ({
      title: pick(r, ["name", "code"], `Office #${r.id}`),
      subtitle: joinParts([pick(r, ["code"]), pick(r, ["sector_label"]), pick(r, ["location"])]),
    }),
  },
  {
    key: "inventory-items",
    module: "inventory",
    path: "/inventory/items/",
    title: "Items",
    singular: "Item",
    icon: "📦",
    accent: I,
    emptyMessage: "No items found.",
    searchKeys: ["item_code", "description", "hsn_code"],
    card: (r) => ({
      title: pick(r, ["description", "item_code"], `Item #${r.id}`),
      subtitle: joinParts([pick(r, ["item_code"]), pick(r, ["category_label"]), pick(r, ["type"])]),
      trailing: !isBlank(r.standard_cost_per_unit)
        ? { value: formatMoney(r.standard_cost_per_unit), caption: "std cost" }
        : undefined,
    }),
  },
  {
    key: "inventory-price-list",
    module: "inventory",
    path: "/inventory/price-list/",
    title: "Item Price List",
    singular: "Item Price",
    icon: "🏷️",
    accent: I,
    emptyMessage: "No price entries found.",
    searchKeys: ["item_label"],
    card: (r) => ({
      title: pick(r, ["item_label"], `Price #${r.id}`),
      subtitle: formatDate(r.effective_date),
      trailing: !isBlank(r.price) ? { value: formatMoney(r.price) } : undefined,
    }),
  },
  {
    key: "inventory-stock-transfers",
    module: "inventory",
    path: "/inventory/stock-transfers/",
    title: "Stock Transfers",
    singular: "Stock Transfer",
    icon: "🔁",
    accent: I,
    emptyMessage: "No stock transfers yet.",
    searchKeys: ["trnum", "dc_no", "vehicle_no", "driver_name"],
    card: (r) => ({
      title: pick(r, ["trnum"], `Transfer #${r.id}`),
      subtitle: joinParts([pick(r, ["item_label"]), formatDate(r.date), pick(r, ["dc_no"])]),
      trailing: !isBlank(r.quantity) ? { value: formatNumber(r.quantity), caption: "qty" } : undefined,
    }),
  },
  {
    key: "inventory-medicine-transfers",
    module: "inventory",
    path: "/inventory/medicine-transfers/",
    title: "Medicine Transfers",
    singular: "Medicine / Vaccine Transfer",
    icon: "💉",
    accent: I,
    emptyMessage: "No medicine transfers yet.",
    searchKeys: ["trnum", "dc_no", "vehicle_no", "driver_name"],
    card: (r) => ({
      title: pick(r, ["trnum"], `Transfer #${r.id}`),
      subtitle: joinParts([formatDate(r.date), pick(r, ["dc_no"]), pick(r, ["vehicle_no"])]),
    }),
  },
  {
    key: "inventory-adjustments",
    module: "inventory",
    path: "/inventory/adjustments/",
    title: "Inventory Adjustments",
    singular: "Inventory Adjustment",
    icon: "🎚️",
    accent: I,
    emptyMessage: "No adjustments yet.",
    searchKeys: ["trnum", "bill_no"],
    card: (r) => ({
      title: pick(r, ["trnum"], `Adjustment #${r.id}`),
      subtitle: joinParts([formatDate(r.date), pick(r, ["bill_no"]), pick(r, ["warehouse_label"])]),
    }),
  },
  {
    key: "inventory-stock-issues",
    module: "inventory",
    path: "/inventory/stock-issues/",
    title: "Stock Issued",
    singular: "Stock Issue",
    icon: "📤",
    accent: I,
    emptyMessage: "No stock issues yet.",
    searchKeys: ["trnum"],
    card: (r) => ({
      title: pick(r, ["trnum"], `Issue #${r.id}`),
      subtitle: joinParts([formatDate(r.date), pick(r, ["chart_of_account_label"])]),
    }),
  },
  {
    key: "inventory-stock-receives",
    module: "inventory",
    path: "/inventory/stock-receives/",
    title: "Stock Received",
    singular: "Stock Receive",
    icon: "📥",
    accent: I,
    emptyMessage: "No stock receipts yet.",
    searchKeys: ["trnum"],
    card: (r) => ({
      title: pick(r, ["trnum"], `Receipt #${r.id}`),
      subtitle: joinParts([formatDate(r.date), pick(r, ["chart_of_account_label"])]),
    }),
  },
];

/* ----------------------------- Modules ---------------------------------- */

export const RESOURCES: Record<string, ResourceConfig> = Object.fromEntries(
  [
    ...broilerResources,
    ...hatcheryResources,
    ...smsResources,
    ...accountResources,
    ...inventoryResources,
  ].map((r) => [r.key, r])
);

export const MODULES: Record<ModuleKey, ModuleConfig> = {
  broiler: {
    key: "broiler",
    title: "Broiler",
    tagline: "Poultry farm operations",
    icon: "🐔",
    color: colors.broiler,
    colorLight: colors.broilerLight,
    sections: [
      {
        title: "Transactions",
        resourceKeys: [
          "broiler-daily-entries",
          "broiler-medicine-vaccine",
          "broiler-bird-sales",
          "broiler-sale-receipts",
        ],
      },
      {
        title: "Farms & Batches",
        resourceKeys: [
          "broiler-farms",
          "broiler-sheds",
          "broiler-batches",
          "broiler-farmers",
          "broiler-farmer-groups",
        ],
      },
      {
        title: "Organization",
        resourceKeys: [
          "broiler-regions",
          "broiler-branches",
          "broiler-lines",
          "broiler-supervisors",
        ],
      },
      {
        title: "Breeds & Charges",
        resourceKeys: [
          "broiler-breeds",
          "broiler-breed-standards",
          "broiler-diseases",
          "broiler-growing-charges",
        ],
      },
      {
        title: "Settlement",
        resourceKeys: ["broiler-gc-settlements"],
      },
    ],
  },
  hatchery: {
    key: "hatchery",
    title: "Hatchery",
    tagline: "Egg intake to chick dispatch",
    icon: "🥚",
    color: colors.hatchery,
    colorLight: colors.hatcheryLight,
    sections: [
      {
        title: "Transactions",
        resourceKeys: [
          "hatchery-egg-purchases",
          "hatchery-egg-gradings",
          "hatchery-hatch-settings",
          "hatchery-tray-settings",
          "hatchery-hatch-entries",
          "hatchery-chick-sales",
          "hatchery-delivery-challans",
        ],
      },
      {
        title: "Expenses",
        resourceKeys: ["hatchery-expenses", "hatchery-expense-types"],
      },
      {
        title: "Infrastructure",
        resourceKeys: ["hatchery-hatcheries", "hatchery-setters", "hatchery-hatchers"],
      },
      {
        title: "Approvals",
        resourceKeys: ["hatchery-change-requests"],
      },
    ],
  },
  sms: {
    key: "sms",
    title: "SMS",
    tagline: "Templates, history & settings",
    icon: "💬",
    color: colors.sms,
    colorLight: colors.smsLight,
    sections: [
      { title: "Templates", resourceKeys: ["sms-templates"] },
      { title: "Activity", resourceKeys: ["sms-messages"] },
      { title: "Configuration", resourceKeys: ["sms-settings"] },
    ],
  },
  account: {
    key: "account",
    title: "Accounts",
    tagline: "Books, masters & vouchers",
    icon: "📒",
    color: colors.account,
    colorLight: colors.accountLight,
    sections: [
      {
        title: "Masters",
        resourceKeys: [
          "account-financial-years",
          "account-chart-of-accounts",
          "account-bank-cash",
          "account-organization-centres",
          "account-company-profiles",
          "account-terms",
        ],
      },
      {
        title: "Transactions",
        resourceKeys: ["account-vouchers"],
      },
    ],
  },
  inventory: {
    key: "inventory",
    title: "Inventory",
    tagline: "Items, stock & movements",
    icon: "📦",
    color: colors.inventory,
    colorLight: colors.inventoryLight,
    sections: [
      {
        title: "Masters",
        resourceKeys: [
          "inventory-item-categories",
          "inventory-uom",
          "inventory-sectors",
          "inventory-warehouses",
          "inventory-items",
          "inventory-price-list",
        ],
      },
      {
        title: "Transactions",
        resourceKeys: [
          "inventory-stock-transfers",
          "inventory-medicine-transfers",
          "inventory-adjustments",
          "inventory-stock-issues",
          "inventory-stock-receives",
        ],
      },
    ],
  },
};

export function moduleResources(module: ModuleKey): ResourceConfig[] {
  return MODULES[module].sections.flatMap((s) =>
    s.resourceKeys.map((k) => RESOURCES[k])
  );
}

function isBlank(v: unknown): boolean {
  return v === null || v === undefined || v === "";
}

/** Standard Active/Inactive badge for masters that carry `is_active`. */
function activeBadge(r: Row): CardView["badge"] {
  if (r.is_active === undefined) return undefined;
  return r.is_active
    ? { label: "Active", tone: "success" }
    : { label: "Inactive", tone: "neutral" };
}

/** Approval status badge for change requests. */
function changeStatusBadge(r: Row): CardView["badge"] {
  const s = String(r.status ?? "").toLowerCase();
  if (!s) return undefined;
  const tone: BadgeTone = /approv/.test(s)
    ? "success"
    : /reject|declin/.test(s)
    ? "danger"
    : /pending|await/.test(s)
    ? "warning"
    : "neutral";
  return { label: String(r.status), tone };
}

/** "12 Jul 2026 → 30 Sep 2026" from a date range, skipping blanks. */
function rangeText(from: unknown, to: unknown): string {
  const a = formatDate(from);
  const b = formatDate(to);
  if (a && b) return `${a} → ${b}`;
  return a || b || "";
}
