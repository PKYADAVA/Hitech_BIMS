import { NativeStackScreenProps } from "@react-navigation/native-stack";
import { useQuery } from "@tanstack/react-query";
import * as ScreenOrientation from "expo-screen-orientation";
import React, { useEffect, useState } from "react";
import { Pressable, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { WebView } from "react-native-webview";

import { fetchReportWebLink } from "@/api/reportLink";
import { AppIcon } from "@/components/AppIcon";
import { EmptyOrError, Loading } from "@/components/ui";
import { ModuleStackParams } from "@/navigation/types";
import { makeStyles, spacing } from "@/theme";

type Props = NativeStackScreenProps<ModuleStackParams, "ReportWebView">;

/**
 * Shrinks text, the company letterhead, the filter bar and the table down to
 * something a phone screen can actually show more of at once — injected into
 * the page rather than changed in the Django templates themselves, since
 * every one of these reports is also the desktop ERP page and has no reason
 * to shrink there.
 *
 * Every report shares the same three structural classes underneath its own
 * page-specific ones — .rpt-head (letterhead), .rpt-filter (the search/filter
 * bar), .rpt-table (the data table, alongside e.g. .lfs-table) — so targeting
 * those three plus plain table/input/button tags covers all twelve reports
 * without listing any of them individually.
 *
 * The table itself does NOT get width:auto or a relaxed white-space here —
 * tried, and measured: a ~50-column report has nowhere near enough width to
 * fit even at 9px, and letting columns shrink to content collapses each
 * header down to one letter per line ("S / T / D") rather than something
 * smaller-but-readable. Every column at its natural width with one flat
 * horizontal scroll (the desktop behaviour, kept as-is) reads correctly at
 * any zoom; a same-width table that merely tries to be narrower does not.
 * Smaller font and tighter padding are what actually buys back space,
 * because they shrink the SAME layout instead of fighting it — more of the
 * unchanged table fits on screen before the scroll has to start.
 *
 * A plain <style> tag, not per-row inline styles, so it still reaches rows
 * these pages render in after load (most of them fetch and build their own
 * table body via JS) — CSS applies to elements as they appear, not just what
 * existed the moment this ran.
 */
const COMPACT_CSS = `
  body { font-size: 10px !important; }

  /* The module's own sub-nav bar — a hamburger that expands into the
     module's other pages (Master, Transactions, other reports…). This
     screen already has its own Close button, and browsing to a different
     ERP page from inside one focused report view isn't a thing the in-app
     browser needs to offer. */
  .module-subnav { display: none !important; }
  /* A handful of reports (Production P&L, Production Cost, Farmer & Farm,
     Supervisor Trip) render the full ERP top navbar ABOVE their own
     .module-subnav too — two stacked nav bars, not one. Selector matches
     nothing on the other reports, so this is safe unconditionally. */
  #mainNavbar { display: none !important; }

  .rpt-head { padding: 2px 6px !important; }
  .rpt-head .co-name { font-size: 9px !important; }
  .rpt-head .co-meta, .rpt-head .co-crit, .rpt-head .co-stamp { font-size: 8px !important; }
  .rpt-head .co-title { font-size: 11px !important; }

  .rpt-filter { padding: 2px 4px !important; }
  .rpt-filter .form-label { font-size: 8px !important; margin-bottom: 0 !important; }
  .card-body { padding: 3px !important; }

  table, .table, .rpt-table {
    font-size: 9px !important;
  }
  table th, table td, .rpt-table th, .rpt-table td {
    padding: 1px 4px !important;
  }

  .form-control, .form-select, input, select, textarea,
  .rpt-filter .form-control-sm, .rpt-filter .form-select-sm {
    font-size: 9px !important; padding: 1px 4px !important; height: auto !important;
  }
  .btn, .rpt-filter .btn-sm {
    font-size: 9px !important; padding: 1px 6px !important;
  }
  h1, h2, h3, h4, h5 { font-size: 85% !important; }
`;
const INJECT_COMPACT_CSS = `
  (function() {
    var s = document.createElement("style");
    s.innerHTML = ${JSON.stringify(COMPACT_CSS)};
    document.head.appendChild(s);
  })();
  true;
`;

/**
 * The full web report, inside the app rather than a tab switch away.
 *
 * ReportScreen's native card view covers what fits a phone screen; this is
 * for the report as the ERP actually renders it — every column, the filters,
 * CSV/print — for whoever needs that instead. Logging in is bridged, not
 * asked twice: see api/reportLink.ts.
 *
 * Full-screen, deliberately: the header and the module's bottom tab bar (see
 * ModuleTabBar) both hide themselves on this screen, since a wide desktop
 * table is already fighting for phone width and both cost it real height for
 * no reason a report needs — the floating Close button below is what a
 * header's back arrow would have been.
 *
 * The app is portrait-locked everywhere else, but these reports are wide
 * tables built for a desktop, not a phone held upright — so this one screen
 * switches to landscape (either way up) for the extra width, and switches
 * the rest of the app straight back the moment it's left.
 */
export function ReportWebViewScreen({ route, navigation }: Props) {
  const { webReportName } = route.params;
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const [webViewError, setWebViewError] = useState(false);

  useEffect(() => {
    ScreenOrientation.lockAsync(ScreenOrientation.OrientationLock.LANDSCAPE);
    return () => {
      ScreenOrientation.lockAsync(ScreenOrientation.OrientationLock.PORTRAIT_UP);
    };
  }, []);

  const q = useQuery({
    queryKey: ["report-web-link", webReportName],
    queryFn: () => fetchReportWebLink(webReportName),
    staleTime: 0,
    retry: false,
  });

  const closeButton = (
    <Pressable
      style={[styles.close, { top: insets.top + spacing.sm, left: insets.left + spacing.sm }]}
      onPress={() => navigation.goBack()}
      hitSlop={10}
      accessibilityRole="button"
      accessibilityLabel="Close report"
    >
      <AppIcon name="close" size={22} color="#fff" />
    </Pressable>
  );

  let body: React.ReactNode;
  if (q.isLoading) {
    body = <Loading label="Opening report…" />;
  } else if (q.isError || !q.data) {
    body = (
      <EmptyOrError
        icon="⚠️"
        message={(q.error as Error)?.message ?? "Could not open this report."}
        onRetry={q.refetch}
      />
    );
  } else if (webViewError) {
    body = (
      <EmptyOrError
        icon="⚠️"
        message="Could not load the report page. Check your connection and try again."
        onRetry={() => setWebViewError(false)}
      />
    );
  } else {
    body = (
      <WebView
        source={{ uri: q.data }}
        style={styles.web}
        startInLoadingState
        renderLoading={() => <Loading label="Loading…" />}
        onError={() => setWebViewError(true)}
        onHttpError={() => setWebViewError(true)}
        // The report page already ships a correct responsive viewport meta
        // tag (see templates/base.html) — Android's own legacy "scale the
        // whole page to fit" (the default) fights that instead of trusting
        // it, landing on a zoomed-out, blurry render. Off, the page sizes
        // itself the same way it would in a phone's own browser.
        scalesPageToFit={false}
        injectedJavaScript={INJECT_COMPACT_CSS}
      />
    );
  }

  return (
    <View style={styles.screen}>
      {body}
      {closeButton}
    </View>
  );
}

const useStyles = makeStyles((colors) => ({
  screen: { flex: 1, backgroundColor: colors.bg },
  web: { flex: 1 },
  close: {
    position: "absolute",
    width: 36, height: 36, borderRadius: 18,
    backgroundColor: "rgba(0,0,0,0.55)",
    alignItems: "center", justifyContent: "center",
  },
}));
