import { NativeStackScreenProps } from "@react-navigation/native-stack";
import { useQuery } from "@tanstack/react-query";
import React, { useEffect, useLayoutEffect, useState } from "react";
import { Alert, Pressable, ScrollView, Switch, Text, TextInput, View } from "react-native";

import {
  createRole,
  createUser,
  deleteRole,
  fetchRolesAccess,
  NAV_LABEL,
  renameRole,
  RoleAccess,
  setRoleMobileModule,
  setRoleModule,
  setUserRoles,
} from "@/api/access";
import { MODULE_NAV } from "@/api/permissions";
import { ApiError } from "@/api/types";
import { listResource } from "@/api/resources";
import { Row } from "@/api/types";
import { AppIcon } from "@/components/AppIcon";
import { Card, EmptyOrError, Loading } from "@/components/ui";
import { ModuleStackParams } from "@/navigation/types";
import { makeStyles, radius, spacing, type, useTheme } from "@/theme";
import { pick } from "@/utils/format";
import { confirm, notify } from "@/ui/confirm";

type Props = NativeStackScreenProps<ModuleStackParams, "ManageAccess">;

export function ManageAccessScreen({ navigation }: Props) {
  const styles = useStyles();
  const [tab, setTab] = useState<"roles" | "users">("roles");
  useLayoutEffect(() => navigation.setOptions({ title: "Manage Access" }), [navigation]);

  return (
    <View style={styles.screen}>
      <View style={styles.segment}>
        {(["roles", "users"] as const).map((t) => (
          <Pressable
            key={t}
            onPress={() => setTab(t)}
            style={[styles.segBtn, tab === t && styles.segBtnActive]}
          >
            <Text style={[styles.segText, tab === t && styles.segTextActive]}>
              {t === "roles" ? "Roles" : "Users"}
            </Text>
          </Pressable>
        ))}
      </View>
      {tab === "roles" ? <RolesPanel /> : <UsersPanel />}
    </View>
  );
}

/* ------------------------------- Roles ---------------------------------- */

