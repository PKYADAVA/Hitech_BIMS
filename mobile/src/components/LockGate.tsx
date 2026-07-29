import * as LocalAuthentication from "expo-local-authentication";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { AppState, Text, View } from "react-native";

import { useAuthStore } from "@/store/authStore";
import { useSettingsStore } from "@/store/settingsStore";
import { AppIcon } from "@/components/AppIcon";
import { makeStyles, radius, spacing, type, useTheme } from "@/theme";
import { Button } from "./ui";

/** True if the device can actually do biometric / passcode auth. */
export async function biometricsAvailable(): Promise<boolean> {
  try {
    const hw = await LocalAuthentication.hasHardwareAsync();
    const enrolled = await LocalAuthentication.isEnrolledAsync();
    return hw && enrolled;
  } catch {
    return false;
  }
}

/**
 * Gates the app behind biometric auth when the user has enabled App Lock.
 * Locks on background and re-prompts on return to foreground.
 */
export function LockGate({ children }: { children: React.ReactNode }) {
  const enabled = useSettingsStore((s) => s.appLockEnabled);
  const hydrated = useSettingsStore((s) => s.hydrated);
  const signedIn = useAuthStore((s) => s.status === "signedIn");
  const { colors } = useTheme();
  const styles = useStyles();

  const active = hydrated && enabled && signedIn;
  const [locked, setLocked] = useState(true);
  const authing = useRef(false);

  const authenticate = useCallback(async () => {
    if (authing.current) return;
    authing.current = true;
    try {
      const res = await LocalAuthentication.authenticateAsync({
        promptMessage: "Unlock Hitech BIMS",
        fallbackLabel: "Use passcode",
      });
      if (res.success) setLocked(false);
    } finally {
      authing.current = false;
    }
  }, []);

  // Lock on background; prompt when active & locked.
  useEffect(() => {
    if (!active) {
      setLocked(false);
      return;
    }
    setLocked(true);
    const sub = AppState.addEventListener("change", (state) => {
      if (state === "background" || state === "inactive") setLocked(true);
    });
    return () => sub.remove();
  }, [active]);

  useEffect(() => {
    if (active && locked) authenticate();
  }, [active, locked, authenticate]);

  if (active && locked) {
    return (
      <View style={styles.wrap}>
        <View style={styles.logo}>
          <AppIcon name="lock-outline" size={44} color={colors.onDark} />
        </View>
        <Text style={styles.title}>Hitech BIMS is locked</Text>
        <Text style={styles.sub}>Authenticate to continue</Text>
        <View style={styles.btn}>
          <Button title="Unlock" onPress={authenticate} />
        </View>
      </View>
    );
  }

  return <>{children}</>;
}

const useStyles = makeStyles((colors) => ({
  wrap: { flex: 1, backgroundColor: colors.primaryDark, alignItems: "center", justifyContent: "center", padding: spacing.xl, gap: spacing.sm },
  logo: {
    width: 84,
    height: 84,
    borderRadius: radius.xl,
    backgroundColor: "rgba(255,255,255,0.16)",
    alignItems: "center",
    justifyContent: "center",
    marginBottom: spacing.md,
  },
  glyph: { fontSize: 40 },
  title: { ...type.h2, color: colors.onDark },
  sub: { ...type.body, color: "rgba(255,255,255,0.85)" },
  btn: { alignSelf: "stretch", marginTop: spacing.lg },
}));
