import { useQuery } from "@tanstack/react-query";

import { http } from "./client";
import { Envelope, Row } from "./types";

/** Today, as the API writes dates. Local, because the day is the driver's. */
export function todayISO(d = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/**
 * The asking employee's trip for today, or null when the day is not started.
 *
 * `/hr/trips/` already narrows to the employee behind the login and the
 * database holds one trip per person per day, so a date filter returns at most
 * that person's own row — no client-side "which of these is mine" step, and
 * nothing to tamper with in the query string.
 *
 * `enabled` is the caller's, because asking at all only makes sense for a
 * login that maps to an employee.
 */
export function useTodayTrip(enabled: boolean) {
  const date = todayISO();
  return useQuery({
    queryKey: ["today-trip", date],
    enabled,
    queryFn: async (): Promise<Row | null> => {
      const resp = await http.get<Envelope<Row[]>>("/hr/trips/", { params: { date } });
      return resp.data.data[0] ?? null;
    },
  });
}
