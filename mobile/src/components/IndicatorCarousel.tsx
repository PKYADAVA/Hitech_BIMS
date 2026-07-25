import React, { useState } from "react";
import {
  NativeScrollEvent,
  NativeSyntheticEvent,
  ScrollView,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from "react-native";

import { TrendPoint } from "@/api/stats";
import { Card, withAlpha } from "@/components/ui";
import { colors, radius, spacing, type } from "@/theme";

/** One headline number, optionally with a 7-point trend sparkline. */
export interface Indicator {
  key: string;
  label: string;
  value: string;
  caption?: string;
  icon: string;
  accent: string;
  trend?: TrendPoint[];
}

/** Bars-only mini chart — no axis text, sized to sit inside an indicator card. */
function Sparkline({ data, color, height = 40 }: { data: TrendPoint[]; color: string; height?: number }) {
  const max = Math.max(1, ...data.map((d) => d.value));
  return (
    <View style={[styles.spark, { height }]}>
      {data.map((d, i) => (
        <View key={`${d.label}-${i}`} style={styles.sparkCol}>
          <View
            style={[
              styles.sparkBar,
              { height: Math.max(3, (d.value / max) * height), backgroundColor: color },
            ]}
          />
          <Text style={styles.sparkLabel} numberOfLines={1}>
            {d.label.slice(0, 1)}
          </Text>
        </View>
      ))}
    </View>
  );
}

function IndicatorCard({ item, width }: { item: Indicator; width: number }) {
  return (
    <Card style={{ ...styles.card, width }}>
      <View style={styles.cardTop}>
        <View style={[styles.iconWrap, { backgroundColor: withAlpha(item.accent, 0.14) }]}>
          <Text style={styles.icon}>{item.icon}</Text>
        </View>
        <Text style={styles.label} numberOfLines={1}>
          {item.label}
        </Text>
      </View>
      <Text style={[styles.value, { color: item.accent }]} numberOfLines={1}>
        {item.value}
      </Text>
      {item.caption ? (
        <Text style={styles.caption} numberOfLines={1}>
          {item.caption}
        </Text>
      ) : null}
      {item.trend && item.trend.length > 0 ? (
        <Sparkline data={item.trend} color={item.accent} />
      ) : null}
    </Card>
  );
}

/**
 * Horizontally swipeable cross-module KPIs. Cards snap into place and a peek of
 * the next card hints there's more; a dot row tracks position.
 */
export function IndicatorCarousel({ indicators }: { indicators: Indicator[] }) {
  const { width } = useWindowDimensions();
  const cardW = Math.round(width * 0.72);
  const interval = cardW + spacing.sm;
  const [active, setActive] = useState(0);

  const onScroll = (e: NativeSyntheticEvent<NativeScrollEvent>) => {
    const idx = Math.round(e.nativeEvent.contentOffset.x / interval);
    if (idx !== active) setActive(Math.max(0, Math.min(indicators.length - 1, idx)));
  };

  return (
    <View>
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        decelerationRate="fast"
        snapToInterval={interval}
        snapToAlignment="start"
        onMomentumScrollEnd={onScroll}
        contentContainerStyle={styles.track}
      >
        {indicators.map((item) => (
          <IndicatorCard key={item.key} item={item} width={cardW} />
        ))}
      </ScrollView>
      <View style={styles.dots}>
        {indicators.map((item, i) => (
          <View
            key={item.key}
            style={[
              styles.dot,
              i === active && { backgroundColor: colors.primary, width: 16 },
            ]}
          />
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  track: { paddingHorizontal: spacing.md, gap: spacing.sm, paddingVertical: spacing.xs },
  card: { padding: spacing.lg, gap: spacing.xs, minHeight: 132 },
  cardTop: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  iconWrap: {
    width: 34,
    height: 34,
    borderRadius: radius.md,
    alignItems: "center",
    justifyContent: "center",
  },
  icon: { fontSize: 17 },
  label: { ...type.label, color: colors.textMuted, flex: 1 },
  value: { ...type.h1, marginTop: spacing.xs },
  caption: { ...type.caption, color: colors.textFaint },

  spark: { flexDirection: "row", alignItems: "flex-end", gap: 4, marginTop: spacing.sm },
  sparkCol: { flex: 1, alignItems: "center", justifyContent: "flex-end" },
  sparkBar: { width: "68%", minWidth: 6, borderRadius: 3 },
  sparkLabel: { ...type.caption, color: colors.textFaint, fontSize: 9, marginTop: 3 },

  dots: { flexDirection: "row", justifyContent: "center", gap: 6, marginTop: spacing.sm },
  dot: { width: 6, height: 6, borderRadius: 3, backgroundColor: colors.border },
});
