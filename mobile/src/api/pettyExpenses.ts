import { Envelope } from "./types";
import { http } from "./client";

/**
 * Petty expense — the register and the entry screen.
 *
 * These endpoints are the web module's own views behind a mobile door
 * (`account/api_write.py`), so a phone entry runs the same validation, the
 * same cash-box check and the same journal posting as one typed in the
 * browser. Nothing about a petty expense is decided here.
 */

export interface PettyRow {
  id: number;
  expense_no: string;
  date: string;
  branch: string;
  farm: string;
  shed: string;
  batch: string;
  category: string;
  sub_category: string;
  description: string;
  paid_to: string;
  mode: string;
  paid_from: string;
  amount: number;
  status: "Draft" | "Posted" | "Cancelled";
  voucher_no: string;
  bills: { id: number; url: string; name: string; type: string }[];
  editable?: boolean;
}

/** A cash box and what it holds, as the register's tile shows it. */
export interface CashBox {
  id: number;
  label: string;
  balance: number;
  low: boolean;
  float_amount: number;
  top_up: number;
}

export interface PettyCards {
  today: number;
  month: number;
  drafts: number;
  cash: CashBox[];
}

export interface PettyList {
  rows: PettyRow[];
  cards: PettyCards;
}

/** Every filter the web register takes, so the phone cannot ask a different question. */
export interface PettyFilters {
  from?: string;
  to?: string;
  month?: string;
  year?: string;
  status?: string;
  branch?: string;
  farm?: string;
  shed?: string;
  paid_from?: string;
  category?: string;
  q?: string;
}

export interface PettyMasters {
  branches: { id: number; branch_name: string }[];
  farms: { id: number; farm_name: string; branch_id: number }[];
  sheds: { id: number; farm_id: number; label: string }[];
  batches: { id: number; farm_id: number; shed_id: number | null; label: string }[];
  categories: { id: number; name: string; items: { id: number; code: string; name: string }[] }[];
  groups: { id: number; code: string; name: string }[];
  centres: { id: number; branch_id: number; name: string }[];
  paid_from: { id: number; label: string; is_cash: boolean; balance: number | null }[];
  modes: { id: number; name: string }[];
  mode_accounts: Record<string, number[]>;
  uoms: { id: number; name: string }[];
  years: number[];
}

/** One line of an expense, as the entry screen holds it before saving. */
export interface PettyItemInput {
  account: string;
  description: string;
  quantity: string;
  uom?: string;
  rate: string;
}

export interface PettyExpenseInput {
  expense_date: string;
  branch: string;
  farm?: string;
  shed?: string;
  batch?: string;
  cost_centre?: string;
  paid_to_name: string;
  payment_mode: string;
  paid_from: string;
  reference?: string;
  narration?: string;
  tags?: string;
  other_charges?: string;
  adjustment?: string;
  items: PettyItemInput[];
  post?: boolean;
}

export interface PettySaved {
  id: number;
  expense_no: string;
  status: string;
  voucher_no: string;
  duplicate?: string;
}

const BASE = "/account/petty-expenses";

/** The register's rows and the figures above them, counted from the same query. */
export async function listPettyExpenses(filters: PettyFilters = {}): Promise<PettyList> {
  const resp = await http.get<Envelope<PettyList>>(`${BASE}/rows`, { params: filters });
  return resp.data.data;
}

/** Everything the entry screen's pickers hold, already scoped to this user. */
export async function pettyMasters(): Promise<PettyMasters> {
  const resp = await http.get<Envelope<PettyMasters>>(`${BASE}/masters`);
  return resp.data.data;
}

export async function getPettyExpense(id: number) {
  const resp = await http.get<Envelope<Record<string, unknown>>>(`${BASE}/${id}`);
  return resp.data.data;
}

/** Save a draft, or save and post — `post: true` does both in one call. */
export async function savePettyExpense(
  body: PettyExpenseInput,
  id?: number
): Promise<PettySaved> {
  const url = id ? `${BASE}/save/${id}` : `${BASE}/save`;
  const resp = await http.post<Envelope<PettySaved>>(url, body);
  return resp.data.data;
}

export async function postPettyExpense(id: number) {
  const resp = await http.post<Envelope<PettySaved>>(`${BASE}/${id}/post`);
  return resp.data.data;
}

export async function cancelPettyExpense(id: number, reason: string) {
  const resp = await http.post<Envelope<PettySaved>>(`${BASE}/${id}/cancel`, { reason });
  return resp.data.data;
}

export async function deletePettyExpense(id: number) {
  await http.post(`${BASE}/${id}/delete`);
}

/** Take a bill off a draft. A posted expense keeps its evidence. */
export async function detachPettyBill(id: number, attachmentId: number) {
  await http.delete(`${BASE}/${id}/attach/${attachmentId}`);
}

/** The bill, photographed at the counter. */
export async function attachPettyBills(id: number, body: FormData) {
  const resp = await http.post<Envelope<{ bills: PettyRow["bills"]; refused: string[] }>>(
    `${BASE}/${id}/attach`,
    body,
    { headers: { "Content-Type": "multipart/form-data" } }
  );
  return resp.data.data;
}
