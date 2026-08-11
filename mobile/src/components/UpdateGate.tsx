import React, { useState } from "react";
import { Alert, Linking, Modal, Pressable, Text, View } from "react-native";

import { useAppVersion } from "@/api/appVersion";
import { APP_VERSION_CODE } from "@/config";
import { AppIcon } from "./AppIcon";
import { makeStyles, radius, spacing, type, useTheme } from "@/theme";

/**
 * The sideload update prompt.
 *
 * This app has no store to push an update through, so nothing tells an
 * already-installed copy a newer one exists unless it asks — this is that
 * ask, on every launch. Both cases are the same centered dialog (a thin top
 * banner was too easy to miss or mis-tap); a normal release adds a "Later"
 * button, a release the server marks `force_update` (a breaking API change
 * the old build cannot safely keep talking through) does not — there is no
 * way past it but to update.
 */
export function UpdateGate() {
  const { data } = useAppVersion();
  const [dismissed, setDismissed] = useState(false);
  const styles = useStyles();
  const { colors } = useTheme();

  const hasUpdate =
    !!data?.latest_version_code && data.latest_version_code > APP_VERSION_CODE;
  if (!hasUpdate || !data) return null;
  if (dismissed && !data.force_update) return null;

  // Linking.openURL rejects rather than throwing, and a release build shows
  // nothing for an unhandled rejection — exactly "the button does nothing".
  // Catching it and saying so beats a silent no-op every time.
  const openDownload = () => {
    if (!data.download_url) {
      Alert.alert("No download link", "This release has no APK file attached yet.");
      return;
    }
    Linking.openURL(data.download_url).catch(() => {
      Alert.alert(
        "Could not open the download",
        "Copy this link and open it in your browser instead:\n\n" + data.download_url,
      );
    });
  };

  return (
    <Modal visible transparent animationType="fade" statusBarTranslucent>
      <View style={styles.overlay}>
        <View style={styles.card}>
          <AppIcon name="cloud-download-outline" size={36} color={colors.tint} />
          <Text style={styles.title}>
            {data.force_update ? "Update Required" : "Update Available"}
          </Text>
          <Text style={styles.body}>
            {data.force_update
              ? `Version ${data.latest_version} is required to keep using Hitech BIMS.`
              : `Version ${data.latest_version} is available.`}
          </Text>
          {data.notes ? <Text style={styles.notes}>{data.notes}</Text> : null}
          <Pressable style={styles.button} onPress={openDownload} accessibilityRole="button">
            <AppIcon name="download-outline" size={18} color={colors.onDark} />
            <Text style={styles.buttonText}>Update Now</Text>
          </Pressable>
          {!data.force_update ? (
            <Pressable onPress={() => setDismissed(true)} accessibilityRole="button">
              <Text style={styles.later}>Later</Text>
            </Pressable>
          ) : null}
        </View>
      </View>
    </Modal>
  );
}

const useStyles = makeStyles((colors) => ({
  overlay: {
    flex: 1, backgroundColor: "rgba(0,0,0,0.6)", alignItems: "center", justifyContent: "center",
    padding: spacing.lg,
  },
  card: {
    width: "100%", maxWidth: 360, backgroundColor: colors.surface, borderRadius: radius.lg,
    padding: spacing.lg, alignItems: "center", gap: spacing.sm,
  },
  title: { ...type.h3, color: colors.text },
  body: { ...type.body, color: colors.textMuted, textAlign: "center" },
  notes: { ...type.caption, color: colors.textFaint, textAlign: "center" },
  button: {
    flexDirection: "row", alignItems: "center", gap: spacing.xs,
    backgroundColor: colors.tint, borderRadius: radius.md,
    paddingVertical: spacing.sm, paddingHorizontal: spacing.lg, marginTop: spacing.sm,
  },
  buttonText: { ...type.title, color: colors.onDark },
  later: { ...type.body, color: colors.textMuted, marginTop: spacing.xs, padding: spacing.xs },
}));