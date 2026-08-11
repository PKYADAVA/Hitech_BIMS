import React, { useState } from "react";
import { Alert, Pressable, ScrollView, Switch, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { ChangePasswordModal } from "@/components/ChangePasswordModal";
import { biometricsAvailable } from "@/components/LockGate";
import { AppIcon, IconName } from "@/components/AppIcon";
import { Card, IconCircle, Screen, withAlpha } from "@/components/ui";
import { AuthUser } from "@/api/types";
import { APP_VERSION } from "@/config";
import { makeStyles, spacing, radius, type, ThemePreference, useTheme } from "@/theme";
import { confirm } from "@/ui/confirm";
import { useAuthStore } from "@/store/authStore";
import { useSettingsStore } from "@/store/settingsStore";

function initialsOf(user: AuthUser | null): string {
  return (user?.full_name || user?.username || "?")
    .split(" ")
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

function accessLabel(user: AuthUser | null): string {
  if (user?.is_superuser) return "Administrator";
  if (user?.is_staff) return "Staff";
  return "Standard";
}

/** Header with the avatar + identity, on the page background. */
function ProfileHero({ user }: { user: AuthUser | null }) {
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  return (
    <View style={[styles.hero, { paddingTop: insets.top + spacing.sm }]}>
      <View style={styles.avatarRing}>
        <View style={styles.avatar}>
          <Text style={styles.avatarText}>{initialsOf(user)}</Text>
        </View>
      </View>
      <View style={styles.heroInfo}>
        <Text style={styles.name} numberOfLines={1}>
          {user?.full_name || user?.username || "—"}
        </Text>
        <Text style={styles.email} numberOfLines={1}>
          {user?.email || "No email on file"}
        </Text>
        <View style={styles.pillRow}>
          <View style={styles.heroPill}>
            <Text style={styles.heroPillText}>{user?.role || "User"}</Text>
          </View>
          <View style={styles.heroPill}>
            <Text style={styles.heroPillText}>{accessLabel(user)}</Text>
          </View>
        </View>
      </View>
    </View>
  );
}

/** Icon-led info row: leading glyph, stacked label + value. */
function InfoRow({ icon, accent, label, value }: { icon: string; accent: string; label: string; value: string }) {
  const styles = useStyles();
  return (
    <View style={styles.row}>
      <IconCircle icon={icon} color={accent} size={38} />
      <View style={styles.rowBody}>
        <Text style={styles.rowLabel}>{label}</Text>
        <Text style={styles.rowValue} numberOfLines={1}>
          {value}
        </Text>
      </View>
    </View>
  );
}

/** Tappable action row with chevron (change password, etc.). */
function ActionRow({
  icon,
  accent,
  title,
  subtitle,
  onPress,
  trailing,
  danger,
}: {
  icon: string;
  accent: string;
  title: string;
  subtitle?: string;
  onPress?: () => void;
  trailing?: React.ReactNode;
  danger?: boolean;
}) {
  const { colors } = useTheme();
  const styles = useStyles();
  const Body = (
    <>
      <IconCircle icon={icon} color={accent} size={38} />
      <View style={styles.rowBody}>
        <Text style={[styles.actionTitle, danger && { color: colors.danger }]}>{title}</Text>
        {subtitle ? <Text style={styles.rowLabel}>{subtitle}</Text> : null}
      </View>
      {trailing ?? (onPress ? <AppIcon name="chevron-right" size={22} color={colors.textFaint} /> : null)}
    </>
  );
  if (!onPress) return <View style={styles.row}>{Body}</View>;
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [styles.row, pressed && { opacity: 0.6 }]}
    >
      {Body}
    </Pressable>
  );
}

const APPEARANCE_OPTIONS: { key: ThemePreference; label: string; icon: IconName }[] = [
  { key: "light", label: "Light", icon: "white-balance-sunny" },
  { key: "dark", label: "Dark", icon: "moon-waning-crescent" },
  { key: "system", label: "System", icon: "cellphone" },
];

