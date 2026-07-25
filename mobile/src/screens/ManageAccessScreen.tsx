import { NativeStackScreenProps } from "@react-navigation/native-stack";
import { useQuery } from "@tanstack/react-query";
import React, { useEffect, useLayoutEffect, useState } from "react";
import { Alert, Pressable, ScrollView, StyleSheet, Switch, Text, View } from "react-native";

import {
  fetchRolesAccess,
  NAV_LABEL,
  RoleAccess,
  setRoleModule,
  setUserRoles,
} from "@/api/access";
import { listResource } from "@/api/resources";
import { Row } from "@/api/types";
import { Card, EmptyOrError, Loading } from "@/components/ui";
import { ModuleStackParams } from "@/navigation/types";
import { colors, radius, spacing, type } from "@/theme";
import { pick } from "@/utils/format";

type Props = NativeStackScreenProps<ModuleStackParams, "ManageAccess">;

export function ManageAccessScreen({ navigation }: Props) {
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
  const q = useQuery({ queryKey: ["access-roles"], queryFn: fetchRolesAccess });
  const [roles, setRoles] = useState<RoleAccess[]>([]);
  const [expanded, setExpanded] = useState<number | null>(null);
  useEffect(() => setRoles(q.data?.roles ?? []), [q.data]);
  const navs = q.data?.navs ?? [];

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

  if (q.isLoading) return <Loading label="Loading roles…" />;
  if (q.isError)
    return <EmptyOrError icon="⚠️" message={(q.error as Error)?.message ?? "Failed."} onRetry={q.refetch} />;
  if (roles.length === 0)
    return <EmptyOrError icon="🛡️" message="No roles yet. Create roles in the web app, then assign module access here." />;

  return (
    <ScrollView contentContainerStyle={styles.content}>
      <Text style={styles.hint}>Turn a module on/off for a role. Users inherit access from their roles.</Text>
      {roles.map((role) => {
        const on = navs.filter((n) => role.modules[n]).length;
        const open = expanded === role.id;
        return (
          <Card key={role.id} style={styles.card}>
            <Pressable style={styles.cardHead} onPress={() => setExpanded(open ? null : role.id)}>
              <View style={{ flex: 1 }}>
                <Text style={styles.roleName}>{role.name}</Text>
                <Text style={styles.roleMeta}>{on} of {navs.length} modules</Text>
              </View>
              <Text style={styles.caret}>{open ? "▾" : "▸"}</Text>
            </Pressable>
            {open ? (
              <View style={styles.rows}>
                {navs.map((nav) => (
                  <View key={nav} style={styles.row}>
                    <Text style={styles.rowLabel}>{NAV_LABEL[nav] ?? nav}</Text>
                    <Switch
                      value={!!role.modules[nav]}
                      onValueChange={(v) => toggle(role, nav, v)}
                      trackColor={{ true: colors.primary }}
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

/* ------------------------------- Users ---------------------------------- */

function UsersPanel() {
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
  if (users.length === 0) return <EmptyOrError icon="👤" message="No users found." />;

  return (
    <ScrollView contentContainerStyle={styles.content}>
      <Text style={styles.hint}>Assign roles to a user. They gain every module their roles allow.</Text>
      {roles.length === 0 ? (
        <Text style={styles.warn}>No roles exist yet — create them in the web app first.</Text>
      ) : null}
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
                      trackColor={{ true: colors.primary }}
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

const styles = StyleSheet.create({
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
  card: { padding: 0, overflow: "hidden" },
  cardHead: { flexDirection: "row", alignItems: "center", padding: spacing.lg },
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
});
