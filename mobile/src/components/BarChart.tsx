import React from "react";
import { StyleSheet, Text, View } from "react-native";

import { TrendPoint } from "@/api/stats";
import { colors, type } from "@/theme";

/**
 * Dependency-free bar chart: bars are flex-height Views, so it renders crisply
 * with no SVG/chart library. Good for small dashboard trends (≤ ~14 bars).
 */
export function BarChart({
  data,
  color = colors.primary,
  height = 96,
}: {
  data: TrendPoint[];
  color?: string;
  height?: number;
}) {
  const max = Math.max(1, ...data.map((d) => d.value));
  return (
    <View style={[styles.wrap, { height: height + 26 }]}>
      {data.map((d, i) => {
        const h = Math.max(3, (d.value / max) * height);
        return (
          <View key={`${d.label}-${i}`} style={styles.col}>
            <Text style={styles.value} numberOfLines={1}>
              {d.value}
            </Text>
            <View style={styles.track}>
              <View style={[styles.bar, { height: h, backgroundColor: color }]} />
            </View>
            <Text style={styles.label} numberOfLines={1}>
              {d.label}
            </Text>
          </View>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { flexDirection: "row", alignItems: "flex-end", gap: 6 },
  col: { flex: 1, alignItems: "center" },
  track: { justifyContent: "flex-end", flex: 1 },
  bar: { width: "70%", minWidth: 8, borderRadius: 5 },
  value: { ...type.caption, color: colors.textMuted, marginBottom: 2, fontSize: 10 },
  label: { ...type.caption, color: colors.textFaint, marginTop: 4, fontSize: 10 },
});
