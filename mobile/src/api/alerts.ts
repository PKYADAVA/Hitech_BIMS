import { http } from "./client";
import { API_BASE_URL } from "@/config";

/**
 * Business alerts — the phone's half of the ERP's notification bell.
 *
 * These call the alerthub API the web bell already uses
 * (`alerthub/api.py`, `/api/alerthub/notifications/`) rather than a mobile
 * copy of it. Targeting, scope and read-state all live behind
 * `Notification.for_user`, so a supervisor sees on the phone exactly what they
 * see in the office, and "read" means read in both places.
 *
 * Two things differ from the rest of `src/api`:
 *
 *  * These endpoints sit outside `/api/v1`, so each call passes an absolute
 *    URL. Axios ignores `baseURL` when the url is absolute, and the shared
 *    `http` instance still supplies the bearer token and the 401 refresh.
 *  * They answer in plain DRF shapes, not the v1 `{success, data, meta}`
 *    envelope, so nothing here unwraps `.data.data`.
 */

/** `https://host/api/alerthub` — derived so a LAN build talks to the LAN server. */
const ALERTS_BASE = `${API_BASE_URL.replace(/\/api\/v1\/?$/, "")}/api/alerthub`;

export interface AlertNotification {
  id: number;
  rule_key: string;
  module: string;
  module_label: string;
  priority: string;
  priority_label: string;
  /** Set on messages a person composed; blank on rule-raised alerts. */
  category: string;
  category_label: string;
  /** Absolute — the server builds it, so a LAN build gets a LAN URL. */
  attachment_url: string;
  attachment_name: string;
  /** "danger" | "warning" | "info" | "success" — drives the accent colour. */
  tone: string;
  color: string;
  icon: string;
  title: string;
  message: string;
  /** Branch / farm / warehouse the alert is about, already formatted. */
  place: string;
  branch_name: string;
  farm_name: string;
  warehouse_name: string;
  object_display: string;
  voucher_no: string;
  measured_value: string | null;
  threshold_value: string | null;
  is_read: boolean;
  read_at: string | null;
  created_at: string;
}

interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface AlertPage {
  items: AlertNotification[];
  /** Absolute URL of the next page, or null at the end. */
  next: string | null;
  total: number;
}

/**
 * One page of alerts, newest first.
 *
 * `url` follows the server's own `next` link rather than counting pages, the
 * same way `useResourceList` does — the page size is the server's to choose.
 */
export async function listAlerts(
  params?: { unreadOnly?: boolean; url?: string }
): Promise<AlertPage> {
  const url = params?.url ?? `${ALERTS_BASE}/notifications/`;
  const resp = await http.get<Paginated<AlertNotification>>(url, {
    params: params?.url
      ? undefined                       // the next link already carries them
      : params?.unreadOnly
      ? { is_read: "false" }
      : undefined,
  });
  return {
    items: resp.data.results ?? [],
    next: resp.data.next,
    total: resp.data.count ?? 0,
  };
}

/** The badge. Cheap by design — the web bell polls the same endpoint. */
export async function unreadAlertCount(): Promise<number> {
  const resp = await http.get<{ unread: number }>(
    `${ALERTS_BASE}/notifications/unread_count/`
  );
  return resp.data.unread ?? 0;
}

/** Mark one read. Returns the new unread total so the badge needs no refetch. */
export async function markAlertRead(id: number): Promise<number> {
  const resp = await http.post<{ ok: boolean; unread: number }>(
    `${ALERTS_BASE}/notifications/${id}/mark_read/`
  );
  return resp.data.unread ?? 0;
}

/**
 * Clear one off this user's list.
 *
 * Not a delete — the server keeps the notification and the record that this
 * user was sent it, and only their view of it changes. It marks read too, so a
 * cleared alert cannot keep the badge lit.
 */
export async function dismissAlert(id: number): Promise<number> {
  const resp = await http.post<{ ok: boolean; unread: number }>(
    `${ALERTS_BASE}/notifications/${id}/dismiss/`
  );
  return resp.data.unread ?? 0;
}

export async function markAllAlertsRead(): Promise<number> {
  const resp = await http.post<{ marked_read: number; unread: number }>(
    `${ALERTS_BASE}/notifications/mark_all_read/`
  );
  return resp.data.unread ?? 0;
}
