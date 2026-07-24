import React from "react";
import { StyleSheet, Text, View } from "react-native";

import { CardView } from "@/config/catalog";
import { colors, spacing, type } from "@/theme";
import { Badge, Card, IconCircle } from "./ui";

/** Renders one catalog CardView: leading icon, title/subtitle, trailing value + badge. */
export function RecordCard({
  view,
  icon,
  accent,
  onPress,
}: {
  view: CardView;
  icon: string;
  accent: string;
  onPress?: () => void;
}) {
  return (
    <Card onPress={onPress} style={styles.card}>
      <IconCircle icon={icon} color={accent} />
      <View style={styles.body}>
        <Text style={styles.title} numberOfLines={1}>
          {view.title}
        </Text>
        {view.subtitle ? (
          <Text style={styles.subtitle} numberOfLines={1}>
            {view.subtitle}
          </Text>
        ) : null}
        {view.badge ? (
          <View style={styles.badgeRow}>
            <Badge label={view.badge.label} tone={view.badge.tone} />
          </View>
        ) : null}
      </View>
      {view.trailing ? (
        <View style={styles.trailing}>
          <Text style={styles.trailingValue} numberOfLines={1}>
            {view.trailing.value}
          </Text>
          {view.trailing.caption ? (
            <Text style={styles.trailingCaption}>{view.trailing.caption}</Text>
          ) : null}
        </View>
      ) : null}
    </Card>
  );
}

const styles = StyleSheet.create({
  card: { flexDirection: "row", alignItems: "center", gap: spacing.md, padding: spacing.md },
  body: { flex: 1, gap: 3 },
  title: { ...type.title, color: colors.text },
  subtitle: { ...type.caption, color: colors.textMuted },
  badgeRow: { flexDirection: "row", marginTop: 2 },
  trailing: { alignItems: "flex-end", maxWidth: 120 },
  trailingValue: { ...type.h3, color: colors.text },
  trailingCaption: { ...type.caption, color: colors.textFaint, textTransform: "uppercase" },
});
