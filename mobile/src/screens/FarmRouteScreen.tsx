/**
 * Map & Route — the supervisor's own round, on the phone.
 *
 * Deliberately not the planner. Planning happens at a desk, where there is a
 * filter bar and a keyboard; this is the driving half: where to go next, how
 * far it is, and the two buttons pressed at each farm. The web planner is what
 * lays a round out, and it reaches the phone through the in-app browser when
 * somebody actually wants to re-plan on the road.
 *
 * The map is the smaller half of the screen and the list is the larger, which
 * is the opposite of a consumer navigation app and the right way round here: a
 * supervisor knows the district, and what they need from this screen is the
 * order, the distances and a check-in button that works on one bar of signal.
 *
 * The map is Leaflet on OpenStreetMap tiles inside a WebView, not a native
 * map component. react-native-maps would have meant a Google Maps key — which
 * this company does not have — and without one it draws a blank grey rectangle
 * on Android, which is worse than no map at all. The WebView needs no key, adds
 * no native module (the in-app report browser already uses it) and draws the
 * same tiles the web planner does, so the two screens agree.
 *
 * The map is also the smaller half of the screen and the list the larger. That
 * is the opposite of a consumer navigation app and the right way round here: a
 * supervisor knows the district, and a check-in with no map is useful where a
 * map with no check-in is not.
 */
import * as Location from "expo-location";
import React, { useMemo, useState } from "react";
import { ActivityIndicator, Alert, Linking, Pressable, ScrollView, Text, View } from "react-native";
import { WebView } from "react-native-webview";

import { durationLabel, FarmRoute, RouteStop, useMyRoute, useRouteActions } from "@/api/farmRoute";
import { AppIcon } from "@/components/AppIcon";
import { Card, Screen } from "@/components/ui";
import { makeStyles, radius, spacing, type } from "@/theme";

/** The pins that have somewhere to be drawn. */
function drawable(stops: RouteStop[]) {
  return stops.filter(
    (s) => typeof s.latitude === "number" && typeof s.longitude === "number"
  );
}

/** A region that holds the whole round, with a little air around it. */
function regionFor(stops: RouteStop[]) {
  const points = drawable(stops);
  if (!points.length) return undefined;
  const lats = points.map((p) => p.latitude as number);
  const lngs = points.map((p) => p.longitude as number);
  const minLat = Math.min(...lats);
  const maxLat = Math.max(...lats);
  const minLng = Math.min(...lngs);
  const maxLng = Math.max(...lngs);
  return {
    latitude: (minLat + maxLat) / 2,
    longitude: (minLng + maxLng) / 2,
    // A floor on the span, or a round whose farms sit close together opens
    // zoomed so far in that the map is one grey field.
    latitudeDelta: Math.max((maxLat - minLat) * 1.5, 0.05),
    longitudeDelta: Math.max((maxLng - minLng) * 1.5, 0.05),
  };
}

async function currentFix() {
  /**
   * The phone's own position, for a check-in. Refused permission is not an
   * error worth blocking on: the visit still records, just without the proof
   * that somebody was there, and saying so is better than refusing the button.
   */
  try {
    const { status } = await Location.requestForegroundPermissionsAsync();
    if (status !== "granted") return null;
    const fix = await Location.getCurrentPositionAsync({
      accuracy: Location.Accuracy.Balanced,
    });
    return { latitude: fix.coords.latitude, longitude: fix.coords.longitude };
  } catch {
    return null;
  }
}


/**
 * The round drawn with Leaflet, as a self-contained page.
 *
 * Built here rather than fetched so the map appears without a round trip and
 * still draws on a bad signal once the tiles are cached. The tile layer is the
 * only thing that needs the network.
 */
