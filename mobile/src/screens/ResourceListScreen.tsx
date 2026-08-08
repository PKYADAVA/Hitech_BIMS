import { NativeStackScreenProps } from "@react-navigation/native-stack";
import React, { useMemo, useState } from "react";
import { ActivityIndicator, Alert, FlatList, Pressable, Text, View } from "react-native";

import { http } from "@/api/client";
import { deleteResource } from "@/api/resources";
import { Row } from "@/api/types";
import { useOverview } from "@/api/stats";
import { LIST_KPIS } from "@/config/modulePrimary";
import { buildGroups, GroupItem } from "@/domain/grouping";
import { AppIcon } from "@/components/AppIcon";
import { RecordAction, RecordCard } from "@/components/RecordCard";
import { ListSkeleton } from "@/components/Skeleton";
import { EmptyOrError, SearchBar } from "@/components/ui";
import { FormControl } from "@/components/form";
import { RESOURCES } from "@/config/catalog";
import { extraRowActions } from "@/config/rowActions";
import { hasCreateForm, hasEditForm, openRecordForm } from "@/navigation/openForm";
import { ModuleStackParams } from "@/navigation/types";
import { queryClient } from "@/query/queryClient";
import { useResourceList } from "@/query/useResourceList";
import { usePermissionsStore } from "@/store/permissionsStore";
import { makeStyles, radius, shadow, spacing, type, useTheme } from "@/theme";
import { isEmpty } from "@/utils/format";
import { confirm, notify } from "@/ui/confirm";

type Props = NativeStackScreenProps<ModuleStackParams, "List">;

const isGroup = (item: Row | GroupItem): item is GroupItem =>
  Array.isArray((item as GroupItem).rows);

/** Read a dotted path out of the overview payload. */
const at = (obj: unknown, path: string): number | undefined =>
  path.split(".").reduce<any>((o, k) => (o == null ? o : o[k]), obj);

/**
 * The figures the reference puts above a list — today's purchase, this month's
 * — for the few lists that have any. A list with nothing worth stating shows
 * nothing rather than a count of its own rows.
 */
