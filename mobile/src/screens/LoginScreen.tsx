import { StatusBar } from "expo-status-bar";
import React, { useState } from "react";
import {
  ImageBackground,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { AppIcon } from "@/components/AppIcon";
import { Button, Field } from "@/components/ui";
import { colors, radius, shadow, spacing, type } from "@/theme";
import { useAuthStore } from "@/store/authStore";

// Bundled poultry photo — offline, reliable login backdrop.
const BG = require("../../assets/poultry.jpg");

export function LoginScreen() {
  const login = useAuthStore((s) => s.login);
  const error = useAuthStore((s) => s.error);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const disabled = !username.trim() || !password;

  const onSubmit = async () => {
    setSubmitting(true);
    try {
      await login(username.trim(), password);
    } catch {
      // error text surfaced from the store below
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <ImageBackground source={BG} style={styles.bg} resizeMode="cover">
      <StatusBar style="light" />
      <View style={styles.scrim} />
      <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
        <KeyboardAvoidingView
          style={styles.flex}
          behavior={Platform.OS === "ios" ? undefined : "height"}
        >
          <ScrollView
            contentContainerStyle={styles.scroll}
            keyboardShouldPersistTaps="handled"
            keyboardDismissMode="interactive"
            automaticallyAdjustKeyboardInsets
            showsVerticalScrollIndicator={false}
          >
            {/* Brand over the photo */}
            <View style={styles.brandWrap}>
              <View style={styles.logo}>
                <AppIcon emoji="🐔" size={40} color={colors.onDark} />
              </View>
              <Text style={styles.brand}>Hitech BIMS</Text>
              <Text style={styles.tagline}>Poultry &amp; Hatchery Management</Text>
            </View>

            {/* Sign-in card */}
            <View style={[styles.card, shadow(3)]}>
              <Text style={styles.cardTitle}>Welcome back</Text>
              <Text style={styles.cardSub}>Sign in to continue</Text>

              <Field
                label="Username"
                value={username}
                onChangeText={setUsername}
                placeholder="your.username"
                autoCorrect={false}
                returnKeyType="next"
              />
              <Field
                label="Password"
                value={password}
                onChangeText={setPassword}
                placeholder="••••••••"
                secureTextEntry
                returnKeyType="go"
                onSubmitEditing={disabled ? undefined : onSubmit}
              />

              {error ? <Text style={styles.error}>{error}</Text> : null}

              <Button title="Sign In" onPress={onSubmit} loading={submitting} disabled={disabled} />
            </View>
          </ScrollView>
        </KeyboardAvoidingView>
      </SafeAreaView>
    </ImageBackground>
  );
}

const styles = StyleSheet.create({
  bg: { flex: 1, backgroundColor: colors.primaryDark },
  scrim: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(6,20,12,0.55)" },
  safe: { flex: 1 },
  flex: { flex: 1 },
  scroll: { flexGrow: 1, justifyContent: "flex-end", padding: spacing.lg },

  brandWrap: { alignItems: "center", marginBottom: spacing.xl, gap: spacing.xs },
  logo: {
    width: 76,
    height: 76,
    borderRadius: 24,
    backgroundColor: "rgba(255,255,255,0.16)",
    borderWidth: 1,
    borderColor: "rgba(255,255,255,0.3)",
    alignItems: "center",
    justifyContent: "center",
    marginBottom: spacing.sm,
  },
  logoGlyph: { fontSize: 40 },
  brand: { ...type.h1, fontSize: 30, color: colors.onDark, textShadowColor: "rgba(0,0,0,0.35)", textShadowRadius: 8 },
  tagline: { ...type.body, color: "rgba(255,255,255,0.9)" },

  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.xl,
    padding: spacing.xl,
  },
  cardTitle: { ...type.h2, color: colors.text },
  cardSub: { ...type.body, color: colors.textMuted, marginTop: 2, marginBottom: spacing.lg },
  error: {
    ...type.label,
    color: colors.danger,
    marginBottom: spacing.md,
    textAlign: "center",
  },
});
