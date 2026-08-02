import { http } from "./client";
import { Envelope } from "./types";

export interface RoleAccess {
  id: number;
  name: string;
  /** Web access: nav key -> the role has any view permission under it. */
  modules: Record<string, boolean>;
  /** Mobile Access: phone module key -> shown in the app. Subtractive — a
   *  module switched on here still needs the web access above to appear. */
  mobile: Record<string, boolean>;
}

/** A phone module the app can show, with its label from the server registry. */
export interface MobileModule {
  key: string;
  title: string;
}

export interface RolesAccessResp {
  navs: string[];
  mobile_modules: MobileModule[];
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

/**
 * Show or hide one module of the phone app for a role (User > Mobile Access).
 *
 * Subtractive: switching a module on cannot grant access the web matrix
 * withholds, it only stops Mobile Access from taking it away. So a module can
 * read as on here and still not appear, when the role has no web access to it.
 */
export async function setRoleMobileModule(
  roleId: number,
  module: string,
  enabled: boolean
): Promise<{ mobile: Record<string, boolean> }> {
  return (
    await http.post<Envelope<{ mobile: Record<string, boolean> }>>(
      `/user/roles/${roleId}/mobile-module`,
      { module, enabled }
    )
  ).data.data;
}

export interface NewUser {
  username: string;
  password: string;
  first_name?: string;
  last_name?: string;
  email?: string;
  is_active?: boolean;
  is_staff?: boolean;
  group_ids?: number[];
}

export interface CreatedUser {
  id: number;
  username: string;
  group_ids: number[];
}

/** Admin: create a new login user (hashed password, optional roles/staff). */
export async function createUser(payload: NewUser): Promise<CreatedUser> {
  return (await http.post<Envelope<CreatedUser>>("/user/users/create", payload)).data.data;
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
