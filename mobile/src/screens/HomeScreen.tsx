import React from "react";
import { ScrollView, StyleSheet, Text, View } from "react-native";

import { Button, Screen } from "@/components/ui";
import { useAuthStore } from "@/store/authStore";
import { colors, radius, spacing } from "@/theme";

export function HomeScreen() {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);

  return (
    <Screen>
      <ScrollView contentContainerStyle={styles.content}>
        <View style={styles.card}>
          <Text style={styles.hello}>Hello, {user?.full_name || user?.username} 👋</Text>
          <Text style={styles.meta}>{user?.role || "User"}{user?.department ? ` · ${user.department}` : ""}</Text>
        </View>

        <Text style={styles.section}>Modules</Text>
        <View style={styles.card}>
          <Text style={styles.item}>🐔  Broiler — Daily Entries</Text>
          <Text style={styles.item}>🥚  Hatchery — Egg Purchases</Text>
          <Text style={styles.hint}>Open a tab below to browse records.</Text>
        </View>

        <Button title="Log out" variant="ghost" onPress={logout} />
      </ScrollView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  content: { padding: spacing.md, gap: spacing.md },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    padding: spacing.lg,
    borderWidth: 1,
    borderColor: colors.border,
    gap: spacing.xs,
  },
  hello: { fontSize: 18, fontWeight: "700", color: colors.text },
  meta: { color: colors.textMuted },
  section: { fontWeight: "700", color: colors.text, marginTop: spacing.sm, marginLeft: spacing.xs },
  item: { fontSize: 15, color: colors.text, paddingVertical: spacing.xs },
  hint: { color: colors.textMuted, marginTop: spacing.sm, fontSize: 13 },
});
