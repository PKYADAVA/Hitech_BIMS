import { NativeStackScreenProps } from "@react-navigation/native-stack";
import React, { useMemo, useState } from "react";
import { ActivityIndicator, FlatList, StyleSheet, View } from "react-native";

import { Row } from "@/api/types";
import { RecordCard } from "@/components/RecordCard";
import { EmptyOrError, Loading, SearchBar } from "@/components/ui";
import { RESOURCES } from "@/config/catalog";
import { ModuleStackParams } from "@/navigation/types";
import { useResourceList } from "@/query/useResourceList";
import { colors, spacing } from "@/theme";
import { isEmpty } from "@/utils/format";

type Props = NativeStackScreenProps<ModuleStackParams, "List">;

/** Generic, config-driven list screen: search + infinite scroll + modern cards. */
export function ResourceListScreen({ route, navigation }: Props) {
  const config = RESOURCES[route.params.resourceKey];
  const list = useResourceList<Row>(config.path);
  const [query, setQuery] = useState("");

  // Server feeds have no search_fields, so filter the loaded rows client-side.
  const data = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return list.items;
    return list.items.filter((row) =>
      config.searchKeys.some((k) => {
        const v = row[k];
        return !isEmpty(v) && String(v).toLowerCase().includes(q);
      })
    );
  }, [list.items, query, config.searchKeys]);

  if (list.isLoading) return <Loading label={`Loading ${config.title.toLowerCase()}…`} />;
  if (list.isError) {
    const message = (list.error as Error)?.message ?? "Failed to load.";
    return <EmptyOrError icon="⚠️" message={message} onRetry={list.refresh} />;
  }

  return (
    <View style={styles.screen}>
      <View style={styles.searchWrap}>
        <SearchBar value={query} onChangeText={setQuery} placeholder={`Search ${config.title}`} />
      </View>
      <FlatList
        data={data}
        keyExtractor={(row) => String(row.id)}
        contentContainerStyle={data.length === 0 ? styles.fill : styles.content}
        onRefresh={list.refresh}
        refreshing={list.isRefreshing}
        onEndReachedThreshold={0.4}
        onEndReached={list.loadMore}
        keyboardShouldPersistTaps="handled"
        ListEmptyComponent={
          <EmptyOrError
            icon={config.icon}
            message={query ? "No matches for your search." : config.emptyMessage}
          />
        }
        ListFooterComponent={
          list.isFetchingNextPage ? (
            <ActivityIndicator style={{ margin: spacing.lg }} color={config.accent} />
          ) : null
        }
        renderItem={({ item }) => (
          <RecordCard
            view={config.card(item)}
            icon={config.icon}
            accent={config.accent}
            onPress={() =>
              navigation.navigate("Detail", { resourceKey: config.key, row: item })
            }
          />
        )}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.bg },
  searchWrap: { padding: spacing.md, paddingBottom: spacing.sm },
  fill: { flexGrow: 1 },
  content: { padding: spacing.md, paddingTop: spacing.xs, gap: spacing.sm },
});
