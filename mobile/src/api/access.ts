import { http } from "./client";
import { Envelope } from "./types";

export interface RoleAccess {
  id: number;
  name: string;
  modules: Record<string, boolean>;
}

export interface RolesAccessResp {
  navs: string[];
  roles: RoleAccess[];
}

export async function fetchRolesAccess(): Promise<RolesAccessResp> {
  return (await http.get<Envelope<RolesAccessResp>>("/user/access/roles")).data.data;
}

/** Bulk grant/revoke a whole module's tabs for a role. */
export async function setRoleModule(
  roleId: number,
  module: string,
  enabled: boolean
): Promise<{ modules: Record<string, boolean> }> {
  return (
    await http.post<Envelope<{ modules: Record<string, boolean> }>>(
      `/user/roles/${roleId}/module`,
      { module, enabled }
    )
  ).data.data;
}

/** Set which roles a user belongs to. */
export async function setUserRoles(
  userId: number,
  groupIds: number[]
): Promise<{ group_ids: number[] }> {
  return (
    await http.post<Envelope<{ group_ids: number[] }>>(`/user/users/${userId}/roles`, {
      group_ids: groupIds,
    })
  ).data.data;
}

/** Friendly labels for the backend nav keys shown as module toggles. */
export const NAV_LABEL: Record<string, string> = {
  broiler: "Broiler",
  hatchery: "Hatchery",
  account: "Accounts",
  inventory: "Inventory",
  sales: "Sales",
  purchase: "Purchase",
  hr: "HR",
  user: "Users",
  notifications: "SMS",
};
