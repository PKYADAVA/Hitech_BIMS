import React from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  TextInputProps,
  View,
  ViewStyle,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { AppIcon } from "@/components/AppIcon";
import { colors, radius, shadow, spacing, type } from "@/theme";

/* ------------------------------------------------------------------ */
/* Layout                                                              */
/* ------------------------------------------------------------------ */

/** Screen wrapper with safe-area insets + page background. */
export function Screen({
  children,
  edges = ["top", "left", "right"],
}: {
  children: React.ReactNode;
  edges?: ("top" | "bottom" | "left" | "right")[];
}) {
  return (
    <SafeAreaView style={styles.screen} edges={edges}>
      {children}
    </SafeAreaView>
  );
}

/** Elevated surface. Becomes pressable (with feedback) when `onPress` is set. */
export function Card({
  children,
  onPress,
  style,
  padded = true,
}: {
  children: React.ReactNode;
  onPress?: () => void;
  style?: ViewStyle;
  padded?: boolean;
}) {
  const content = [styles.card, padded && styles.cardPadded, style];
  if (!onPress) return <View style={content}>{children}</View>;
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [...content, pressed && styles.pressed]}
    >
      {children}
    </Pressable>
  );
}

export function Divider() {
  return <View style={styles.divider} />;
}

export function SectionHeader({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: React.ReactNode;
}) {
  return (
    <View style={styles.sectionHeader}>
      <View style={{ flex: 1 }}>
        <Text style={styles.sectionTitle}>{title}</Text>
        {subtitle ? <Text style={styles.sectionSubtitle}>{subtitle}</Text> : null}
      </View>
      {action}
    </View>
  );
}

/* ------------------------------------------------------------------ */
/* Iconography + badges                                                */
/* ------------------------------------------------------------------ */

/** Rounded tinted square holding an emoji glyph — the app's icon language. */
export function IconCircle({
  icon,
  color = colors.primary,
  tint,
  size = 44,
}: {
  icon: string;
  color?: string;
  tint?: string;
  size?: number;
}) {
  return (
    <View
      style={[
        styles.iconCircle,
        {
          width: size,
          height: size,
          borderRadius: size / 3,
          backgroundColor: tint ?? withAlpha(color, 0.12),
        },
      ]}
    >
      <AppIcon emoji={icon} size={size * 0.5} color={color} />
    </View>
  );
}

export type BadgeTone = "neutral" | "success" | "danger" | "warning" | "info" | "brand";

export function Badge({ label, tone = "neutral" }: { label: string; tone?: BadgeTone }) {
  const map: Record<BadgeTone, { bg: string; fg: string }> = {
    neutral: { bg: colors.surfaceAlt, fg: colors.textMuted },
    success: { bg: colors.successLight, fg: colors.success },
    danger: { bg: colors.dangerLight, fg: colors.danger },
    warning: { bg: colors.warningLight, fg: "#b45309" },
    info: { bg: colors.infoLight, fg: colors.info },
    brand: { bg: colors.primaryLight, fg: colors.primaryDark },
  };
  const c = map[tone];
  return (
    <View style={[styles.badge, { backgroundColor: c.bg }]}>
      <Text style={[styles.badgeText, { color: c.fg }]}>{label}</Text>
    </View>
  );
}

/* ------------------------------------------------------------------ */
/* Data display                                                        */
/* ------------------------------------------------------------------ */

/** A tappable row: leading icon, title + subtitle, trailing value/badge, chevron. */
export function ListItem({
  icon,
  accent = colors.primary,
  title,
  subtitle,
  trailing,
  onPress,
}: {
  icon?: string;
  accent?: string;
  title: string;
  subtitle?: string;
  trailing?: React.ReactNode;
  onPress?: () => void;
}) {
  return (
    <Card onPress={onPress} style={styles.listItem}>
      {icon ? <IconCircle icon={icon} color={accent} /> : null}
      <View style={styles.listItemBody}>
        <Text style={styles.listItemTitle} numberOfLines={1}>
          {title}
        </Text>
        {subtitle ? (
          <Text style={styles.listItemSub} numberOfLines={1}>
            {subtitle}
          </Text>
        ) : null}
      </View>
      {trailing}
      {onPress ? <AppIcon name="chevron-right" size={22} color={colors.textFaint} /> : null}
    </Card>
  );
}

