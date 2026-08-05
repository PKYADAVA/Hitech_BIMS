/**
 * A module's own bottom bar, as the reference gives each module screen.
 *
 * Rendered once beneath a module's stack rather than per screen, so it stays
 * put while the stack pushes lists and forms over it — and so adding a screen
 * to a module does not mean remembering to add the bar to it.
 *
 * Five where a module has five: Home, the module's hub, its own shortcut (the
 * list its people open most), Reports, and Menu for the sidebar. A module with
 * no obvious shortcut keeps a four-button bar rather than carrying one chosen
 * to fill the space, and the shortcut is hidden from anyone who may not view
 * that list.
 */
import { useNavigation, useNavigationState } from "@react-navigation/native";
import React from "react";
import { Pressable, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { AppIcon, IconName } from "@/components/AppIcon";
import { RESOURCE_TABS } from "@/api/permissions";
import { MODULES, ModuleKey } from "@/config/catalog";
import { MODULE_SHORTCUT } from "@/config/modulePrimary";
import { usePermissionsStore } from "@/store/permissionsStore";
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

  const shortcut = MODULE_SHORTCUT[moduleKey];
  const canTab = usePermissionsStore((s) => s.canTab);
  // Same rule the hub tiles use: no tab mapping means the module gate is the
  // only gate, otherwise the screen needs its own tab.
  const shortcutTab = shortcut ? RESOURCE_TABS[shortcut.resourceKey] : undefined;
  const showShortcut = !!shortcut && (!shortcutTab || canTab(shortcutTab));

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
    ...(showShortcut
      ? [{
          key: "shortcut",
          label: shortcut!.label,
          icon: shortcut!.icon as IconName,
          on: false,
          go: () => navigation.navigate("List", { resourceKey: shortcut!.resourceKey }),
        }]
      : []),
    {
      key: "reports",
      label: "Reports",
      icon: "chart-bar",
      on: false,
      go: () => navigation.navigate("ReportsModule"),
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
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    borderRadius: 999,
  },
  label: { ...type.caption, color: colors.textMuted, fontSize: 10 },
}));
