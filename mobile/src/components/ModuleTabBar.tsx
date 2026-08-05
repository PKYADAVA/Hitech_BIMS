/**
 * A module's own bottom bar, as the reference gives each module screen.
 *
 * Rendered once beneath a module's stack rather than per screen, so it stays
 * put while the stack pushes lists and forms over it — and so adding a screen
 * to a module does not mean remembering to add the bar to it.
 *
 * Three destinations, not the reference's five. Home and the module's own hub
 * are real places; "Menu" opens the sidebar, which reaches everything else.
 * The reference's other two are per-module shortcuts ("Farms", "Visits",
 * "Incubators") that differ for every module and would need a fourth registry
 * to describe — worth doing, but not worth inventing a button that goes
 * nowhere in the meantime.
 */
import { useNavigation, useNavigationState } from "@react-navigation/native";
import React from "react";
import { Pressable, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { AppIcon, IconName } from "@/components/AppIcon";
import { MODULES, ModuleKey } from "@/config/catalog";
import { useSideNav } from "@/store/sideNavStore";
import { makeStyles, spacing, type, withAlpha } from "@/theme";

export function ModuleTabBar({ moduleKey }: { moduleKey: ModuleKey }) {
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const navigation = useNavigation<any>();
  const openNav = useSideNav((s) => s.openNav);
  const mod = MODULES[moduleKey];

  // The hub is "current" only while it is the screen showing; pushing a list
  // over it should un-highlight, or the bar lies about where you are.
  const onHub = useNavigationState((state) => {
    const route = state?.routes?.[state.index ?? 0];
    return (route?.state?.index ?? 0) === 0;
  });

  const items: { key: string; label: string; icon: IconName; on: boolean; go: () => void }[] = [
    {
      key: "home",
      label: "Home",
      icon: "home-outline",
      on: false,
      go: () => navigation.navigate("App", { screen: "Home" }),
    },
    {
      key: "module",
      label: mod.title,
      icon: "view-grid-outline",
      on: onHub,
      go: () => navigation.navigate("Hub"),
    },
    {
      key: "menu",
      label: "Menu",
      icon: "menu",
      on: false,
      go: () => openNav(moduleKey),
    },
  ];

  return (
    <View style={[styles.bar, { paddingBottom: Math.max(insets.bottom, spacing.xs) }]}>
      {items.map((item) => (
        <Pressable
          key={item.key}
          style={styles.item}
          onPress={item.go}
          accessibilityRole="button"
          accessibilityState={{ selected: item.on }}
          accessibilityLabel={item.label}
        >
          <View style={[styles.iconWrap, item.on && { backgroundColor: withAlpha(mod.color, 0.16) }]}>
            <AppIcon name={item.icon} size={22} color={item.on ? mod.color : undefined} />
          </View>
          <Text style={[styles.label, item.on && { color: mod.color, fontWeight: "700" }]}>
            {item.label}
          </Text>
        </Pressable>
      ))}
    </View>
  );
}

const useStyles = makeStyles((colors) => ({
  bar: {
    flexDirection: "row",
    backgroundColor: colors.surface,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    paddingTop: spacing.xs,
  },
  item: { flex: 1, alignItems: "center", gap: 2 },
  iconWrap: {
    paddingHorizontal: spacing.md,
    paddingVertical: 2,
    borderRadius: 999,
  },
  label: { ...type.caption, color: colors.textMuted },
}));
