import { Envelope } from "./types";
import { http } from "./client";

/**
 * Transfer Charges — the register and the Add screen.
 *
 * These endpoints are the web module's own views behind a mobile door
 * (`inventory/api_write.py`), so a phone entry runs the same allocation
 * engine, the same duplicate-trip check and the same journal posting as one
 * typed in the browser. Nothing about a Transfer Charge is decided here —
 * including the allocation split, which is always asked of the server
 * (`previewAllocation`) rather than recomputed on the phone.
 */

/** One destination farm's share of a Common line, or a Farm-wise line's
 *  own entered amount — both come back in this shape. */
export interface AllocationRow {
  id?: number;
  destination_farm: number;
  destination_farm_name?: string;
  quantity_basis?: number;
  stock_value_basis?: number;
  distance_basis?: number | null;
  percentage?: number;
  allocated_amount: number;
  remarks?: string;
}

/** A trip's resolved destination farms, as the lookup and the save both see them. */
export interface DestinationFarm {
  farm_id: number;
  farm_name: string;
  quantity: number;
  stock_value: number;
  /** Batch code(s) the linked Stock Transfer rows placed onto this farm. */
  batches: string[];
}

/** One Stock Transfer "trip" — every row sharing one DC No. and date,
 *  grouped the way the Add screen's Step 1 picker groups them. */
export interface StockTransferTripGroup {
  dc_no: string;
  date: string;
  stock_transfer_ids: number[];
  from_location: string;
  vehicle_no: string;
  driver_name: string;
  trnums: string[];
  batches: string[];
  item_codes: string[];
  item_names: string[];
  to_locations: string[];
  farm_count: number;
  item_count: number;
  total_quantity: number;
  total_stock_value: number;
  farms: DestinationFarm[];
  already_charged: boolean;
  existing_charge_nos: string[];
}

/** The register's row shape — one Transfer Charge, without its lines. */
export interface TransferChargeRow {
  id: number;
  charge_no: string;
  charge_date: string;
  dc_no: string;
  treatment: "Expense Only" | "Add to Inventory Cost";
  status: "Draft" | "Pending Approval" | "Posted" | "Cancelled";
  total_transport: number;
  total_loading: number;
  total_unloading: number;
  total_other: number;
  total_charges: number;
  payment_mode: "Paid Now" | "Pay Later";
  paid_from: number | null;
  payable_account: number | null;
  payee_name: string;
  cost_centre: number | null;
  narration: string;
  header_remarks: string;
  voucher_id: number | null;
  posted_by: string;
  created_by: string;
  from_location: string;
  vehicle_no: string;
  driver_name: string;
  destination_farms: DestinationFarm[];
  farm_count: number;
  total_quantity: number;
  total_stock_value: number;
  charge_types: string[];
  charge_scopes: string[];
  attachments: { id: number; file_name: string; file_type: string; url: string }[];
}

/** One charge line, as the detail call returns it with its allocations. */
export interface TransferChargeLineRow {
  id: number;
  charge_type: number;
  charge_type_name: string;
  description: string;
  charge_scope: "Common" | "Farm-wise";
  basis: string;
  total_amount: number;
  allocation_method: "Equal" | "By Quantity" | "By Stock Value" | "By Distance" | "Manual";
  line_total: number;
  allocations: AllocationRow[];
}

export interface TransferChargeDetail extends TransferChargeRow {
  stock_transfer_ids: number[];
  lines: TransferChargeLineRow[];
}

/** Every filter the web register takes, so the phone cannot ask a different question. */
export interface TransferChargeFilters {
  from_date?: string;
  to_date?: string;
  status?: string;
  charge_type?: string;
  charge_scope?: string;
  farm?: string;
  dc_no?: string;
  branch?: string;
  vehicle?: string;
}

export interface TransferChargeMasters {
  charge_types: { id: number; name: string }[];
  branches: { id: number; branch_name: string }[];
  farms: { id: number; farm_name: string; branch_id: number }[];
  statuses: string[];
  treatments: string[];
  payment_modes: string[];
  allocation_methods: string[];
  scopes: string[];
  bank_cash_accounts: { id: number; name: string; is_cash: boolean }[];
  payable_accounts: { id: number; code: string; description: string }[];
}

/** One allocation, as the entry screen holds it before saving -- a
 *  Farm-wise amount typed directly, or a Manual override of a Common split. */
export interface TransferChargeAllocationInput {
  destination_farm: number;
  allocated_amount: string;
  percentage?: string;
  remarks?: string;
}

/** One charge line, as the entry screen holds it before saving. */
export interface TransferChargeLineInput {
  charge_type: string;
  description?: string;
  charge_scope: "Common" | "Farm-wise";
  basis?: string;
  total_amount?: string;
  allocation_method?: string;
  allocations?: TransferChargeAllocationInput[];
}