/** Compact metric tile for dashboards / hub headers. */
export function StatTile({
  label,
  value,
  icon,
  accent = colors.primary,
}: {
  label: string;
  value: string;
  icon?: string;
  accent?: string;
}) {
  return (
    <View style={[styles.stat, shadow(1)]}>
      {icon ? (
        <View style={[styles.statDot, { backgroundColor: withAlpha(accent, 0.14) }]}>
          <AppIcon emoji={icon} size={16} color={accent} />
        </View>
      ) : null}
      <Text style={styles.statValue} numberOfLines={1}>
        {value}
      </Text>
      <Text style={styles.statLabel} numberOfLines={1}>
        {label}
      </Text>
    </View>
  );
}

/** label / value row for detail screens. */
export function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.detailRow}>
      <Text style={styles.detailLabel}>{label}</Text>
      <Text style={styles.detailValue} selectable>
        {value}
      </Text>
    </View>
  );
}

/* ------------------------------------------------------------------ */
/* Inputs / actions                                                    */
/* ------------------------------------------------------------------ */

export function SearchBar({
  value,
  onChangeText,
  placeholder = "Search…",
}: {
  value: string;
  onChangeText: (t: string) => void;
  placeholder?: string;
}) {
  return (
    <View style={styles.search}>
      <AppIcon name="magnify" size={18} color={colors.textFaint} style={styles.searchIcon} />
      <TextInput
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor={colors.textFaint}
        style={styles.searchInput}
        autoCorrect={false}
        autoCapitalize="none"
        clearButtonMode="while-editing"
      />
    </View>
  );
}

export function Button({
  title,
  onPress,
  loading,
  disabled,
  variant = "primary",
}: {
  title: string;
  onPress: () => void;
  loading?: boolean;
  disabled?: boolean;
  variant?: "primary" | "ghost" | "danger";
}) {
  const isPrimary = variant === "primary";
  const isDanger = variant === "danger";
  const fg = isPrimary || isDanger ? "#fff" : colors.primary;
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled || loading}
      style={({ pressed }) => [
        styles.btn,
        isPrimary && styles.btnPrimary,
        isDanger && styles.btnDanger,
        variant === "ghost" && styles.btnGhost,
        (disabled || loading) && styles.btnDisabled,
        pressed && styles.pressed,
      ]}
    >
      {loading ? (
        <ActivityIndicator color={fg} />
      ) : (
        <Text style={[styles.btnText, { color: fg }]}>{title}</Text>
      )}
    </Pressable>
  );
}

export function Field({
  label,
  style,
  ...props
}: TextInputProps & { label: string }) {
  return (
    <View style={{ marginBottom: spacing.lg }}>
      <Text style={styles.fieldLabel}>{label}</Text>
      <TextInput
        placeholderTextColor={colors.textFaint}
        style={[styles.input, style]}
        autoCapitalize="none"
        {...props}
      />
    </View>
  );
}

/* ------------------------------------------------------------------ */
/* States                                                              */
/* ------------------------------------------------------------------ */

export function Loading({ label }: { label?: string }) {
  return (
    <View style={styles.center}>
      <ActivityIndicator color={colors.primary} size="large" />
      {label ? <Text style={styles.muted}>{label}</Text> : null}
    </View>
  );
}

export function EmptyOrError({
  message,
  title,
  icon = "🗂️",
  accent = colors.textFaint,
  onRetry,
  actionLabel,
  onAction,
  secondaryLabel,
  onSecondary,
}: {
  message: string;
  /** Optional bold headline shown above the message. */
  title?: string;
  icon?: string;
  /** Tints the icon + its halo (defaults to a neutral grey). */
  accent?: string;
  onRetry?: () => void;
  /** Primary call-to-action (e.g. "Add Sale"). */
  actionLabel?: string;
  onAction?: () => void;
  /** Secondary, lower-emphasis action. */
  secondaryLabel?: string;
  onSecondary?: () => void;
}) {
  const isNeutral = accent === colors.textFaint;
  return (
    <View style={styles.center}>
      <View style={[styles.emptyIconWrap, !isNeutral && { backgroundColor: withAlpha(accent, 0.12) }]}>
        <AppIcon emoji={icon} size={40} color={accent} />
      </View>
      {title ? <Text style={styles.emptyTitle}>{title}</Text> : null}
      <Text style={styles.muted}>{message}</Text>
      {onAction && actionLabel ? (
        <View style={styles.emptyAction}>
          <Button title={actionLabel} onPress={onAction} />
        </View>
      ) : null}
      {onSecondary && secondaryLabel ? (
        <Button title={secondaryLabel} variant="ghost" onPress={onSecondary} />
      ) : null}
      {onRetry ? <Button title="Retry" variant="ghost" onPress={onRetry} /> : null}
    </View>
  );
}

