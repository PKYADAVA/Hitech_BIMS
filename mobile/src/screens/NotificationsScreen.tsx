import { NativeStackScreenProps } from "@react-navigation/native-stack";
import { useInfiniteQuery, useMutation } from "@tanstack/react-query";
import React, { useLayoutEffect, useState } from "react";
import { FlatList, Linking, Pressable, RefreshControl, Text, View } from "react-native";

import {
  AlertNotification, dismissAlert, listAlerts, markAlertRead, markAllAlertsRead,
} from "@/api/alerts";
import { AppIcon, IconName } from "@/components/AppIcon";
import { UNREAD_ALERTS_KEY } from "@/components/AlertBell";
import { EmptyOrError, Loading } from "@/components/ui";
import { queryClient } from "@/query/queryClient";
import { makeStyles, radius, shadow, spacing, type, useTheme } from "@/theme";
import { formatDateTime } from "@/utils/format";

// Registered on the Root stack, not a module stack: the bell is tapped from
// Home (a tab) as well as from every module header.
type Props = { navigation: NativeStackScreenProps<Record<string, undefined>, string>["navigation"] };

/**
 * Alerts & Notifications — the phone's version of the ERP's bell dropdown and
 * its notification centre, which on a phone are one screen rather than two.
 *
 * Reads the same alerthub feed as the web, so the list, the scope and the read
 * state are shared: clearing something here clears it in the office.
 *
 * There is no delete, deliberately, and for the same reason the API has none —
 * a notification is the record that someone was told something, and any later
 * argument about who knew what depends on it surviving. Read is as far as it
 * goes.
 */

/** The alert's own tone, mapped to this app's palette. */
const TONE_COLOR: Record<string, "danger" | "warning" | "info" | "success"> = {
  danger: "danger",
  critical: "danger",
  high: "danger",
  warning: "warning",
  medium: "warning",
  info: "info",
  low: "info",
  success: "success",
};

/** MaterialCommunityIcons stand-ins for the web's Font Awesome glyphs. */
const TONE_ICON: Record<string, IconName> = {
  danger: "alert-octagon-outline",
  warning: "alert-outline",
  info: "information-outline",
  success: "check-circle-outline",
};

export function NotificationsScreen({ navigation }: Props) {
  const styles = useStyles();
  const { colors } = useTheme();
  const [unreadOnly, setUnreadOnly] = useState(false);

  const query = useInfiniteQuery({
    queryKey: ["alerts", "list", unreadOnly],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) => listAlerts({ unreadOnly, url: pageParam }),
    getNextPageParam: (last) => last.next ?? undefined,
  });

  const items: AlertNotification[] = query.data?.pages.flatMap((p) => p.items) ?? [];

  /** Both mutations refresh the badge from the server's own count. */
  const refreshBadge = (unread: number) =>
    queryClient.setQueryData(UNREAD_ALERTS_KEY, unread);

  const readOne = useMutation({
    mutationFn: markAlertRead,
    onSuccess: (unread) => {
      refreshBadge(unread);
      queryClient.invalidateQueries({ queryKey: ["alerts", "list"] });
    },
  });

  // Clear takes it off this user's list whether it was read or not — "I am
  // done with it" is a different answer from "I have seen it".
  const clearOne = useMutation({
    mutationFn: dismissAlert,
    onSuccess: (unread) => {
      refreshBadge(unread);
      queryClient.invalidateQueries({ queryKey: ["alerts", "list"] });
    },
  });

  const readAll = useMutation({
    mutationFn: markAllAlertsRead,
    onSuccess: (unread) => {
      refreshBadge(unread);
      queryClient.invalidateQueries({ queryKey: ["alerts", "list"] });
    },
  });

  useLayoutEffect(() => {
    navigation.setOptions({
      title: "Alerts & Notifications",
      headerRight: () => (
        <Pressable
          hitSlop={12}
          onPress={() => readAll.mutate()}
          disabled={readAll.isPending}
          accessibilityRole="button"
        >
          <Text style={styles.markAll}>
            {readAll.isPending ? "Marking…" : "Mark all read"}
          </Text>
        </Pressable>
      ),
    });
  }, [navigation, styles, readAll]);

  if (query.isLoading) return <Loading label="Loading alerts…" />;
  if (query.isError) {
    return (
      <EmptyOrError
        icon="⚠️"
        title="Couldn't load alerts"
        message="Check your connection and try again."
        onRetry={() => query.refetch()}
      />
    );
  }

  return (
    <View style={styles.screen}>
      {/* The web centre filters on a dozen fields; a phone earns the one that
          is actually reached for — everything, or only what is still unread. */}
      <View style={styles.filterRow}>
        {[
          { label: "All", value: false },
          { label: "Unread", value: true },
        ].map((opt) => (
          <Pressable
            key={opt.label}
            onPress={() => setUnreadOnly(opt.value)}
            style={[styles.chip, unreadOnly === opt.value && styles.chipOn]}
          >
            <Text style={[styles.chipText, unreadOnly === opt.value && styles.chipTextOn]}>
              {opt.label}
            </Text>
          </Pressable>
        ))}
      </View>

      <FlatList
        data={items}
        keyExtractor={(n) => String(n.id)}
        contentContainerStyle={styles.list}
        refreshControl={
          <RefreshControl
            refreshing={query.isRefetching && !query.isFetchingNextPage}
            onRefresh={() => query.refetch()}
            tintColor={colors.tint}
          />
        }
        onEndReachedThreshold={0.4}
        onEndReached={() => {
          if (query.hasNextPage && !query.isFetchingNextPage) query.fetchNextPage();
        }}
        ListEmptyComponent={
          <EmptyOrError
            icon="🔔"
            title={unreadOnly ? "Nothing unread" : "No alerts yet"}
            message={
              unreadOnly
                ? "Everything here has been read."
                : "Alerts about your farms and stock will appear here."
            }
          />
        }
        renderItem={({ item }) => (
          <AlertRow
            alert={item}
            onClear={() => clearOne.mutate(item.id)}
            onPress={() => {
              if (!item.is_read) readOne.mutate(item.id);
            }}
          />
        )}
      />
    </View>
  );
}