function mapHtml(stops: RouteStop[]): string {
  const points = drawable(stops).map((s) => ({
    lat: s.latitude as number,
    lng: s.longitude as number,
    seq: s.sequence,
    label: s.label,
    farm: s.kind === "farm",
    done: s.state === "done",
    km: s.leg_distance_km,
  }));
  const data = JSON.stringify(points);
  return `<!doctype html><html><head>
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  html,body,#m{height:100%;margin:0}
  .p{border-radius:50%;border:2px solid #fff;color:#fff;font:600 11px sans-serif;
     display:flex;align-items:center;justify-content:center;
     box-shadow:0 0 0 1px rgba(0,0,0,.25)}
  .l{background:#fff;border:1px solid #cbd5e1;border-radius:4px;padding:0 4px;
     font:600 11px sans-serif;white-space:nowrap}
</style></head><body><div id="m"></div><script>
  var pts = ${data};
  var map = L.map('m', { zoomControl: false, attributionControl: false });
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19 }).addTo(map);
  var line = pts.map(function (p) { return [p.lat, p.lng]; });
  if (line.length > 1) L.polyline(line, { color: '#2563eb', weight: 4 }).addTo(map);
  pts.forEach(function (p) {
    var colour = !p.farm ? '#16a34a' : p.done ? '#16a34a' : '#2563eb';
    L.marker([p.lat, p.lng], { icon: L.divIcon({ className: '',
      html: '<div class="p" style="background:' + colour + ';width:20px;height:20px">' + p.seq + '</div>',
      iconSize: [20, 20], iconAnchor: [10, 10] }) }).addTo(map);
    L.marker([p.lat, p.lng], { icon: L.divIcon({ className: '',
      html: '<span class="l">' + p.label + '</span>', iconSize: [0, 0],
      iconAnchor: [-12, 7] }), interactive: false }).addTo(map);
  });
  if (line.length === 1) map.setView(line[0], 13);
  else if (line.length) map.fitBounds(L.latLngBounds(line), { padding: [24, 24] });
</script></body></html>`;
}