function RolesPanel() {
  const { colors } = useTheme();
  const styles = useStyles();
  const q = useQuery({ queryKey: ["access-roles"], queryFn: fetchRolesAccess });
  const [roles, setRoles] = useState<RoleAccess[]>([]);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [newRole, setNewRole] = useState("");
  const [adding, setAdding] = useState(false);
  const [renameDraft, setRenameDraft] = useState<Record<number, string>>({});
  // Which access surface the expanded role is being edited for. Web access is
  // the one that grants; Mobile Access only narrows it, so web leads.
  const [scope, setScope] = useState<"web" | "mobile">("web");
  useEffect(() => setRoles(q.data?.roles ?? []), [q.data]);
  const navs = q.data?.navs ?? [];
  const mobileModules = q.data?.mobile_modules ?? [];

  const doRename = async (role: RoleAccess) => {
    const name = (renameDraft[role.id] ?? role.name).trim();
    if (!name || name === role.name) return;
    try {
      await renameRole(role.id, name);
      setRoles((prev) =>
        prev.map((r) => (r.id === role.id ? { ...r, name } : r)).sort((a, b) => a.name.localeCompare(b.name))
      );
    } catch (e) {
      Alert.alert("Failed", (e as Error)?.message ?? "Could not rename role.");
    }
  };

  const doDelete = async (role: RoleAccess) => {
    if (!(await confirm({
      title: "Delete role",
      message: `Delete "${role.name}"? Users lose the access it grants.`,
      confirmLabel: "Delete",
      destructive: true,
    }))) return;
    try {
      await deleteRole(role.id);
      setRoles((prev) => prev.filter((r) => r.id !== role.id));
      setExpanded(null);
    } catch (e) {
      notify("Failed", (e as Error)?.message ?? "Could not delete role.");
    }
  };

  const addRole = async () => {
    const name = newRole.trim();
    if (!name) return;
    setAdding(true);
    try {
      const role = await createRole(name);
      setRoles((prev) =>
        prev.some((r) => r.id === role.id) ? prev : [...prev, role].sort((a, b) => a.name.localeCompare(b.name))
      );
      setNewRole("");
      setExpanded(role.id);
    } catch (e) {
      Alert.alert("Failed", (e as Error)?.message ?? "Could not create role.");
    } finally {
      setAdding(false);
    }
  };

  const toggle = async (role: RoleAccess, nav: string, val: boolean) => {
    setRoles((prev) =>
      prev.map((r) => (r.id === role.id ? { ...r, modules: { ...r.modules, [nav]: val } } : r))
    );
    try {
      await setRoleModule(role.id, nav, val);
    } catch (e) {
      setRoles((prev) =>
        prev.map((r) => (r.id === role.id ? { ...r, modules: { ...r.modules, [nav]: !val } } : r))
      );
      Alert.alert("Failed", (e as Error)?.message ?? "Could not update access.");
    }
  };

  const toggleMobile = async (role: RoleAccess, key: string, val: boolean) => {
    setRoles((prev) =>
      prev.map((r) => (r.id === role.id ? { ...r, mobile: { ...r.mobile, [key]: val } } : r))
    );
    try {
      // The server materialises the role's full set of rows on first edit, so
      // the reply is the authoritative state rather than just this one key.
      const { mobile } = await setRoleMobileModule(role.id, key, val);
      setRoles((prev) => prev.map((r) => (r.id === role.id ? { ...r, mobile } : r)));
    } catch (e) {
      setRoles((prev) =>
        prev.map((r) => (r.id === role.id ? { ...r, mobile: { ...r.mobile, [key]: !val } } : r))
      );
      Alert.alert("Failed", (e as Error)?.message ?? "Could not update mobile access.");
    }
  };

  if (q.isLoading) return <Loading label="Loading roles…" />;
  if (q.isError)
    return <EmptyOrError icon="⚠️" message={(q.error as Error)?.message ?? "Failed."} onRetry={q.refetch} />;

  return (
    <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
      <Text style={styles.hint}>
        Turn a module on/off for a role. Web access grants it; mobile access only
        decides whether it also shows in this app. Users inherit both from their roles.
      </Text>

      <View style={styles.addRow}>
        <TextInput
          value={newRole}
          onChangeText={setNewRole}
          placeholder="New role name"
          placeholderTextColor={colors.textFaint}
          style={styles.addInput}
          onSubmitEditing={addRole}
          returnKeyType="done"
        />
        <Pressable
          style={[styles.addBtn, (!newRole.trim() || adding) && { opacity: 0.5 }]}
          onPress={addRole}
          disabled={!newRole.trim() || adding}
        >
          <Text style={styles.addBtnText}>Add role</Text>
        </Pressable>
      </View>

      {roles.length === 0 ? (
        <Text style={styles.warn}>No roles yet — add one above to start granting module access.</Text>
      ) : null}

      {roles.map((role) => {
        const on = navs.filter((n) => role.modules[n]).length;
        // A phone module only counts as shown when web access backs it.
        const mobileOn = mobileModules.filter(
          (m) => role.mobile?.[m.key] && role.modules[MODULE_NAV[m.key] ?? m.key]
        ).length;
        const open = expanded === role.id;
        return (
          <Card key={role.id} style={styles.card}>
            <Pressable style={styles.cardHead} onPress={() => setExpanded(open ? null : role.id)}>
              <View style={{ flex: 1 }}>
                <Text style={styles.roleName}>{role.name}</Text>
                <Text style={styles.roleMeta}>
                  {on} of {navs.length} web · {mobileOn} of {mobileModules.length} on phone
                </Text>
              </View>
              <Text style={styles.caret}>{open ? "▾" : "▸"}</Text>
            </Pressable>
            {open ? (
              <View style={styles.rows}>
                <View style={styles.scopeBar}>
                  {(["web", "mobile"] as const).map((s) => (
                    <Pressable
                      key={s}
                      onPress={() => setScope(s)}
                      style={[styles.scopeBtn, scope === s && styles.scopeBtnActive]}
                    >
                      <Text style={[styles.scopeText, scope === s && styles.scopeTextActive]}>
                        {s === "web" ? "Web access" : "Mobile access"}
                      </Text>
                    </Pressable>
                  ))}
                </View>

                {scope === "web"
                  ? navs.map((nav) => (
                      <View key={nav} style={styles.row}>
                        <Text style={styles.rowLabel}>{NAV_LABEL[nav] ?? nav}</Text>
                        <Switch
                          value={!!role.modules[nav]}
                          onValueChange={(v) => toggle(role, nav, v)}
                          trackColor={{ true: colors.tint }}
                        />
                      </View>
                    ))
                  : mobileModules.map((m) => {
                      // Subtractive: without web access the switch cannot make
                      // the module appear, so say so rather than let someone
                      // turn it on and wonder why nothing changed.
                      const granted = !!role.modules[MODULE_NAV[m.key] ?? m.key];
                      return (
                        <View key={m.key} style={styles.row}>
                          <View style={{ flex: 1 }}>
                            <Text style={[styles.rowLabel, !granted && styles.rowLabelOff]}>
                              {m.title}
                            </Text>
                            {!granted ? (
                              <Text style={styles.rowNote}>Needs web access to show</Text>
                            ) : null}
                          </View>
                          <Switch
                            value={!!role.mobile?.[m.key]}
                            onValueChange={(v) => toggleMobile(role, m.key, v)}
                            trackColor={{ true: colors.tint }}
                          />
                        </View>
                      );
                    })}
                <View style={styles.roleFooter}>
                  <TextInput
                    value={renameDraft[role.id] ?? role.name}
                    onChangeText={(t) => setRenameDraft((p) => ({ ...p, [role.id]: t }))}
                    style={styles.renameInput}
                    placeholder="Role name"
                    placeholderTextColor={colors.textFaint}
                  />
                  <Pressable style={styles.smallBtn} onPress={() => doRename(role)}>
                    <Text style={styles.smallBtnText}>Rename</Text>
                  </Pressable>
                </View>
                <Pressable style={styles.deleteRow} onPress={() => doDelete(role)}>
                  <Text style={styles.deleteLink}>Delete role</Text>
                </Pressable>
              </View>
            ) : null}
          </Card>
        );
      })}
    </ScrollView>
  );
}