/** Segmented Light / Dark / System control bound to the theme preference. */
function AppearanceControl() {
  const { colors } = useTheme();
  const styles = useStyles();
  const { preference, setPreference } = useTheme();
  return (
    <View style={styles.segmentRow}>
      {APPEARANCE_OPTIONS.map((opt) => {
        const active = preference === opt.key;
        return (
          <Pressable
            key={opt.key}
            onPress={() => setPreference(opt.key)}
            style={[styles.segment, active && styles.segmentActive]}
          >
            <AppIcon name={opt.icon} size={16} color={active ? colors.onDark : colors.textMuted} />
            <Text style={[styles.segmentText, active && styles.segmentTextActive]}>{opt.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

function GroupLabel({ text }: { text: string }) {
  const styles = useStyles();
  return <Text style={styles.groupLabel}>{text}</Text>;
}

function HairLine() {
  const styles = useStyles();
  return <View style={styles.hairline} />;
}

export function ProfileScreen() {
  const { colors } = useTheme();
  const styles = useStyles();
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

  const confirmLogout = async () => {
    if (await confirm({
      title: "Log out",
      message: "Are you sure you want to sign out?",
      confirmLabel: "Log out",
      destructive: true,
    })) {
      await logout();
    }
  };

  return (
    <Screen edges={["left", "right"]}>
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        <ProfileHero user={user} />

        <View style={styles.body}>
          <GroupLabel text="Account" />
          <Card padded={false} style={styles.group}>
            <InfoRow icon="👤" accent={colors.user} label="Username" value={user?.username ?? "—"} />
            <HairLine />
            <InfoRow icon="💼" accent={colors.account} label="Role" value={user?.role || "User"} />
            <HairLine />
            <InfoRow icon="🏢" accent={colors.inventory} label="Department" value={user?.department || "—"} />
            <HairLine />
            <InfoRow icon="🛡️" accent={colors.sms} label="Access level" value={accessLabel(user)} />
          </Card>

          <GroupLabel text="Appearance" />
          <Card padded={false} style={styles.group}>
            <AppearanceControl />
          </Card>

          <GroupLabel text="Security" />
          <Card padded={false} style={styles.group}>
            <ActionRow
              icon="🔒"
              accent={colors.tint}
              title="App Lock"
              subtitle="Require Face ID / fingerprint to open"
              trailing={
                <Switch
                  value={appLock}
                  onValueChange={onToggleLock}
                  trackColor={{ true: colors.tint }}
                />
              }
            />
            <HairLine />
            <ActionRow
              icon="🔑"
              accent={colors.hatchery}
              title="Change password"
              subtitle="Update your login password"
              onPress={() => setPwOpen(true)}
            />
          </Card>

          <GroupLabel text="Session" />
          <Card padded={false} style={styles.group}>
            <ActionRow
              icon="🚪"
              accent={colors.danger}
              title="Log out"
              subtitle="Sign out of this device"
              onPress={confirmLogout}
              danger
            />
          </Card>

          <Text style={styles.version}>Hitech BIMS · v{APP_VERSION}</Text>
        </View>
      </ScrollView>

      <ChangePasswordModal visible={pwOpen} onClose={() => setPwOpen(false)} />
    </Screen>
  );
}

const useStyles = makeStyles((colors) => ({
  content: { paddingBottom: spacing.xxl },

  // Header — plain, on the page background (no dark card)
  hero: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.md,
  },
  avatarRing: {
    padding: 3,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  avatar: {
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: withAlpha(colors.primary, 0.12),
    alignItems: "center",
    justifyContent: "center",
  },
  avatarText: { ...type.h3, fontSize: 20, color: colors.tint },
  heroInfo: { flex: 1, gap: 2 },
  name: { ...type.h2, color: colors.text },
  email: { ...type.caption, color: colors.textMuted },
  pillRow: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.xs },
  heroPill: {
    paddingHorizontal: spacing.md,
    paddingVertical: 5,
    borderRadius: radius.pill,
    backgroundColor: colors.surfaceAlt,
  },
  heroPillText: { ...type.caption, color: colors.textMuted, fontWeight: "700" },

  // Body
  body: { paddingHorizontal: spacing.md, gap: spacing.xs },
  groupLabel: {
    ...type.label,
    color: colors.textFaint,
    textTransform: "uppercase",
    letterSpacing: 0.6,
    marginTop: spacing.md,
    marginBottom: spacing.sm,
    marginLeft: spacing.xs,
  },
  group: { overflow: "hidden" },

  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
  },
  rowBody: { flex: 1, gap: 2 },
  rowLabel: { ...type.caption, color: colors.textMuted },
  rowValue: { ...type.title, color: colors.text },
  actionTitle: { ...type.title, color: colors.text },
  hairline: { height: 1, backgroundColor: colors.border, marginLeft: 38 + spacing.md + spacing.md },

  // Appearance segmented control
  segmentRow: { flexDirection: "row", gap: spacing.xs, padding: spacing.sm },
  segment: {
    flex: 1,
    flexDirection: "row",
    gap: 6,
    alignItems: "center",
    justifyContent: "center",
    paddingVertical: spacing.sm,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceAlt,
  },
  segmentActive: { backgroundColor: colors.primary },
  segmentText: { ...type.label, color: colors.textMuted },
  segmentTextActive: { color: colors.onDark },

  version: { ...type.caption, color: colors.textFaint, textAlign: "center", marginTop: spacing.xl },
}));
