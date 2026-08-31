import { http } from "./client";
import { Envelope } from "./types";

export interface SendResult {
  sent: boolean;
  status: string;
  log_id?: number;
  message_id?: string | null;
  error?: string | null;
}

/* --------------------------- SMS Transaction ----------------------------- */

/** A document type the transaction screen can pull (customer_due, chick_receipt, ...). */
export interface SmsDocSource {
  key: string;
  label: string;
  party_type: string;
  module: string;
  transaction: string;
}

export interface SmsSentRecord {
  template_id: number;
  template_name: string;
  mobile: string;
  sent_at: string;
}

/** One document eligible for SMS — a row from a doc source. */
export interface SmsDocRow {
  doc_id: number | string;
  date: string;
  party_type: string;
  party_id: number;
  party_name: string;
  mobile: string;
  doc_no: string;
  amount: string;
  context: Record<string, string>;
  /** The DOC_SOURCES key this row came from (set even when browsing "All"). */
  module: string;
  sent_history: SmsSentRecord[];
  already_sent: boolean;
}

export async function fetchDocSources(): Promise<SmsDocSource[]> {
  return (await http.get<Envelope<SmsDocSource[]>>("/sms/doc-sources")).data.data;
}

export interface SmsPartyOption {
  id: number;
  name: string;
}

export interface SmsPartyGroup {
  label: string;
  options: SmsPartyOption[];
}

/** (id, name) pickers per party type (customer/supplier/farmer/employee), scoped to this user. */
export async function fetchParties(): Promise<Record<string, SmsPartyGroup>> {
  return (await http.get<Envelope<Record<string, SmsPartyGroup>>>("/sms/parties")).data.data;
}

/**
 * Rows eligible for SMS. Omit `module` to browse every document type at once
 * (party ids aren't comparable across different party tables then, so `party`
 * is only honoured alongside a specific `module`).
 */
export async function fetchTransactionDocuments(params: {
  module?: string;
  from_date?: string;
  to_date?: string;
  party?: number | string;
}): Promise<SmsDocRow[]> {
  const resp = await http.get<Envelope<{ rows: SmsDocRow[] }>>("/sms/transaction/documents", {
    params,
  });
  return resp.data.data.rows;
}

export interface TransactionPreview {
  party_name: string;
  mobile: string;
  doc_no: string;
  message: string;
  char_count: number;
  sms_parts: number;
  is_unicode: boolean;
}

/** Render (never send) one document's SMS — the exact text a send would use. */
export async function previewTransactionDocument(body: {
  module: string;
  doc_id: number | string;
  template_id: number;
}): Promise<TransactionPreview> {
  const resp = await http.post<Envelope<TransactionPreview>>("/sms/transaction/preview", body);
  return resp.data.data;
}

export interface TransactionSendResult extends SendResult {
  duplicate?: boolean;
}

/** Render + send one document's SMS. `force` re-sends past the 1-minute duplicate guard. */
export async function sendTransactionDocument(body: {
  module: string;
  doc_id: number | string;
  template_id: number;
  force?: boolean;
}): Promise<TransactionSendResult> {
  const resp = await http.post<Envelope<TransactionSendResult>>("/sms/transaction/send", body);
  return resp.data.data;
}

/** Render + send a template to a phone number. `context` fills {placeholder}s. */
export async function sendTemplate(
  templateId: number,
  body: { phone: string; party_name?: string; context?: Record<string, string> }
): Promise<SendResult> {
  const resp = await http.post<Envelope<SendResult>>(`/sms/templates/${templateId}/send`, body);
  return resp.data.data;
}

/** Re-send a failed message, keeping an audit trail. */
export async function retryMessage(messageId: number): Promise<SendResult> {
  const resp = await http.post<Envelope<SendResult>>(`/sms/messages/${messageId}/retry`, {});
  return resp.data.data;
}

/** Placeholders in a template body, e.g. "Hi {name}, {doc_no}" -> ["name","doc_no"]. */
export function extractPlaceholders(body: string): string[] {
  const out = new Set<string>();
  const re = /\{(\w+)\}/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(body || "")) !== null) out.add(m[1]);
  return [...out];
}