/* ------------------------------- Users ---------------------------------- */

function UsersPanel() {
  const { colors } = useTheme();
  const styles = useStyles();
  const rolesQ = useQuery({ queryKey: ["access-roles"], queryFn: fetchRolesAccess });
  const usersQ = useQuery({
    queryKey: ["access-users"],
    queryFn: () => listResource<Row>("/user/users/", { page_size: 200 }),
  });
  const roles = rolesQ.data?.roles ?? [];
  const [groupsByUser, setGroupsByUser] = useState<Record<number, number[]>>({});
  const [expanded, setExpanded] = useState<number | null>(null);

  useEffect(() => {
    const m: Record<number, number[]> = {};
    (usersQ.data?.items ?? []).forEach((u) => {
      m[u.id] = Array.isArray(u.groups) ? (u.groups as number[]) : [];
    });
    setGroupsByUser(m);
  }, [usersQ.data]);

  const toggleRole = async (userId: number, roleId: number, val: boolean) => {
    const cur = groupsByUser[userId] ?? [];
    const next = val ? [...new Set([...cur, roleId])] : cur.filter((id) => id !== roleId);
    setGroupsByUser((p) => ({ ...p, [userId]: next }));
    try {
      await setUserRoles(userId, next);
    } catch (e) {
      setGroupsByUser((p) => ({ ...p, [userId]: cur }));
      Alert.alert("Failed", (e as Error)?.message ?? "Could not update roles.");
    }
  };

  if (usersQ.isLoading || rolesQ.isLoading) return <Loading label="Loading users…" />;
  if (usersQ.isError)
    return <EmptyOrError icon="⚠️" message={(usersQ.error as Error)?.message ?? "Failed."} onRetry={usersQ.refetch} />;
  const users = usersQ.data?.items ?? [];

  return (
    <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
      <Text style={styles.hint}>Create a login user, then assign roles. They gain every module their roles allow.</Text>
      <CreateUserCard roles={roles} onCreated={() => usersQ.refetch()} />
      {roles.length === 0 ? (
        <Text style={styles.warn}>No roles exist yet — add one in the Roles tab to grant module access.</Text>
      ) : null}
      {users.length === 0 ? <Text style={styles.warn}>No users yet — create the first one above.</Text> : null}
      {users.map((u) => {
        const open = expanded === u.id;
        const mine = groupsByUser[u.id] ?? [];
        const name = pick(u, ["username"], `User #${u.id}`);
        return (
          <Card key={u.id} style={styles.card}>
            <Pressable style={styles.cardHead} onPress={() => setExpanded(open ? null : u.id)}>
              <View style={{ flex: 1 }}>
                <Text style={styles.roleName}>{name}</Text>
                <Text style={styles.roleMeta}>
                  {u.is_superuser ? "Administrator · all access" : `${mine.length} role(s)`}
                </Text>
              </View>
              <Text style={styles.caret}>{open ? "▾" : "▸"}</Text>
            </Pressable>
            {open ? (
              <View style={styles.rows}>
                {roles.map((role) => (
                  <View key={role.id} style={styles.row}>
                    <Text style={styles.rowLabel}>{role.name}</Text>
                    <Switch
                      value={mine.includes(role.id)}
                      disabled={!!u.is_superuser}
                      onValueChange={(v) => toggleRole(u.id, role.id, v)}
                      trackColor={{ true: colors.tint }}
                    />
                  </View>
                ))}
              </View>
            ) : null}
          </Card>
        );
      })}
    </ScrollView>
  );
}

