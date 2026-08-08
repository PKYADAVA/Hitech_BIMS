import { useNavigation } from "@react-navigation/native";
import { useQuery } from "@tanstack/react-query";
import React from "react";
import { Pressable, Text, View } from "react-native";

import { unreadAlertCount } from "@/api/alerts";
import { AppIcon } from "@/components/AppIcon";
import { makeStyles, radius, type, useTheme } from "@/theme";

/**
 * The header's notification bell, matching the ERP's.
 *
 * Same endpoint as the web bell's badge (`unread_count`), so the number here
 * and the number in the office agree, and marking something read in either
 * place clears it in both.
 *
 * Polled rather than pushed: the web bell polls too, and a socket for a count
 * that changes a few times a day would be machinery for nothing. Push
 * notifications remain a separate concern — this is the in-app badge.
 */
export const UNREAD_ALERTS_KEY = ["alerts", "unread"] as const;

export function AlertBell({ tint }: { tint?: string }) {
  const navigation = useNavigation<any>();
  const styles = useStyles();
  const { colors } = useTheme();

  const { data: unread = 0 } = useQuery({
    queryKey: UNREAD_ALERTS_KEY,
    queryFn: unreadAlertCount,
    // Often enough to feel live, rarely enough to be invisible on mobile data.
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
    // A failed poll must never surface as an error screen — the badge simply
    // keeps its last value.
    retry: false,
    staleTime: 30_000,
  });

  return (
    <Pressable
      hitSlop={12}
      onPress={() => navigation.navigate("Notifications")}
      accessibilityRole="button"
      accessibilityLabel={
        unread ? `Alerts, ${unread} unread` : "Alerts"
      }
      style={styles.wrap}
    >
      <AppIcon name="bell-outline" size={22} color={tint ?? colors.onDark} />
      {unread > 0 ? (
        <View style={styles.badge}>
          {/* Past 99 the exact number stops meaning anything and starts
              breaking the pill's width. */}
          <Text style={styles.badgeText}>{unread > 99 ? "99+" : unread}</Text>
        </View>
      ) : null}
    </Pressable>
  );
}

const useStyles = makeStyles((colors) => ({
  wrap: { padding: 2 },
  badge: {
    position: "absolute",
    top: -4,
    right: -8,
    minWidth: 18,
    height: 18,
    paddingHorizontal: 4,
    borderRadius: radius.pill,
    backgroundColor: colors.danger,
    alignItems: "center",
    justifyContent: "center",
  },
  badgeText: { ...type.caption, fontSize: 10, color: "#fff", fontWeight: "700" },
}));
