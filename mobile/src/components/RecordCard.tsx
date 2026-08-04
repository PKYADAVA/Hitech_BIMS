import React from "react";
import { Pressable, Text, View } from "react-native";

import { CardView } from "@/config/catalog";
import { makeStyles, radius, spacing, type, useTheme } from "@/theme";
import { AppIcon, IconName } from "./AppIcon";
import { Badge, Card, IconCircle } from "./ui";

/**
 * One action offered on a card — the register's Actions column, as a row of
 * buttons under the record rather than a column beside it.
 */
export interface RecordAction {
  key: string;
  label: string;
  icon: IconName;
  /** Destructive actions read in the danger colour, as they do on the web. */
  danger?: boolean;
  onPress: () => void;
}

/** Renders one catalog CardView: leading icon, title/subtitle, trailing value + badge. */
export function RecordCard({
  view,
  icon,
  accent,
  onPress,
  actions,
}: {
  view: CardView;
  icon: string;
  accent: string;
  onPress?: () => void;
  actions?: RecordAction[];
}) {
  const styles = useStyles();
  const { colors } = useTheme();
  return (
    <Card onPress={onPress} style={actions?.length ? styles.cardWithActions : styles.card}>
      <View style={styles.main}>
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
      </View>
      {actions?.length ? (
        <View style={styles.actions}>
          {actions.map((a) => (
            <Pressable key={a.key} onPress={a.onPress} hitSlop={6}
                       accessibilityLabel={a.label} style={styles.action}>
              <AppIcon name={a.icon} size={16}
                       color={a.danger ? colors.danger : colors.tint} />
              <Text style={[styles.actionText,
                            { color: a.danger ? colors.danger : colors.tint }]}>
                {a.label}
              </Text>
            </Pressable>
          ))}
        </View>
      ) : null}
    </Card>
  );
}

const useStyles = makeStyles((colors) => ({
  card: { flexDirection: "row", alignItems: "center", gap: spacing.md, padding: spacing.md },
  // With actions the card becomes two stacked rows, so the record and its
  // buttons cannot fight for the same horizontal space on a narrow phone.
  cardWithActions: { padding: spacing.md },
  main: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  actions: {
    flexDirection: "row", justifyContent: "flex-end", flexWrap: "wrap",
    gap: spacing.xs, marginTop: spacing.sm,
    borderTopWidth: 1, borderTopColor: colors.border, paddingTop: spacing.sm,
  },
  action: {
    flexDirection: "row", alignItems: "center", gap: spacing.xs,
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm,
    paddingHorizontal: spacing.sm, paddingVertical: spacing.xs,
  },
  actionText: { ...type.caption, fontWeight: "700" },
  body: { flex: 1, gap: 3 },
  title: { ...type.title, color: colors.text },
  subtitle: { ...type.caption, color: colors.textMuted },
  badgeRow: { flexDirection: "row", marginTop: 2 },
  trailing: { alignItems: "flex-end", maxWidth: 120 },
  trailingValue: { ...type.h3, color: colors.text },
  trailingCaption: { ...type.caption, color: colors.textFaint, textTransform: "uppercase" },
}));