function ListKpiStrip({ resourceKey, accent }: { resourceKey: string; accent: string }) {
  const styles = useStyles();
  const cells = LIST_KPIS[resourceKey];
  const { data: ov } = useOverview();
  if (!cells?.length) return null;
  return (
    <View style={styles.kpiRow}>
      {cells.map((cell) => {
        const value = at(ov, cell.path);
        return (
          <View key={cell.label} style={[styles.kpiCell, { borderTopColor: accent }]}>
            <Text style={styles.kpiValue}>
              {value === undefined
                ? "–"
                : cell.money
                  ? `₹${value.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
                  : value.toLocaleString()}
            </Text>
            <Text style={styles.kpiLabel} numberOfLines={1}>{cell.label}</Text>
          </View>
        );
      })}
    </View>
  );
}

/** Generic, config-driven list screen: search + infinite scroll + modern cards. */
export function ResourceListScreen({ route, navigation }: Props) {
  const config = RESOURCES[route.params.resourceKey];
  const list = useResourceList<Row>(config.path);
  const [query, setQuery] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const can = usePermissionsStore((s) => s.canResource);
  const canAdd = can(config.key, config.module, "add");
  const canEdit = can(config.key, config.module, "edit");
  const canDelete = can(config.key, config.module, "delete");
  const { colors } = useTheme();
  const styles = useStyles();

  /**
   * The register's Actions column, as a row under each card.
   *
   * Same three the ERP registers offer, gated by the same permissions, so a
   * user who may only look sees only View. Reaching a record used to mean
   * knowing the card was tappable and that Edit and Delete lived one screen
   * further in; on the web they are right there on the row.
   */
  const actionsFor = (row: Row): RecordAction[] => {
    const actions: RecordAction[] = [{
      key: "view", label: "View", icon: "eye-outline",
      onPress: () => navigation.navigate("Detail", { resourceKey: config.key, row }),
    }];
    if (canEdit && hasEditForm(config.key)) {
      actions.push({
        key: "edit", label: "Edit", icon: "pencil-outline",
        onPress: () => openRecordForm(navigation, config.key, "edit", row),
      });
    }
    if (canDelete) {
      actions.push({
        key: "delete", label: "Delete", icon: "trash-can-outline", danger: true,
        onPress: () => confirmDelete(row),
      });
    }
    // Resource-specific actions (ending a trip, filling a capture) sit after
    // the standard three. Each gates itself: the ERP offers "+" to whoever may
    // add and the eraser to whoever may edit, and one shared check here made
    // both of them follow whichever right happened to be tested.
    actions.push(...extraRowActions(
      config.key, row,
      (screen, params) => (navigation.navigate as (s: string, p: unknown) => void)(
        screen, params),
      { add: canAdd, edit: canEdit, delete: canDelete },
      { clearLocation: confirmClearLocation }));
    return actions;
  };

  /**
   * Dropping a pin is destructive and off a small button, so it asks first.
   * The visit and its photographs stay — only the reading goes, which is what
   * the wording has to say or it reads like Delete.
   */
  const confirmClearLocation = async (row: Row) => {
    const label = config.card(row).title;
    if (!(await confirm({
      title: "Clear the location?",
      message: `${label} keeps its photos and documents. Only the GPS reading `
             + "is removed, so the farm can be pinned again on the next visit.",
      confirmLabel: "Clear Pin",
      destructive: true,
    }))) return;
    try {
      await http.post(`/broiler/location-captures/${row.id}/clear`);
      queryClient.invalidateQueries({ queryKey: ["resource", config.path] });
    } catch (e) {
      notify("Could not clear", (e as Error)?.message ?? "Please try again.");
    }
  };

  /** Deleting is destructive and off a small button, so it always asks first. */
  const confirmDelete = async (row: Row) => {
    const label = config.card(row).title;
    if (!(await confirm({
      title: `Delete ${config.singular}?`,
      message: `${label} will be removed. This cannot be undone.`,
      confirmLabel: "Delete",
      destructive: true,
    }))) return;
    try {
      await deleteResource(config.path, row.id as number);
      queryClient.invalidateQueries({ queryKey: ["resource", config.path] });
    } catch (e) {
      notify("Could not delete", (e as Error)?.message ?? "Please try again.");
    }
  };

  // Server feeds have no search_fields, so filter the loaded rows client-side.
  const data = useMemo(() => {
    const q = query.trim().toLowerCase();
    const field = config.dateField;
    return list.items.filter((row) => {
      if (q && !config.searchKeys.some((k) => {
        const v = row[k];
        return !isEmpty(v) && String(v).toLowerCase().includes(q);
      })) return false;
      if (!field || (!from && !to)) return true;
      // ISO dates compare correctly as strings, which is why the rows keep
      // them in that form rather than something friendlier.
      const on = String(row[field] ?? "").slice(0, 10);
      if (!on) return false;
      if (from && on < from) return false;
      if (to && on > to) return false;
      return true;
    });
  }, [list.items, query, from, to, config.searchKeys, config.dateField]);

  /**
   * Rows folded into their groups, newest group first and each group's own
   * days oldest-first — the order the web list uses, so a flock reads top to
   * bottom and the most recently worked flock is the one in reach.
   */
  const groups = useMemo(
    () => (config.group ? buildGroups(data, config.group) : null),
    [data, config.group]
  );

  // Collapsed by default: the point of grouping is not to face every day at once.
  const [openKeys, setOpenKeys] = useState<Set<string>>(new Set());
  const toggleGroup = (key: string) =>
    setOpenKeys((cur) => {
      const next = new Set(cur);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

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
        {/* A From/To range above the search, as the ERP reports have it: these
            registers are looked up by when, not by name. */}
        {config.dateField ? (
          <View style={styles.dateRange}>
            <View style={styles.dateCell}>
              <FormControl field={{ name: "from", label: "From", type: "date" }}
                           value={from} onChange={setFrom} />
            </View>
            <View style={styles.dateCell}>
              <FormControl field={{ name: "to", label: "To", type: "date" }}
                           value={to} onChange={setTo} />
            </View>
            {from || to ? (
              <Pressable style={styles.dateClear} hitSlop={8}
                         accessibilityLabel="Clear the date range"
                         onPress={() => { setFrom(""); setTo(""); }}>
                <AppIcon name="close-circle-outline" size={20} color={colors.textMuted} />
              </Pressable>
            ) : null}
          </View>
        ) : null}
        <SearchBar value={query} onChangeText={setQuery} placeholder={`Search ${config.title}`} />
      </View>
      <ListKpiStrip resourceKey={config.key} accent={config.accent} />
      <FlatList<Row | GroupItem>
        data={groups ?? data}
        keyExtractor={(item) =>
          isGroup(item) ? `g:${item.key}` : String(item.id)}
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
        renderItem={({ item }) => {
          if (!isGroup(item)) {
            return (
              <RecordCard
                view={config.card(item)}
                icon={config.icon}
                accent={config.accent}
                actions={actionsFor(item)}
                onPress={() =>
                  navigation.navigate("Detail", { resourceKey: config.key, row: item })
                }
              />
            );
          }
          const open = openKeys.has(item.key);
          return (
            <View>
              <Pressable
                style={[styles.groupHead, { borderLeftColor: config.accent }]}
                onPress={() => toggleGroup(item.key)}
                accessibilityRole="button"
                accessibilityState={{ expanded: open }}
                accessibilityLabel={`${item.title}, ${item.rows.length} entries`}
              >
                <View style={styles.groupText}>
                  <Text style={styles.groupTitle} numberOfLines={1}>{item.title}</Text>
                  {item.subtitle ? (
                    <Text style={styles.groupSubtitle} numberOfLines={1}>{item.subtitle}</Text>
                  ) : null}
                </View>
                <AppIcon
                  name={open ? "chevron-down" : "chevron-right"}
                  size={20}
                  color={colors.textFaint}
                />
              </Pressable>
              {open
                ? item.rows.map((row) => (
                    <View key={String(row.id)} style={styles.groupChild}>
                      <RecordCard
                        view={config.card(row)}
                        icon={config.icon}
                        accent={config.accent}
                        onPress={() =>
                          navigation.navigate("Detail", { resourceKey: config.key, row })
                        }
                      />
                    </View>
                  ))
                : null}
            </View>
          );
        }}
      />

      {hasCreateForm(config.key) && canAdd ? (
        <Pressable
          style={({ pressed }) => [
            styles.fab,
            { backgroundColor: config.accent },
            shadow(3),
            pressed && { opacity: 0.9, transform: [{ scale: 0.96 }] },
          ]}
          onPress={() => openRecordForm(navigation, config.key, "create")}
          accessibilityRole="button"
          accessibilityLabel={config.createLabel ?? `Add ${config.singular}`}
        >
          <AppIcon name="plus" size={22} color="#fff" />
          <Text style={styles.fabText}>{config.createLabel ?? "New"}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const useStyles = makeStyles((colors) => ({
  screen: { flex: 1, backgroundColor: colors.bg },
  dateRange: { flexDirection: "row", alignItems: "flex-end", gap: spacing.sm },
  dateCell: { flex: 1, minWidth: 0 },
  dateClear: { paddingBottom: spacing.md },
  searchWrap: { padding: spacing.md, paddingBottom: spacing.sm },
  fill: { flexGrow: 1 },
  content: { padding: spacing.md, paddingTop: spacing.xs, gap: spacing.sm, paddingBottom: 96 },
  kpiRow: { flexDirection: "row", gap: spacing.sm,
            paddingHorizontal: spacing.md, marginBottom: spacing.sm },
  kpiCell: {
    flex: 1,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    // A hairline of the list's own colour, matching the module hubs.
    borderTopWidth: 3,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.sm,
  },
  kpiValue: { ...type.h3, color: colors.text },
  kpiLabel: { ...type.caption, color: colors.textMuted, marginTop: 2 },
  groupHead: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderLeftWidth: 3,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.md,
  },
  groupText: { flex: 1 },
  groupTitle: { ...type.title, color: colors.text },
  groupSubtitle: { ...type.caption, color: colors.textMuted, marginTop: 2 },
  // Indented so an opened group reads as belonging to its heading.
  groupChild: { marginTop: spacing.sm, marginLeft: spacing.md },
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
