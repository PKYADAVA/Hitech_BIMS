import React, { useState } from "react";
import { Alert, ScrollView, StyleSheet, Switch, Text, View } from "react-native";

import { ChangePasswordModal } from "@/components/ChangePasswordModal";
import { biometricsAvailable } from "@/components/LockGate";
import { Button, Card, DetailRow, Divider, Screen } from "@/components/ui";
import { API_BASE_URL } from "@/config";
import { sendTestPush } from "@/push";
import { colors, radius, spacing, type } from "@/theme";
import { useAuthStore } from "@/store/authStore";
import { useSettingsStore } from "@/store/settingsStore";

export function ProfileScreen() {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const [pwOpen, setPwOpen] = useState(false);
  const appLock = useSettingsStore((s) => s.appLockEnabled);
  const setAppLock = useSettingsStore((s) => s.setAppLock);

  const onToggleLock = async (v: boolean) => {
    if (v && !(await biometricsAvailable())) {
      Alert.alert(
        "Not available",
        "Set up Face ID / fingerprint (or a device passcode) first, then enable App Lock."
      );
      return;
    }
    await setAppLock(v);
  };

  const onTestPush = async () => {
    try {
      const res = await sendTestPush();
      Alert.alert(
        res.sent > 0 ? "Sent ✓" : "No devices",
        res.sent > 0
          ? `Push sent to ${res.sent} device(s).`
          : res.error || "This device isn't registered for push yet (needs the installed app, not Expo Go)."
      );
    } catch (e) {
      Alert.alert("Failed", (e as Error)?.message ?? "Could not send test push.");
    }
  };
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

        <Card style={styles.securityRow}>
          <View style={{ flex: 1 }}>
            <Text style={styles.secTitle}>App Lock</Text>
            <Text style={styles.secSub}>Require Face ID / fingerprint to open</Text>
          </View>
          <Switch value={appLock} onValueChange={onToggleLock} trackColor={{ true: colors.primary }} />
        </Card>

        <Card>
          <Text style={styles.apiLabel}>Connected to</Text>
          <Text style={styles.api} selectable>
            {API_BASE_URL}
          </Text>
        </Card>

        <Button title="Change password" variant="ghost" onPress={() => setPwOpen(true)} />
        <Button title="Send test notification" variant="ghost" onPress={onTestPush} />
        <Button title="Log out" variant="danger" onPress={logout} />
        <Text style={styles.version}>Hitech BIMS · v0.1.0</Text>
      </ScrollView>

      <ChangePasswordModal visible={pwOpen} onClose={() => setPwOpen(false)} />
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
  securityRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.md },
  secTitle: { ...type.title, color: colors.text },
  secSub: { ...type.caption, color: colors.textMuted, marginTop: 2 },
  apiLabel: { ...type.label, color: colors.textFaint, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 2 },
  api: { ...type.mono, color: colors.text },
  version: { ...type.caption, color: colors.textFaint, textAlign: "center", marginTop: spacing.sm },
});
