import React, { useState } from "react";
import { Linking, Modal, Pressable, Text, View } from "react-native";

import { useAppVersion } from "@/api/appVersion";
import { APP_VERSION_CODE } from "@/config";
import { AppIcon } from "./AppIcon";
import { makeStyles, radius, spacing, type, useTheme } from "@/theme";

/**
 * The sideload update prompt.
 *
 * This app has no store to push an update through, so nothing tells an
 * already-installed copy a newer one exists unless it asks — this is that
 * ask, on every launch. A normal release is a dismissible banner; a release
 * the server marks `force_update` (a breaking API change the old build
 * cannot safely keep talking through) is a blocking modal with no way past
 * it but to update.
 */
export function UpdateGate() {
  const { data } = useAppVersion();
  const [dismissed, setDismissed] = useState(false);
  const styles = useStyles();
  const { colors } = useTheme();

  const hasUpdate =
    !!data?.latest_version_code && data.latest_version_code > APP_VERSION_CODE;
  if (!hasUpdate) return null;

  const openDownload = () => {
    if (data.download_url) Linking.openURL(data.download_url);
  };

  if (data.force_update) {
    return (
      <Modal visible transparent animationType="fade" statusBarTranslucent>
        <View style={styles.overlay}>
          <View style={styles.card}>
            <AppIcon name="cloud-download-outline" size={36} color={colors.tint} />
            <Text style={styles.title}>Update Required</Text>
            <Text style={styles.body}>
              Version {data.latest_version} is required to keep using Hitech BIMS.
            </Text>
            {data.notes ? <Text style={styles.notes}>{data.notes}</Text> : null}
            <Pressable style={styles.button} onPress={openDownload} accessibilityRole="button">
              <AppIcon name="download-outline" size={18} color={colors.onDark} />
              <Text style={styles.buttonText}>Update Now</Text>
            </Pressable>
          </View>
        </View>
      </Modal>
    );
  }

  if (dismissed) return null;
  return (
    <View style={styles.banner}>
      <AppIcon name="cloud-download-outline" size={16} color={colors.tint} />
      <Text style={styles.bannerText} numberOfLines={1}>
        Update available — v{data.latest_version}
      </Text>
      <Pressable onPress={openDownload} hitSlop={8}>
        <Text style={styles.bannerAction}>Update</Text>
      </Pressable>
      <Pressable onPress={() => setDismissed(true)} hitSlop={8} accessibilityLabel="Dismiss">
        <AppIcon name="close" size={16} color={colors.textMuted} />
      </Pressable>
    </View>
  );
}

const useStyles = makeStyles((colors) => ({
  banner: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    backgroundColor: colors.infoLight, paddingVertical: spacing.xs, paddingHorizontal: spacing.md,
  },
  bannerText: { ...type.caption, color: colors.info, fontWeight: "700", flex: 1 },
  bannerAction: { ...type.caption, color: colors.info, fontWeight: "800" },

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
}));