/** Collapsible "add a login user" form: credentials, flags, and role toggles. */
function CreateUserCard({ roles, onCreated }: { roles: RoleAccess[]; onCreated: () => void }) {
  const { colors } = useTheme();
  const styles = useStyles();
  const [open, setOpen] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [email, setEmail] = useState("");
  const [isActive, setIsActive] = useState(true);
  const [isStaff, setIsStaff] = useState(false);
  const [groupIds, setGroupIds] = useState<number[]>([]);
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const reset = () => {
    setUsername(""); setPassword(""); setFirstName(""); setLastName("");
    setEmail(""); setIsActive(true); setIsStaff(false); setGroupIds([]); setErrors({});
  };

  const toggleGroup = (id: number, on: boolean) =>
    setGroupIds((prev) => (on ? [...new Set([...prev, id])] : prev.filter((g) => g !== id)));

  const submit = async () => {
    setErrors({});
    const errs: Record<string, string> = {};
    if (!username.trim()) errs.username = "Required";
    if (!password) errs.password = "Required";
    if (Object.keys(errs).length) return setErrors(errs);
    setSaving(true);
    try {
      await createUser({
        username: username.trim(),
        password,
        first_name: firstName.trim(),
        last_name: lastName.trim(),
        email: email.trim(),
        is_active: isActive,
        is_staff: isStaff,
        group_ids: groupIds,
      });
      reset();
      setOpen(false);
      onCreated();
      Alert.alert("User created", `“${username.trim()}” can now sign in.`);
    } catch (e) {
      if (e instanceof ApiError && e.fields) {
        const fe: Record<string, string> = {};
        for (const [k, v] of Object.entries(e.fields)) fe[k] = Array.isArray(v) ? v.join(" ") : String(v);
        setErrors(fe);
      } else {
        Alert.alert("Failed", (e as Error)?.message ?? "Could not create user.");
      }
    } finally {
      setSaving(false);
    }
  };

  if (!open) {
    return (
      <Pressable style={styles.newUserBtn} onPress={() => setOpen(true)}>
        <AppIcon name="plus" size={16} color={colors.tint} />
        <Text style={styles.newUserBtnText}>New user</Text>
      </Pressable>
    );
  }

  const Input = (
    label: string,
    val: string,
    set: (t: string) => void,
    opts?: { secure?: boolean; error?: string; keyboard?: "email-address" },
  ) => (
    <View style={{ marginBottom: spacing.sm }}>
      <Text style={styles.fieldLabel}>{label}</Text>
      <TextInput
        value={val}
        onChangeText={set}
        secureTextEntry={opts?.secure}
        autoCapitalize={opts?.secure || opts?.keyboard ? "none" : "sentences"}
        keyboardType={opts?.keyboard ?? "default"}
        placeholder={label}
        placeholderTextColor={colors.textFaint}
        style={styles.addInput}
      />
      {opts?.error ? <Text style={styles.fieldError}>{opts.error}</Text> : null}
    </View>
  );

  return (
    <Card style={styles.newUserCard}>
      <View style={styles.cardHeadRow}>
        <Text style={styles.roleName}>New user</Text>
        <Pressable hitSlop={10} onPress={() => { reset(); setOpen(false); }}>
          <Text style={styles.modalClose}>Cancel</Text>
        </Pressable>
      </View>
      {Input("Username", username, setUsername, { error: errors.username })}
      {Input("Password", password, setPassword, { secure: true, error: errors.password })}
      {Input("First name", firstName, setFirstName)}
      {Input("Last name", lastName, setLastName)}
      {Input("Email", email, setEmail, { keyboard: "email-address", error: errors.email })}

      <View style={styles.flagRow}>
        <Text style={styles.rowLabel}>Active</Text>
        <Switch value={isActive} onValueChange={setIsActive} trackColor={{ true: colors.tint }} />
      </View>
      <View style={styles.flagRow}>
        <Text style={styles.rowLabel}>Staff (admin site access)</Text>
        <Switch value={isStaff} onValueChange={setIsStaff} trackColor={{ true: colors.tint }} />
      </View>

      {roles.length > 0 ? (
        <>
          <Text style={[styles.fieldLabel, { marginTop: spacing.sm }]}>Roles</Text>
          {roles.map((role) => (
            <View key={role.id} style={styles.row}>
              <Text style={styles.rowLabel}>{role.name}</Text>
              <Switch
                value={groupIds.includes(role.id)}
                onValueChange={(v) => toggleGroup(role.id, v)}
                trackColor={{ true: colors.tint }}
              />
            </View>
          ))}
        </>
      ) : null}

      <Pressable
        style={[styles.addBtn, { marginTop: spacing.md }, saving && { opacity: 0.6 }]}
        onPress={submit}
        disabled={saving}
      >
        <Text style={styles.addBtnText}>{saving ? "Creating…" : "Create user"}</Text>
      </Pressable>
    </Card>
  );
}

