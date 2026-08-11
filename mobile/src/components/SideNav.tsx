/**
 * The dashboard's left sidebar, on a phone.
 *
 * Built as a slide-in panel rather than a drawer navigator: the drawer needs
 * `react-native-gesture-handler` and `reanimated`, which are native modules
 * and a version mismatch away from breaking the app in Expo Go. A Modal needs
 * nothing, works everywhere the app already runs, and this sidebar only has to
 * list modules and close.
 *
 * It reads the same module list the Home tiles do, filtered by the same
 * permission check, so a module hidden there cannot appear here.
 */
import { useNavigation } from "@react-navigation/native";
import React from "react";
import { Modal, Pressable, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { AppIcon, IconName } from "@/components/AppIcon";
import { useSyncSummary } from "@/offline/useSync";
import { colors, makeStyles, radius, spacing, type, withAlpha } from "@/theme";
import { useAuthStore } from "@/store/authStore";
import { usePermissionsStore } from "@/store/permissionsStore";
import { useSideNav } from "@/store/sideNavStore";

/** Route + look for one sidebar row. Mirrors HomeScreen's TILES. */
export interface NavItem {
  key: string;
  title: string;
  /** MaterialCommunityIcons name — see MODULE_ICON. */
  icon: string;
  color: string;
  target?: string;
}

/**
 * Titles are the ERP's own, from `user.access.MODULE_REGISTRY` — "Human
 * Resource", not "HR & Attendance" — so the two products name a module the
 * same way. Order and membership come from the server (`nav_order`), which
 * already applies the administrator's arrangement and drops what the user
 * cannot open, so this list is a lookup rather than the running order.
 */
export const NAV_ITEMS: NavItem[] = [
  { key: "dashboard", title: "Dashboard", icon: "view-dashboard-outline", color: colors.tint, target: "Home" },
  { key: "broiler", title: "Broiler", icon: "bird", color: colors.broiler, target: "Broiler" },
  { key: "hatchery", title: "Hatchery", icon: "egg", color: colors.hatchery, target: "Hatchery" },
  { key: "purchase", title: "Purchase", icon: "truck", color: colors.purchase, target: "PurchaseModule" },
  { key: "sales", title: "Sales", icon: "cart", color: colors.sales, target: "SalesModule" },
  { key: "account", title: "Account", icon: "book-open-variant", color: colors.account, target: "AccountModule" },
  { key: "inventory", title: "Inventory", icon: "package-variant-closed", color: colors.inventory, target: "Inventory" },
  { key: "hr", title: "Human Resource", icon: "account-tie", color: colors.hr, target: "HrModule" },
  { key: "user", title: "User", icon: "shield-account", color: colors.user, target: "UserModule" },
  { key: "sms", title: "SMS Management", icon: "message-text", color: colors.sms, target: "SmsModule" },
  { key: "change_requests", title: "Change Requests", icon: "file-document-edit",
    color: colors.change_requests, target: "ChangeRequestModule" },
  // Not a nav group of its own on the web — reports live inside each module
  // there — but the reference gives them one, and it is where someone looks
  // for "the mortality report" without first deciding which module owns it.
  { key: "reports", title: "Reports & Analytics", icon: "chart-bar",
    color: colors.tint, target: "ReportsModule" },
  // Not a module at all: what this phone has saved that the ERP has not seen.
  // It belongs in the sidebar rather than under a module because the records
  // waiting there can come from any of them, and because the moment it is
  // wanted is after a round filled out of range.
  { key: "offline", title: "Sync Center", icon: "cloud-sync-outline",
    color: colors.warning, target: "SyncCenter" },
];

export function SideNav() {
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const navigation = useNavigation<any>();
  const open = useSideNav((s) => s.open);
  const close = useSideNav((s) => s.close);
  const active = useSideNav((s) => s.active);
  const user = useAuthStore((s) => s.user);
  const canModule = usePermissionsStore((s) => s.canModule);
  const permsLoaded = usePermissionsStore((s) => s.loaded);
  const navOrder = usePermissionsStore((s) => s.navOrder);
  const outbox = useSyncSummary();

  // Dashboard always leads; the modules follow the server's order, which is
  // the administrator's if one is configured and the registry's otherwise.
  const items = React.useMemo(() => {
    const byKey = new Map(NAV_ITEMS.map((i) => [i.key, i]));
    const dashboard = byKey.get("dashboard")!;
    if (!navOrder.length) return NAV_ITEMS;
    const ordered = navOrder.map((k) => byKey.get(k)).filter(Boolean) as NavItem[];
    const reports = byKey.get("reports")!;
    return [dashboard, ...ordered, reports, byKey.get("offline")!];
  }, [navOrder]);

  const go = (item: NavItem) => {
    close();
    if (!item.target) return;
    // Navigate after the modal has gone, or the push animates behind it.
    setTimeout(() => navigation.navigate(item.target as never), 0);
  };

  const goProfile = () => {
    close();
    setTimeout(() => navigation.navigate("Profile" as never), 0);
  };

  return (
    <Modal visible={open} transparent animationType="fade" onRequestClose={close}>
      {/* Tapping the dimmed area closes, which is what a sidebar overlay does
          everywhere else and saves reaching for a close button. */}
      <Pressable style={styles.scrim} onPress={close} accessibilityLabel="Close menu">
        <Pressable style={[styles.panel, { paddingTop: insets.top + spacing.lg }]}>
          {/* Tapping your own name opens Profile. Profile is no longer a
              bottom tab — it was doing the same job as the avatar on Home —
              and the avatar is only on Home, so this is what keeps it
              reachable from inside a module, where the bottom bar is hidden. */}
          <Pressable
            style={styles.brand}
            onPress={goProfile}
            accessibilityRole="button"
            accessibilityLabel="Open profile"
          >
            <View style={styles.brandMark}>
              <AppIcon emoji="🐔" size={20} color="#fff" />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.brandName}>Hi Tech BIMS</Text>
              <Text style={styles.brandSub}>
                {user?.full_name || user?.username || "Poultry ERP"}
              </Text>
            </View>
            <AppIcon name="chevron-right" size={18} color={colors.textFaint} />
          </Pressable>

          <ScrollView showsVerticalScrollIndicator={false}>
            {items
              .filter((i) => ["dashboard", "reports", "offline"].includes(i.key)
                             || !permsLoaded || canModule(i.key))
              .map((item) => {
                const on = active === item.key;
                return (
                  <Pressable
                    key={item.key}
                    onPress={() => go(item)}
                    style={[styles.row, on && styles.rowOn]}
                    accessibilityRole="button"
                    accessibilityState={{ selected: on }}
                  >
                    <View style={[styles.rowIcon, { backgroundColor: withAlpha(item.color, on ? 0.24 : 0.14) }]}>
                      <AppIcon name={item.icon as IconName} size={18} color={item.color} />
                    </View>
                    <Text style={[styles.rowText, on && styles.rowTextOn]} numberOfLines={1}>
                      {item.title}
                    </Text>
                    {/* The count is the whole reason this row is here: a queue
                        nobody notices is a round nobody knows is unsent. */}
                    {item.key === "offline" && outbox.pending + outbox.failed + outbox.conflicts > 0 ? (
                      <View style={[styles.badge, (outbox.failed + outbox.conflicts) > 0 && styles.badgeBad]}>
                        <Text style={styles.badgeText}>
                          {outbox.pending + outbox.failed + outbox.conflicts}
                        </Text>
                      </View>
                    ) : null}
                  </Pressable>
                );
              })}
          </ScrollView>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

// The hamburger that used to open this is gone. The Menu tab in the bottom bar
// opens it now — one control, where a thumb already rests, instead of an icon
// in the top-left corner that a phone hand cannot comfortably reach.

const useStyles = makeStyles((c) => ({
  scrim: { flex: 1, backgroundColor: "rgba(15,23,42,0.45)", flexDirection: "row" },
  panel: {
    width: "78%",
    maxWidth: 320,
    backgroundColor: c.primary,
    paddingHorizontal: spacing.md,
    paddingBottom: spacing.lg,
  },
  brand: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingBottom: spacing.lg,
    marginBottom: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: "rgba(255,255,255,0.12)",
  },
  brandMark: {
    width: 38, height: 38, borderRadius: radius.md,
    alignItems: "center", justifyContent: "center",
    backgroundColor: "rgba(255,255,255,0.14)",
  },
  brandName: { ...type.title, color: "#fff" },
  brandSub: { ...type.caption, color: "rgba(255,255,255,0.72)" },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.sm,
    borderRadius: radius.md,
    marginBottom: 2,
  },
  rowOn: { backgroundColor: "rgba(255,255,255,0.14)" },
  rowIcon: {
    width: 34, height: 34, borderRadius: radius.sm,
    alignItems: "center", justifyContent: "center",
  },
  rowText: { ...type.body, color: "rgba(255,255,255,0.86)", flex: 1 },
  rowTextOn: { color: "#fff", fontWeight: "700" },
  badge: {
    minWidth: 22, paddingHorizontal: 6, paddingVertical: 2,
    borderRadius: 11, backgroundColor: c.warning, alignItems: "center",
  },
  badgeBad: { backgroundColor: c.danger },
  badgeText: { ...type.caption, color: "#fff", fontWeight: "800" },
}));
