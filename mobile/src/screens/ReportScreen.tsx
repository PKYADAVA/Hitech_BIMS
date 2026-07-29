import { NativeStackScreenProps } from "@react-navigation/native-stack";
import { useQuery } from "@tanstack/react-query";
import React, { useLayoutEffect } from "react";
import { ScrollView, Text, View } from "react-native";

import { http } from "@/api/client";
import { Envelope } from "@/api/types";
import { Card, EmptyOrError, Loading, StatTile } from "@/components/ui";
import { ModuleStackParams } from "@/navigation/types";
import { makeStyles, spacing, type, useTheme } from "@/theme";
import { formatValue, humanizeKey, isEmpty } from "@/utils/format";

type Props = NativeStackScreenProps<ModuleStackParams, "Report">;

interface ReportData {
  generated?: string;
  totals?: Record<string, number>;
  rows?: Record<string, unknown>[];
}

/** Generic report renderer: totals as stat tiles + one card per row. */
export function ReportScreen({ route, navigation }: Props) {
  const { colors } = useTheme();
  const styles = useStyles();
  const { title, path } = route.params;

  useLayoutEffect(() => {
    navigation.setOptions({ title });
  }, [navigation, title]);

  const q = useQuery({
    queryKey: ["report", path],
    queryFn: async () => (await http.get<Envelope<ReportData>>(path)).data.data,
    staleTime: 60_000,
  });

  if (q.isLoading) return <Loading label="Building report…" />;
  if (q.isError) {
    return <EmptyOrError icon="⚠️" message={(q.error as Error)?.message ?? "Failed to load."} onRetry={q.refetch} />;
  }

  const data = q.data ?? {};
  const totals = Object.entries(data.totals ?? {});
  const rows = data.rows ?? [];

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      {data.generated ? <Text style={styles.generated}>As of {data.generated}</Text> : null}

      {totals.length > 0 ? (
        <View style={styles.totals}>
          {totals.map(([label, value]) => (
            <StatTile key={label} label={label} value={String(value)} accent={colors.tint} />
          ))}
        </View>
      ) : null}

      {rows.length === 0 ? (
        <EmptyOrError icon="📊" message="No data for this report." />
      ) : (
        rows.map((row, i) => {
          const entries = Object.entries(row).filter(([, v]) => !isEmpty(v));
          const [firstKey, firstVal] = entries[0] ?? ["", ""];
          return (
            <Card key={i} style={styles.row}>
              <Text style={styles.rowTitle}>{String(firstVal)}</Text>
              <View style={styles.pairs}>
                {entries.slice(1).map(([k, v]) => (
                  <View key={k} style={styles.pair}>
                    <Text style={styles.pairLabel}>{humanizeKey(k)}</Text>
                    <Text style={styles.pairValue}>{formatValue(k, v)}</Text>
                  </View>
                ))}
              </View>
            </Card>
          );
        })
      )}
    </ScrollView>
  );
}

const useStyles = makeStyles((colors) => ({
  screen: { flex: 1, backgroundColor: colors.bg },
  content: { padding: spacing.md, gap: spacing.md, paddingBottom: spacing.xxl },
  generated: { ...type.caption, color: colors.textMuted, textAlign: "right" },
  totals: { flexDirection: "row", gap: spacing.sm, flexWrap: "wrap" },
  row: { gap: spacing.sm },
  rowTitle: { ...type.h3, color: colors.text },
  pairs: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  pair: {
    minWidth: "30%",
    backgroundColor: colors.surfaceAlt,
    borderRadius: 10,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
  },
  pairLabel: { ...type.caption, color: colors.textMuted },
  pairValue: { ...type.title, color: colors.text },
}));
