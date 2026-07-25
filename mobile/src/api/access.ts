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

/** Create a new role (auth group). */
export async function createRole(name: string): Promise<RoleAccess> {
  return (await http.post<Envelope<RoleAccess>>("/user/access/roles", { name })).data.data;
}

/** Rename a role. */
export async function renameRole(id: number, name: string): Promise<{ id: number; name: string }> {
  return (await http.patch<Envelope<{ id: number; name: string }>>(`/user/roles/${id}`, { name }))
    .data.data;
}

/** Delete a role (and its tab permissions). */
export async function deleteRole(id: number): Promise<void> {
  await http.delete(`/user/roles/${id}`);
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
