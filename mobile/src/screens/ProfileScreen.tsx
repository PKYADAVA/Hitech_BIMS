import React from "react";
import { ScrollView, StyleSheet, Text, View } from "react-native";

import { Button, Card, DetailRow, Divider, Screen } from "@/components/ui";
import { API_BASE_URL } from "@/config";
import { colors, radius, spacing, type } from "@/theme";
import { useAuthStore } from "@/store/authStore";

export function ProfileScreen() {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const initials = (user?.full_name || user?.username || "?")
    .split(" ")
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

  return (
    <Screen>
      <ScrollView contentContainerStyle={styles.content}>
        <Card style={styles.header}>
          <View style={styles.avatar}>
            <Text style={styles.avatarText}>{initials}</Text>
          </View>
          <Text style={styles.name}>{user?.full_name || user?.username}</Text>
          <Text style={styles.sub}>{user?.email || "—"}</Text>
        </Card>

        <Card>
          <DetailRow label="Username" value={user?.username ?? "—"} />
          <Divider />
          <DetailRow label="Role" value={user?.role || "User"} />
          <Divider />
          <DetailRow label="Department" value={user?.department || "—"} />
          <Divider />
          <DetailRow label="Access" value={user?.is_superuser ? "Administrator" : user?.is_staff ? "Staff" : "Standard"} />
        </Card>

        <Card>
          <Text style={styles.apiLabel}>Connected to</Text>
          <Text style={styles.api} selectable>
            {API_BASE_URL}
          </Text>
        </Card>

        <Button title="Log out" variant="danger" onPress={logout} />
        <Text style={styles.version}>Hitech BIMS · v0.1.0</Text>
      </ScrollView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  content: { padding: spacing.md, gap: spacing.md, paddingBottom: spacing.xxl },
  header: { alignItems: "center", gap: spacing.xs, paddingVertical: spacing.xl },
  avatar: {
    width: 72,
    height: 72,
    borderRadius: 36,
    backgroundColor: colors.primary,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: spacing.sm,
  },
  avatarText: { ...type.h1, color: colors.onDark },
  name: { ...type.h2, color: colors.text },
  sub: { ...type.body, color: colors.textMuted },
  apiLabel: { ...type.label, color: colors.textFaint, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 2 },
  api: { ...type.mono, color: colors.text },
  version: { ...type.caption, color: colors.textFaint, textAlign: "center", marginTop: spacing.sm },
});
