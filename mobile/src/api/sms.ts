import { http } from "./client";
import { Envelope } from "./types";

export interface SendResult {
  sent: boolean;
  status: string;
  log_id?: number;
  message_id?: string | null;
  error?: string | null;
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
