import { useQuery } from "@tanstack/react-query";

import { http } from "./client";
import { Envelope } from "./types";

/**
 * The ERP dashboard's five data widgets (Live Flock, Daily Entries,
 * Receivables, Payables, Stock Alerts), for the phone's own dashboard.
 *
 * Backed by the same `dashboard_widgets()` the web page's own
 * `/api/dashboard-widgets/` fetch renders — same tab-permission gate, and
 * the same admin-configured on/off + ordering (Dashboard Access), so a
 * widget never shows here that the web dashboard would withhold, and an
 * admin's widget layout choice carries over rather than needing a second
 * mobile-only setting.
 */

export interface WidgetStat {
  label: string;
  value: string;
  sub?: string;
  tone?: "good" | "warn" | "bad" | null;
}

export interface WidgetRow {
  label: string;
  meta?: string;
  value?: string;
}

export interface DashboardWidget {
  key: string;
  title: string;
  icon: string;
  colour: string;
  url?: string;
  stats?: WidgetStat[];
  rows?: WidgetRow[];
  rows_title?: string | null;
  more?: number;
  note?: string | null;
  ignored?: string | null;
  error?: boolean;
  position: number;
}

export async function fetchDashboardWidgets(): Promise<DashboardWidget[]> {
  const resp = await http.get<Envelope<DashboardWidget[]>>("/dashboard-widgets");
  return resp.data.data;
}

export function useDashboardWidgets() {
  return useQuery({
    queryKey: ["dashboard-widgets"],
    queryFn: fetchDashboardWidgets,
    staleTime: 60_000,
  });
}
