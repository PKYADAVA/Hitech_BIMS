import { http } from "./client";
import { Envelope } from "./types";

export interface Permissions {
  unrestricted: boolean;
  nav_groups: string[];
  tabs: string[];
}

export async function fetchPermissions(): Promise<Permissions> {
  const resp = await http.get<Envelope<Permissions>>("/auth/permissions");
  return resp.data.data;
}

/** Mobile module key → backend nav group key (SMS lives under "notifications"). */
export const MODULE_NAV: Record<string, string> = {
  broiler: "broiler",
  hatchery: "hatchery",
  sms: "notifications",
  account: "account",
  inventory: "inventory",
  sales: "sales",
  purchase: "purchase",
  hr: "hr",
  user: "user",
};