export function FarmRouteScreen() {
  const styles = useStyles();
  const { data, isLoading, refetch, isRefetching } = useMyRoute();
  const { startTrip, checkIn, checkOut } = useRouteActions();
  const [busyFarm, setBusyFarm] = useState<number | null>(null);

  const route: FarmRoute | null = data?.route ?? null;
  const stops = route?.stops ?? [];
  const region = useMemo(() => regionFor(stops), [stops]);
  const line = useMemo(
    () =>
      drawable(stops).map((s) => ({
        latitude: s.latitude as number,
        longitude: s.longitude as number,
      })),
    [stops]
  );

  const next = stops.find((s) => s.kind === "farm" && s.state !== "done");

  async function onCheck(stop: RouteStop, leaving: boolean) {
    if (!route || !stop.farm_id) return;
    setBusyFarm(stop.farm_id);
    const fix = await currentFix();
    const args = {
      routeId: route.id,
      farmId: stop.farm_id,
      latitude: fix?.latitude ?? null,
      longitude: fix?.longitude ?? null,
    };
    try {
      if (leaving) await checkOut.mutateAsync(args);
      else await checkIn.mutateAsync(args);
      if (!fix) {
        Alert.alert(
          "Recorded without a location",
          "The visit is saved, but the phone would not give a position, so there is no GPS stamp against it."
        );
      }
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { error?: string } } })?.response?.data?.error ??
        "That could not be recorded. Try again when there is signal.";
      Alert.alert("Not recorded", message);
    } finally {
      setBusyFarm(null);
    }
  }

  async function onStart() {
    if (!route) return;
    try {
      await startTrip.mutateAsync(route.id);
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { error?: string } } })?.response?.data?.error ??
        "The trip could not be started.";
      Alert.alert("Not started", message);
    }
  }

  function navigateTo(stop: RouteStop) {
    if (stop.latitude == null || stop.longitude == null) return;
    void Linking.openURL(
      `https://www.google.com/maps/dir/?api=1&destination=${stop.latitude},${stop.longitude}`
    );
  }

  if (isLoading) {
    return (
      <Screen>
        <View style={styles.centre}>
          <ActivityIndicator />
        </View>
      </Screen>
    );
  }

  if (!route) {
    return (
      <Screen>
        <Card>
          <Text style={styles.emptyTitle}>No round planned</Text>
          <Text style={styles.emptyBody}>
            {data?.message ??
              "Nothing has been planned for you today. A route is laid out in Map & Route Planner on the web and appears here once it is saved."}
          </Text>
          <Pressable style={styles.secondary} onPress={() => void refetch()}>
            <Text style={styles.secondaryText}>
              {isRefetching ? "Checking…" : "Check again"}
            </Text>
          </Pressable>
        </Card>
      </Screen>
    );
  }

  return (
    <Screen>
      <ScrollView contentContainerStyle={styles.body}>
        {/* Summary ------------------------------------------------------- */}
        <View style={styles.stats}>
          <Stat label="Farms" value={String(route.farm_count)} />
          <Stat label="Distance" value={`${route.distance_km.toFixed(1)} km`} />
          <Stat label="Est. time" value={durationLabel(route.minutes)} />
          <Stat
            label="Per stop"
            value={
              route.farm_count
                ? `${(route.distance_km / route.farm_count).toFixed(1)} km`
                : "—"
            }
          />
        </View>

        {route.estimated ? (
          <View style={styles.warn}>
            <Text style={styles.warnText}>
              These distances are estimates, not road distances — the routing
              service could not be reached when this round was planned.
            </Text>
          </View>
        ) : null}

        {/* Map ------------------------------------------------------------ */}
        <View style={styles.mapWrap}>
          {line.length ? (
            <WebView
              style={styles.map}
              originWhitelist={["*"]}
              source={{ html: mapHtml(stops) }}
              javaScriptEnabled
              scrollEnabled={false}
              // The map is a picture of the round, not a control surface: the
              // list below is what the supervisor actually works. Letting it
              // swallow drags would fight the page scroll on a phone.
              androidLayerType="hardware"
            />
          ) : (
            <View style={styles.centre}>
              <Text style={styles.emptyBody}>No farm on this round has a location.</Text>
            </View>
          )}
        </View>

        {/* Visit order ---------------------------------------------------- */}
        <Text style={styles.sectionTitle}>Visit Order (Best Sequence)</Text>
        {stops.map((stop) => {
          const isFarm = stop.kind === "farm";
          const busy = busyFarm === stop.farm_id;
          return (
            <Card key={stop.sequence} style={styles.stop}>
              <View style={styles.stopHead}>
                <View
                  style={[
                    styles.seq,
                    !isFarm && styles.seqEnd,
                    stop.state === "done" && styles.seqDone,
                  ]}
                >
                  <Text style={styles.seqText}>{stop.sequence}</Text>
                </View>
                <View style={styles.stopBody}>
                  <Text style={styles.stopName}>{stop.label}</Text>
                  <Text style={styles.stopMeta}>
                    {stop.leg_distance_km
                      ? `${stop.leg_distance_km.toFixed(1)} km · cum ${stop.cumulative_distance_km.toFixed(1)} km`
                      : "start"}
                  </Text>
                </View>
                {isFarm ? (
                  <Pressable style={styles.navBtn} onPress={() => navigateTo(stop)}>
                    <AppIcon name="navigation-variant" size={18} />
                  </Pressable>
                ) : null}
              </View>

              {isFarm && route.trip_id ? (
                <View style={styles.actions}>
                  {stop.state === "pending" ? (
                    <Pressable
                      style={styles.primary}
                      disabled={busy}
                      onPress={() => void onCheck(stop, false)}
                    >
                      <Text style={styles.primaryText}>
                        {busy ? "Checking in…" : "Check In"}
                      </Text>
                    </Pressable>
                  ) : null}
                  {stop.state === "here" ? (
                    <Pressable
                      style={styles.primary}
                      disabled={busy}
                      onPress={() => void onCheck(stop, true)}
                    >
                      <Text style={styles.primaryText}>
                        {busy ? "Checking out…" : "Check Out"}
                      </Text>
                    </Pressable>
                  ) : null}
                  {stop.state === "done" ? (
                    <Text style={styles.doneText}>Visited</Text>
                  ) : null}
                </View>
              ) : null}
            </Card>
          );
        })}
      </ScrollView>

      {/* The one action the whole screen exists for, always reachable. */}
      <View style={styles.footer}>
        <View>
          <Text style={styles.footerLabel}>
            {route.trip_id ? `Trip ${route.trip_no}` : "Not started"}
          </Text>
          <Text style={styles.footerValue}>
            {next ? `Next: ${next.label}` : "Every farm reached"}
          </Text>
        </View>
        {route.trip_id ? null : (
          <Pressable
            style={styles.start}
            disabled={startTrip.isPending}
            onPress={() => void onStart()}
          >
            <Text style={styles.startText}>
              {startTrip.isPending ? "Starting…" : "Start Trip"}
            </Text>
          </Pressable>
        )}
      </View>
    </Screen>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  const styles = useStyles();
  return (
    <View style={styles.stat}>
      <Text style={styles.statLabel}>{label}</Text>
      <Text style={styles.statValue}>{value}</Text>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  centre: { flex: 1, alignItems: "center", justifyContent: "center" },
  body: { padding: spacing.md, paddingBottom: spacing.xl * 3, gap: spacing.sm },
  stats: { flexDirection: "row", gap: spacing.xs },
  stat: {
    flex: 1,
    backgroundColor: c.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: c.border,
    padding: spacing.sm,
  },
  statLabel: { ...type.caption, color: c.textMuted },
  statValue: { ...type.title, color: c.text, fontWeight: "700" },
  warn: {
    backgroundColor: "#fef3c7",
    borderRadius: radius.md,
    padding: spacing.sm,
  },
  warnText: { ...type.caption, color: c.text },
  mapWrap: {
    height: 260,
    borderRadius: radius.md,
    overflow: "hidden",
    borderWidth: 1,
    borderColor: c.border,
  },
  map: { flex: 1 },
  sectionTitle: { ...type.title, color: c.text, marginTop: spacing.sm },
  stop: { gap: spacing.xs },
  stopHead: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  seq: {
    width: 26,
    height: 26,
    borderRadius: 13,
    backgroundColor: "#2563eb",
    alignItems: "center",
    justifyContent: "center",
  },
  seqEnd: { backgroundColor: "#16a34a" },
  seqDone: { backgroundColor: "#16a34a" },
  seqText: { color: "#fff", fontWeight: "700", fontSize: 12 },
  stopBody: { flex: 1 },
  stopName: { ...type.body, color: c.text, fontWeight: "600" },
  stopMeta: { ...type.caption, color: c.textMuted },
  navBtn: { padding: spacing.xs },
  actions: { flexDirection: "row", gap: spacing.sm, alignItems: "center" },
  primary: {
    backgroundColor: "#2563eb",
    borderRadius: radius.sm,
    paddingVertical: spacing.xs,
    paddingHorizontal: spacing.md,
  },
  primaryText: { color: "#fff", fontWeight: "700" },
  doneText: { ...type.caption, color: "#16a34a", fontWeight: "700" },
  secondary: {
    marginTop: spacing.sm,
    alignSelf: "flex-start",
    borderWidth: 1,
    borderColor: c.border,
    borderRadius: radius.sm,
    paddingVertical: spacing.xs,
    paddingHorizontal: spacing.md,
  },
  secondaryText: { color: c.text },
  emptyTitle: { ...type.title, color: c.text, marginBottom: spacing.xs },
  emptyBody: { ...type.body, color: c.textMuted },
  footer: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    padding: spacing.md,
    backgroundColor: c.surface,
    borderTopWidth: 1,
    borderTopColor: c.border,
  },
  footerLabel: { ...type.caption, color: c.textMuted },
  footerValue: { ...type.body, color: c.text, fontWeight: "600" },
  start: {
    backgroundColor: "#16a34a",
    borderRadius: radius.sm,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.lg,
  },
  startText: { color: "#fff", fontWeight: "800" },
}));