/* ------------------------------------------------------------------ */

/** Add an alpha channel to a #rrggbb hex color. */
export function withAlpha(hex: string, alpha: number): string {
  const a = Math.round(Math.max(0, Math.min(1, alpha)) * 255)
    .toString(16)
    .padStart(2, "0");
  return `${hex}${a}`;
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.bg },
  center: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: spacing.xl,
    gap: spacing.md,
  },
  muted: { color: colors.textMuted, textAlign: "center", ...type.body },
  emptyTitle: { ...type.h3, color: colors.text, textAlign: "center" },
  emptyAction: { minWidth: 180, marginTop: spacing.xs },
  emptyIconWrap: {
    width: 84,
    height: 84,
    borderRadius: radius.pill,
    backgroundColor: colors.surfaceAlt,
    alignItems: "center",
    justifyContent: "center",
  },
  pressed: { opacity: 0.88, transform: [{ scale: 0.975 }] },

  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
  },
  cardPadded: { padding: spacing.lg },
  divider: { height: 1, backgroundColor: colors.border, marginVertical: spacing.sm },

  sectionHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginTop: spacing.lg,
    marginBottom: spacing.sm,
    paddingHorizontal: spacing.xs,
  },
  sectionTitle: { ...type.h3, color: colors.text },
  sectionSubtitle: { ...type.caption, color: colors.textMuted, marginTop: 1 },

  iconCircle: { alignItems: "center", justifyContent: "center" },

  badge: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 3,
    borderRadius: radius.pill,
    alignSelf: "flex-start",
  },
  badgeText: { ...type.caption, fontWeight: "700" },

  listItem: { flexDirection: "row", alignItems: "center", gap: spacing.md, padding: spacing.md },
  listItemBody: { flex: 1, gap: 2 },
  listItemTitle: { ...type.title, color: colors.text },
  listItemSub: { ...type.caption, color: colors.textMuted },
  chevron: { fontSize: 24, color: colors.textFaint, marginLeft: 2 },

  stat: {
    flex: 1,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.md,
    gap: 2,
    borderWidth: 1,
    borderColor: colors.border,
  },
  statDot: {
    width: 30,
    height: 30,
    borderRadius: 9,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: spacing.xs,
  },
  statValue: { ...type.h2, color: colors.text },
  statLabel: { ...type.caption, color: colors.textMuted },

  detailRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    gap: spacing.lg,
    paddingVertical: spacing.sm,
  },
  detailLabel: { ...type.label, color: colors.textMuted, flexShrink: 0, maxWidth: "45%" },
  detailValue: { ...type.body, color: colors.text, flex: 1, textAlign: "right" },

  search: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    paddingHorizontal: spacing.md,
    height: 44,
  },
  searchIcon: { opacity: 0.9 },
  searchInput: { flex: 1, ...type.body, color: colors.text, padding: 0 },

  btn: {
    height: 50,
    borderRadius: radius.md,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: spacing.lg,
    flexDirection: "row",
    gap: spacing.sm,
  },
  btnPrimary: { backgroundColor: colors.primary },
  btnDanger: { backgroundColor: colors.danger },
  btnGhost: { backgroundColor: "transparent" },
  btnDisabled: { opacity: 0.5 },
  btnText: { ...type.h3, color: "#fff" },

  fieldLabel: { ...type.label, color: colors.text, marginBottom: spacing.xs },
  input: {
    height: 50,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    backgroundColor: colors.surface,
    color: colors.text,
    ...type.body,
  },
});
