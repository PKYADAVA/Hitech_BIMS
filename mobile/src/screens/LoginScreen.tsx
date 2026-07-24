import React, { useState } from "react";
import { KeyboardAvoidingView, Platform, StyleSheet, Text, View } from "react-native";

import { Button, Field, Screen } from "@/components/ui";
import { useAuthStore } from "@/store/authStore";
import { colors, spacing } from "@/theme";

export function LoginScreen() {
  const login = useAuthStore((s) => s.login);
  const error = useAuthStore((s) => s.error);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const onSubmit = async () => {
    setSubmitting(true);
    try {
      await login(username.trim(), password);
    } catch {
      // error text is surfaced from the store below
    } finally {
      setSubmitting(false);
    }
  };

  const disabled = !username.trim() || !password;

  return (
    <Screen>
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        style={styles.wrap}
      >
        <View style={styles.header}>
          <Text style={styles.brand}>Hitech BIMS</Text>
          <Text style={styles.subtitle}>Sign in to continue</Text>
        </View>

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
      </KeyboardAvoidingView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, justifyContent: "center", padding: spacing.xl },
  header: { alignItems: "center", marginBottom: spacing.xl },
  brand: { fontSize: 28, fontWeight: "800", color: colors.text },
  subtitle: { color: colors.textMuted, marginTop: spacing.xs },
  error: { color: colors.danger, marginBottom: spacing.md, textAlign: "center" },
});