function AlertRow({
  alert,
  onPress,
  onClear,
}: {
  alert: AlertNotification;
  onPress: () => void;
  onClear: () => void;
}) {
  const styles = useStyles();
  const { colors } = useTheme();
  const tone = TONE_COLOR[alert.tone] ?? TONE_COLOR[alert.priority] ?? "info";
  const accent = colors[tone];

  return (
    <Pressable onPress={onPress} style={[styles.card, !alert.is_read && styles.cardUnread]}>
      {/* An unread alert carries a coloured spine; read ones keep the icon but
          lose the emphasis, so a full list still scans. */}
      <View style={[styles.spine, { backgroundColor: alert.is_read ? colors.border : accent }]} />
      <View style={[styles.icon, { backgroundColor: colors[`${tone}Light`] }]}>
        <AppIcon name={TONE_ICON[tone] ?? "bell-outline"} size={18} color={accent} />
      </View>

      <View style={styles.body}>
        <View style={styles.headRow}>
          <Text style={[styles.title, !alert.is_read && styles.titleUnread]} numberOfLines={2}>
            {alert.title}
          </Text>
          {alert.is_read ? null : <View style={[styles.dot, { backgroundColor: accent }]} />}
        </View>

        <Text style={styles.message} numberOfLines={3}>
          {alert.message}
        </Text>

        {alert.attachment_url ? (
          <Pressable
            onPress={() => Linking.openURL(alert.attachment_url).catch(() => {})}
            hitSlop={6}
            accessibilityRole="link"
            style={styles.attachRow}
          >
            <AppIcon name="paperclip" size={13} color={colors.tint} />
            <Text style={styles.attachText} numberOfLines={1}>
              {alert.attachment_name || "Attachment"}
            </Text>
          </Pressable>
        ) : null}

        <View style={styles.metaRow}>
          <Text style={[styles.pill, { backgroundColor: colors[`${tone}Light`], color: accent }]}>
            {alert.category_label || alert.priority_label || alert.module_label}
          </Text>
          {alert.place ? <Text style={styles.meta} numberOfLines={1}>{alert.place}</Text> : null}
          <Text style={styles.metaWhen}>{formatDateTime(alert.created_at)}</Text>
        </View>

        {/* Clear removes it from this list. Offered on read rows too: having
            seen something is not the same as being finished with it, and a
            read alert with no way to clear it just accumulates. The record
            itself is never deleted. */}
        {(
          <Pressable
            onPress={onClear}
            hitSlop={8}
            accessibilityRole="button"
            accessibilityLabel="Clear this alert"
            style={styles.clearBtn}
          >
            <AppIcon name="close" size={13} color={colors.textMuted} />
            <Text style={styles.clearText}>Clear</Text>
          </Pressable>
        )}
      </View>
    </Pressable>
  );
}

const useStyles = makeStyles((colors) => ({
  screen: { flex: 1, backgroundColor: colors.bg },
  markAll: { ...type.label, color: colors.onDark },

  filterRow: {
    flexDirection: "row",
    gap: spacing.sm,
    paddingHorizontal: spacing.md,
    paddingTop: spacing.md,
  },
  chip: {
    paddingHorizontal: spacing.md,
    paddingVertical: 6,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  chipOn: { backgroundColor: colors.primary, borderColor: colors.primary },
  chipText: { ...type.label, color: colors.textMuted },
  chipTextOn: { color: colors.onDark },

  list: { padding: spacing.md, gap: spacing.md, flexGrow: 1 },

  card: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.md,
    paddingLeft: spacing.md + 6,
    overflow: "hidden",
    ...shadow(1),
  },
  cardUnread: { backgroundColor: colors.surface },
  spine: { position: "absolute", left: 0, top: 0, bottom: 0, width: 4 },

  icon: {
    width: 36, height: 36, borderRadius: radius.md,
    alignItems: "center", justifyContent: "center",
  },
  body: { flex: 1, gap: 4 },
  headRow: { flexDirection: "row", alignItems: "flex-start", gap: spacing.sm },
  title: { ...type.title, color: colors.text, flex: 1 },
  titleUnread: { fontWeight: "800" },
  dot: { width: 8, height: 8, borderRadius: 4, marginTop: 6 },
  message: { ...type.caption, color: colors.textMuted, lineHeight: 17 },

  // A file the sender attached. Opened in the phone's own viewer rather than
  // downloaded here — the app has no document store to put it in.
  attachRow: { flexDirection: "row", alignItems: "center", gap: 5, marginTop: 3 },
  attachText: { ...type.caption, color: colors.tint, flexShrink: 1, textDecorationLine: "underline" },

  metaRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginTop: 2, flexWrap: "wrap" },
  pill: {
    ...type.caption,
    fontSize: 10,
    overflow: "hidden",
    borderRadius: radius.pill,
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
  },
  meta: { ...type.caption, color: colors.textFaint, flexShrink: 1 },
  metaWhen: { ...type.caption, color: colors.textFaint, marginLeft: "auto" },

  clearBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    alignSelf: "flex-start",
    marginTop: spacing.xs,
    paddingHorizontal: spacing.sm,
    paddingVertical: 3,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.border,
  },
  clearText: { ...type.caption, fontSize: 11, color: colors.textMuted },
}));
