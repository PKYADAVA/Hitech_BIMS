import { Envelope } from "./types";
import { http } from "./client";

/**
 * Journal vouchers — the register, one voucher, and the two endings.
 *
 * These endpoints are the web module's own views behind a mobile door
 * (`account/api_write.py`), so posting from a phone runs the engine's rules
 * rather than a second copy of them. Nothing about a voucher is decided here.
 */

export interface VoucherRow {
  id: number;
  voucher_no: string;
  voucher_type: string;
  date: string;
  narration: string;
  auto_narration: string;
  narration_source: string;
  reference: string;
  sector: number | null;
  sector_name: string;
  total_debit: string;
  total_credit: string;
  status: "Draft" | "Posted" | "Cancelled";
  manual: boolean;
  system_generated: boolean;
  financial_year: string;
  attachments?: { id: number; url: string; name: string; type: string }[];
}

/** One side of a voucher: what it charged, and to which account. */
export interface VoucherLine {
  id: number;
  account: number;
  account_code: string;
  account_name: string;
  debit: string;
  credit: string;
  narration: string;
  cost_center?: number | null;
  cost_center_name?: string;
}

export interface VoucherDetail extends VoucherRow {
  lines: VoucherLine[];
  cancelled_reason?: string;
  created_by?: string;
}

export interface VoucherCards {
  today: string;
  month: string;
  month_count: number;
  drafts: number;
  cancelled: number;
  month_from: string;
  today_date: string;
}

/** Every filter the web register takes, so the phone asks the same question. */
export interface VoucherFilters {
  type?: string;
  status?: string;
  sector?: string;
  date_from?: string;
  date_to?: string;
  q?: string;
  page_size?: number;
}

const BASE = "/account/vouchers";

export async function listVouchers(filters: VoucherFilters = {}) {
  const resp = await http.get<Envelope<{ count: number; page: number; results: VoucherRow[] }>>(
    `${BASE}/rows`,
    { params: { page_size: 200, ...filters } }
  );
  return resp.data.data;
}

/** The figures above the register, counted over the company. */
export async function voucherCards(): Promise<VoucherCards> {
  const resp = await http.get<Envelope<VoucherCards>>(`${BASE}/cards`);
  return resp.data.data;
}

/** One voucher, with the lines that make it balance. */
export async function getVoucher(id: number): Promise<VoucherDetail> {
  const resp = await http.get<Envelope<VoucherDetail>>(`${BASE}/${id}/full`);
  return resp.data.data;
}

export interface VoucherMasters {
  /** Postable ledgers that take manual entry: the only thing a line may hit. */
  accounts: { id: number; code: string; name: string }[];
  types: { value: string; label: string }[];
  sectors: { id: number; name: string }[];
  centres: { id: number; name: string }[];
}

/** One side of an entry, as the screen holds it before saving. */
export interface VoucherLineInput {
  account: string;
  debit: string;
  credit: string;
  narration?: string;
  cost_center?: string;
}

export interface VoucherInput {
  date: string;
  voucher_type: string;
  narration: string;
  reference?: string;
  sector?: number | null;
  lines: VoucherLineInput[];
  post?: boolean;
}

/** Everything the entry screen's pickers hold, already filtered to what may
 *  actually be chosen. */
export async function voucherMasters(): Promise<VoucherMasters> {
  const resp = await http.get<Envelope<VoucherMasters>>(`${BASE}/masters`);
  return resp.data.data;
}

/** Write a voucher, or rewrite a draft. `post: true` puts it on the books. */
export async function saveVoucher(body: VoucherInput, id?: number): Promise<VoucherRow> {
  const url = id ? `${BASE}/save/${id}` : `${BASE}/save`;
  const resp = await http.post<Envelope<VoucherRow>>(url, body);
  return resp.data.data;
}

export async function postVoucher(id: number): Promise<VoucherRow> {
  const resp = await http.post<Envelope<VoucherRow>>(`${BASE}/${id}/post`);
  return resp.data.data;
}

/** A posted voucher is reversed and kept: its number stays on the record. */
export async function cancelVoucher(id: number, reason: string) {
  const resp = await http.post<Envelope<VoucherRow>>(`${BASE}/${id}/cancel`, { reason });
  return resp.data.data;
}

/** Drafts only. A posted voucher is cancelled, never deleted. */
export async function deleteVoucher(id: number) {
  await http.delete(`${BASE}/${id}/full`);
}
