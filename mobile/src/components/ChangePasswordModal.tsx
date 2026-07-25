import React, { useState } from "react";
import {
  Alert,
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { changePassword } from "@/api/auth";
import { ApiError } from "@/api/types";
import { Button, Field } from "@/components/ui";
import { colors, spacing, type } from "@/theme";

/** Slide-up sheet to change the signed-in user's password. */
export function ChangePasswordModal({ visible, onClose }: { visible: boolean; onClose: () => void }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reset = () => {
    setCurrent("");
    setNext("");
    setConfirm("");
    setError(null);
    setSaving(false);
  };

  const close = () => {
    reset();
    onClose();
  };

  const onSubmit = async () => {
    setError(null);
    if (!current || !next || !confirm) {
      setError("Please fill in all fields.");
      return;
    }
    if (next.length < 8) {
      setError("New password must be at least 8 characters.");
      return;
    }
    if (next !== confirm) {
      setError("New password and confirmation don't match.");
      return;
    }
    if (next === current) {
      setError("New password must be different from the current one.");
      return;
    }

    setSaving(true);
    try {
      await changePassword(current, next);
      reset();
      onClose();
      Alert.alert("Password changed", "Your password has been updated.");
    } catch (e) {
      if (e instanceof ApiError) {
        const fieldMsgs = Object.values(e.fields || {})
          .flatMap((m) => (Array.isArray(m) ? m : [String(m)]))
          .join(" ");
        setError(fieldMsgs || e.message || "Could not change password.");
      } else {
        setError((e as Error)?.message ?? "Could not change password.");
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={close} presentationStyle="pageSheet">
      <SafeAreaView style={styles.screen} edges={["top", "bottom"]}>
        <View style={styles.header}>
          <Text style={styles.title}>Change Password</Text>
          <Pressable onPress={close} hitSlop={12}>
            <Text style={styles.close}>Close</Text>
          </Pressable>
        </View>

        <KeyboardAvoidingView
          style={styles.flex}
          behavior={Platform.OS === "ios" ? "padding" : "height"}
        >
          <ScrollView
            contentContainerStyle={styles.content}
            keyboardShouldPersistTaps="handled"
            keyboardDismissMode="interactive"
            showsVerticalScrollIndicator={false}
          >
            {error ? <Text style={styles.error}>{error}</Text> : null}

            <Field
              label="Current password"
              value={current}
              onChangeText={setCurrent}
              secureTextEntry
              placeholder="Enter current password"
              textContentType="password"
            />
            <Field
              label="New password"
              value={next}
              onChangeText={setNext}
              secureTextEntry
              placeholder="At least 8 characters"
              textContentType="newPassword"
            />
            <Field
              label="Confirm new password"
              value={confirm}
              onChangeText={setConfirm}
              secureTextEntry
              placeholder="Re-enter new password"
              textContentType="newPassword"
              onSubmitEditing={onSubmit}
              returnKeyType="go"
            />

            <Button title="Update password" onPress={onSubmit} loading={saving} />
          </ScrollView>
        </KeyboardAvoidingView>
      </SafeAreaView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.bg },
  flex: { flex: 1 },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  title: { ...type.h3, color: colors.text },
  close: { ...type.title, color: colors.primary },
  content: { padding: spacing.md },
  error: {
    ...type.label,
    color: colors.danger,
    backgroundColor: colors.dangerLight,
    padding: spacing.md,
    borderRadius: 12,
    marginBottom: spacing.md,
  },
});
