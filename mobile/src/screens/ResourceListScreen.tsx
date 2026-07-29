import { NativeStackScreenProps } from "@react-navigation/native-stack";
import React, { useMemo, useState } from "react";
import { ActivityIndicator, FlatList, Pressable, Text, View } from "react-native";

import { Row } from "@/api/types";
import { AppIcon } from "@/components/AppIcon";
import { RecordCard } from "@/components/RecordCard";
import { ListSkeleton } from "@/components/Skeleton";
import { EmptyOrError, SearchBar } from "@/components/ui";
import { RESOURCES } from "@/config/catalog";
import { isEditable } from "@/config/forms";
import { openRecordForm } from "@/navigation/openForm";
import { ModuleStackParams } from "@/navigation/types";
import { useResourceList } from "@/query/useResourceList";
import { usePermissionsStore } from "@/store/permissionsStore";
import { makeStyles, shadow, spacing, type, useTheme } from "@/theme";
import { isEmpty } from "@/utils/format";

type Props = NativeStackScreenProps<ModuleStackParams, "List">;

/** Generic, config-driven list screen: search + infinite scroll + modern cards. */
export function ResourceListScreen({ route, navigation }: Props) {
  const config = RESOURCES[route.params.resourceKey];
  const list = useResourceList<Row>(config.path);
  const [query, setQuery] = useState("");
  const canAdd = usePermissionsStore((s) => s.canAction)(config.module, "add");
  const { colors } = useTheme();
  const styles = useStyles();

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

  if (list.isLoading) {
    return (
      <View style={styles.screen}>
        <View style={styles.searchWrap}>
          <SearchBar value={query} onChangeText={setQuery} placeholder={`Search ${config.title}`} />
        </View>
        <ListSkeleton />
      </View>
    );
  }
  if (list.isError) {
    const message = (list.error as Error)?.message ?? "Failed to load.";
    return (
      <EmptyOrError
        icon="⚠️"
        accent={colors.danger}
        title="Couldn't load"
        message={message}
        onRetry={list.refresh}
      />
    );
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
        keyboardDismissMode="on-drag"
        automaticallyAdjustKeyboardInsets
        ListEmptyComponent={
          query ? (
            <EmptyOrError icon="🔍" title="No matches" message="No results for your search." />
          ) : (
            <EmptyOrError
              icon={config.icon}
              accent={config.accent}
              title={`No ${config.title.toLowerCase()} yet`}
              message={config.emptyMessage}
            />
          )
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

      {isEditable(config.key) && canAdd ? (
        <Pressable
          style={({ pressed }) => [
            styles.fab,
            { backgroundColor: config.accent },
            shadow(3),
            pressed && { opacity: 0.9, transform: [{ scale: 0.96 }] },
          ]}
          onPress={() => openRecordForm(navigation, config.key, "create")}
          accessibilityRole="button"
          accessibilityLabel={`Add ${config.singular}`}
        >
          <AppIcon name="plus" size={22} color="#fff" />
          <Text style={styles.fabText}>New</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const useStyles = makeStyles((colors) => ({
  screen: { flex: 1, backgroundColor: colors.bg },
  searchWrap: { padding: spacing.md, paddingBottom: spacing.sm },
  fill: { flexGrow: 1 },
  content: { padding: spacing.md, paddingTop: spacing.xs, gap: spacing.sm, paddingBottom: 96 },
  fab: {
    position: "absolute",
    right: spacing.lg,
    bottom: spacing.xl,
    height: 52,
    paddingHorizontal: spacing.lg,
    borderRadius: 26,
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
  },
  fabPlus: { color: "#fff", fontSize: 22, fontWeight: "700", marginTop: -2 },
  fabText: { color: "#fff", ...type.title, fontWeight: "800" },
}));
