import React, { useEffect, useRef } from "react";
import { Animated, DimensionValue, Easing, View, ViewStyle } from "react-native";

import { makeStyles, radius, shadow, spacing, useTheme } from "@/theme";

/**
 * Content placeholders shown while data loads — a calmer, more premium wait
 * than a bare spinner. Pure RN `Animated` (no extra deps): one shared pulse
 * drives every block so a whole screen breathes in sync.
 */
function usePulse() {
  const v = useRef(new Animated.Value(0.4)).current;
  useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(v, { toValue: 1, duration: 750, easing: Easing.inOut(Easing.ease), useNativeDriver: true }),
        Animated.timing(v, { toValue: 0.4, duration: 750, easing: Easing.inOut(Easing.ease), useNativeDriver: true }),
      ])
    );
    loop.start();
    return () => loop.stop();
  }, [v]);
  return v;
}

/** A single shimmering block. Pass a shared `opacity` to sync many together. */
export function Skeleton({
  width = "100%",
  height = 12,
  radius: r = radius.sm,
  opacity,
  style,
}: {
  width?: DimensionValue;
  height?: number;
  radius?: number;
  opacity?: Animated.Value;
  style?: ViewStyle;
}) {
  const { colors } = useTheme();
  const own = usePulse();
  return (
    <Animated.View
      style={[
        { width, height, borderRadius: r, backgroundColor: colors.surfaceAlt, opacity: opacity ?? own },
        style,
      ]}
    />
  );
}

/** A card-shaped placeholder mirroring a RecordCard (icon + two text lines). */
function SkeletonCard({ opacity }: { opacity: Animated.Value }) {
  const styles = useStyles();
  return (
    <View style={styles.card}>
      <Skeleton width={44} height={44} radius={radius.md} opacity={opacity} />
      <View style={styles.lines}>
        <Skeleton width="62%" height={13} opacity={opacity} />
        <Skeleton width="40%" height={11} opacity={opacity} />
      </View>
      <Skeleton width={36} height={20} radius={radius.sm} opacity={opacity} />
    </View>
  );
}

/** A full list of card placeholders — drop-in for a list screen's loading state. */
export function ListSkeleton({ count = 7 }: { count?: number }) {
  const styles = useStyles();
  const opacity = usePulse();
  return (
    <View style={styles.list}>
      {Array.from({ length: count }).map((_, i) => (
        <SkeletonCard key={i} opacity={opacity} />
      ))}
    </View>
  );
}

const useStyles = makeStyles((colors) => ({
  list: { padding: spacing.md, gap: spacing.sm },
  card: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    ...shadow(1),
  },
  lines: { flex: 1, gap: 8 },
}));