const useStyles = makeStyles((colors) => ({
  screen: { flex: 1, backgroundColor: colors.bg },
  segment: {
    flexDirection: "row",
    margin: spacing.md,
    backgroundColor: colors.surfaceAlt,
    borderRadius: radius.md,
    padding: 4,
  },
  segBtn: { flex: 1, paddingVertical: spacing.sm, alignItems: "center", borderRadius: radius.sm },
  segBtnActive: { backgroundColor: colors.surface, ...({} as object) },
  segText: { ...type.title, color: colors.textMuted },
  segTextActive: { color: colors.text },
  content: { padding: spacing.md, paddingTop: 0, gap: spacing.sm, paddingBottom: spacing.xxl },
  hint: { ...type.caption, color: colors.textMuted, marginBottom: spacing.xs },
  warn: { ...type.caption, color: colors.warning, marginBottom: spacing.xs },
  addRow: { flexDirection: "row", gap: spacing.sm, marginBottom: spacing.sm },
  addInput: {
    flex: 1,
    height: 44,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    backgroundColor: colors.surface,
    color: colors.text,
    ...type.body,
  },
  addBtn: {
    height: 44,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.md,
    backgroundColor: colors.primary,
    alignItems: "center",
    justifyContent: "center",
  },
  addBtnText: { ...type.title, color: colors.onDark },
  card: { padding: 0, overflow: "hidden" },
  newUserCard: { padding: spacing.lg },
  cardHead: { flexDirection: "row", alignItems: "center", padding: spacing.lg },
  cardHeadRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: spacing.md,
  },
  newUserBtn: {
    flexDirection: "row",
    gap: spacing.xs,
    borderWidth: 1,
    borderColor: colors.tint,
    borderStyle: "dashed",
    borderRadius: radius.md,
    paddingVertical: spacing.md,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: spacing.xs,
  },
  newUserBtnText: { ...type.title, color: colors.tint },
  fieldLabel: { ...type.label, color: colors.text, marginBottom: spacing.xs },
  fieldError: { ...type.caption, color: colors.danger, marginTop: 2 },
  flagRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: spacing.sm,
  },
  modalClose: { ...type.title, color: colors.tint },
  roleName: { ...type.title, color: colors.text },
  roleMeta: { ...type.caption, color: colors.textMuted, marginTop: 2 },
  caret: { ...type.h3, color: colors.textFaint },
  rows: { borderTopWidth: 1, borderTopColor: colors.border, paddingHorizontal: spacing.lg },
  row: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  rowLabel: { ...type.body, color: colors.text },
  rowLabelOff: { color: colors.textMuted },
  rowNote: { ...type.caption, color: colors.textFaint, marginTop: 1 },
  scopeBar: {
    flexDirection: "row",
    backgroundColor: colors.surfaceAlt,
    borderRadius: radius.sm,
    padding: 3,
    marginTop: spacing.md,
    marginBottom: spacing.xs,
  },
  scopeBtn: { flex: 1, paddingVertical: spacing.xs, alignItems: "center", borderRadius: radius.sm },
  scopeBtnActive: { backgroundColor: colors.surface },
  scopeText: { ...type.label, color: colors.textMuted },
  scopeTextActive: { color: colors.text },
  roleFooter: { flexDirection: "row", gap: spacing.sm, paddingVertical: spacing.md },
  renameInput: {
    flex: 1,
    height: 40,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.md,
    backgroundColor: colors.surface,
    color: colors.text,
    ...type.body,
  },
  smallBtn: {
    height: 40,
    paddingHorizontal: spacing.md,
    borderRadius: radius.sm,
    backgroundColor: colors.surfaceAlt,
    alignItems: "center",
    justifyContent: "center",
  },
  smallBtnText: { ...type.label, color: colors.text },
  deleteRow: { paddingBottom: spacing.md },
  deleteLink: { ...type.label, color: colors.danger },
}));
