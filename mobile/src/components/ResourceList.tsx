import React from "react";
import { ActivityIndicator, FlatList, StyleSheet, Text, View } from "react-native";

import { Row } from "@/api/types";
import { useResourceList } from "@/query/useResourceList";
import { colors, radius, spacing } from "@/theme";
import { EmptyOrError, Loading } from "./ui";

/**
 * Reusable list view: infinite scroll + pull-to-refresh over any resource.
 * A screen supplies the endpoint path and how to render one row — nothing else.
 * This is why the daily-entries and egg-purchases screens are ~10 lines each.
 */
export function ResourceList<T extends Row = Row>({
  path,
  params,
  renderTitle,
  renderSubtitle,
  emptyMessage = "Nothing here yet.",
}: {
  path: string;
  params?: Record<string, string | number | undefined>;
  renderTitle: (row: T) => string;
  renderSubtitle?: (row: T) => string;
  emptyMessage?: string;
}) {
  const list = useResourceList<T>(path, params);

  if (list.isLoading) return <Loading label="Loading…" />;
  if (list.isError) {
    const message = (list.error as Error)?.message ?? "Failed to load.";
    return <EmptyOrError message={message} onRetry={list.refresh} />;
  }

  return (
    <FlatList
      data={list.items}
      keyExtractor={(row) => String(row.id)}
      contentContainerStyle={list.items.length === 0 ? styles.fill : styles.content}
      onRefresh={list.refresh}
      refreshing={list.isRefreshing}
      onEndReachedThreshold={0.4}
      onEndReached={list.loadMore}
      ListEmptyComponent={<EmptyOrError message={emptyMessage} />}
      ListFooterComponent={
        list.isFetchingNextPage ? (
          <ActivityIndicator style={{ margin: spacing.lg }} color={colors.primary} />
        ) : null
      }
      renderItem={({ item }) => (
        <View style={styles.card}>
          <Text style={styles.title}>{renderTitle(item)}</Text>
          {renderSubtitle ? <Text style={styles.subtitle}>{renderSubtitle(item)}</Text> : null}
        </View>
      )}
    />
  );
}

const styles = StyleSheet.create({
  fill: { flexGrow: 1 },
  content: { padding: spacing.md, gap: spacing.sm },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    padding: spacing.lg,
    borderWidth: 1,
    borderColor: colors.border,
  },
  title: { fontSize: 15, fontWeight: "600", color: colors.text },
  subtitle: { fontSize: 13, color: colors.textMuted, marginTop: 2 },
});