export interface TransferChargeInput {
  dc_no: string;
  charge_date: string;
  stock_transfer_ids: number[];
  treatment?: string;
  payment_mode?: string;
  paid_from?: string;
  payable_account?: string;
  payee_name?: string;
  cost_centre?: string;
  narration?: string;
  header_remarks?: string;
  lines: TransferChargeLineInput[];
  /** The web form's own flag for "Submit for Approval" rather than a draft. */
  submit_for_approval?: boolean;
  /** `"post"` puts it on the books in the same call as the save. */
  action?: "post";
  /** Confirms posting a second charge against a trip already posted. */
  allow_duplicate?: boolean;
}

const BASE = "/inventory/transfer-charges";

/** The register's rows, filtered. */
export async function listTransferCharges(
  filters: TransferChargeFilters = {}
): Promise<TransferChargeRow[]> {
  const resp = await http.get<Envelope<TransferChargeRow[]>>(`${BASE}/rows`, { params: filters });
  return resp.data.data;
}

/** Everything the Add screen's pickers hold, already scoped to this user. */
export async function transferChargeMasters(): Promise<TransferChargeMasters> {
  const resp = await http.get<Envelope<TransferChargeMasters>>(`${BASE}/masters`);
  return resp.data.data;
}

export async function getTransferCharge(id: number): Promise<TransferChargeDetail> {
  const resp = await http.get<Envelope<TransferChargeDetail>>(`${BASE}/${id}`);
  return resp.data.data;
}

/** Save a draft, submit for approval, or save and post — `action: "post"`
 *  does the last in one call, exactly as the web form's buttons do. */
export async function saveTransferCharge(
  body: TransferChargeInput,
  id?: number
): Promise<TransferChargeDetail> {
  const url = id ? `${BASE}/save/${id}` : `${BASE}/save`;
  const resp = await http.post<Envelope<TransferChargeDetail>>(url, body);
  return resp.data.data;
}

export async function postTransferCharge(
  id: number,
  allowDuplicate = false
): Promise<TransferChargeDetail> {
  const resp = await http.post<Envelope<TransferChargeDetail>>(`${BASE}/${id}/post`, {
    allow_duplicate: allowDuplicate,
  });
  return resp.data.data;
}

export async function cancelTransferCharge(id: number, reason: string): Promise<TransferChargeDetail> {
  const resp = await http.post<Envelope<TransferChargeDetail>>(`${BASE}/${id}/cancel`, { reason });
  return resp.data.data;
}

/** Drafts only — a posted charge is cancelled, never deleted. */
export async function deleteTransferCharge(id: number) {
  await http.delete(`${BASE}/${id}`);
}

/** Trip search: every Stock Transfer row sharing one DC No. and date,
 *  grouped as one trip. `dc_no` + `date` asks for one group's full detail;
 *  `ids` re-expands a saved charge's stock_transfer_ids back into its
 *  original groups; otherwise `q`/`from_date`/`to_date` searches. */
export async function lookupStockTransferTrips(params: {
  q?: string;
  dc_no?: string;
  date?: string;
  ids?: string;
  from_date?: string;
  to_date?: string;
  exclude_header?: number;
}): Promise<StockTransferTripGroup[] | StockTransferTripGroup> {
  const resp = await http.get<Envelope<StockTransferTripGroup[] | StockTransferTripGroup>>(
    `${BASE}/stock-transfer-lookup`,
    { params }
  );
  return resp.data.data;
}

/** What the Transaction No. will look like if saved against this date —
 *  not reserved, so a concurrent save can still take it first. */
export async function nextChargeNoPreview(chargeDate: string): Promise<string> {
  const resp = await http.get<Envelope<{ preview: string }>>(`${BASE}/next-number`, {
    params: { charge_date: chargeDate },
  });
  return resp.data.data.preview;
}

/** Live allocation split for a Common line, straight from the engine — the
 *  same function the save itself calls, so the preview can never show a
 *  number the save would disagree with. No database write. */
export async function previewAllocation(body: {
  farms: { farm_id: number; farm_name?: string; quantity?: string; stock_value?: string; distance?: string }[];
  total_amount: string;
  allocation_method: string;
}): Promise<{ rows: AllocationRow[]; total: number }> {
  const resp = await http.post<Envelope<{ rows: AllocationRow[]; total: number }>>(
    `${BASE}/allocate-preview`,
    body
  );
  return resp.data.data;
}

/** Bills, Bilty/LR and toll receipts, photographed at the counter. */
export async function attachTransferChargeFiles(id: number, body: FormData) {
  const resp = await http.post<Envelope<{ attachments: TransferChargeRow["attachments"]; refused: string[] }>>(
    `${BASE}/${id}/attach`,
    body,
    { headers: { "Content-Type": "multipart/form-data" } }
  );
  return resp.data.data;
}

/** Removed only from a Draft or Pending Approval record — a posted charge
 *  keeps its evidence, same rule as Petty Expense's bills. */
export async function detachTransferChargeFile(id: number, attachmentId: number) {
  await http.delete(`${BASE}/${id}/attach/${attachmentId}`);
}
