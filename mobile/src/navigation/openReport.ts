import { ReportLink } from "@/config/catalog";

/**
 * Where opening a report actually goes.
 *
 * Straight to the full web page in the in-app browser whenever one exists
 * (`webReportName` set) — that's the actual report, filters and all, not a
 * summary of it. The native card screen (ReportScreen) was the tile's
 * landing page before this, with "View Full Report" one more tap away; that
 * extra stop is gone now, kept only for the reports with no web page at all
 * (Mortality Trend), where the native screen is the only report there is.
 */
export function openReport(
  navigate: (screen: string, params: unknown) => void,
  rep: ReportLink,
): void {
  if (rep.webReportName) {
    navigate("ReportWebView", { title: rep.title, webReportName: rep.webReportName });
  } else if (rep.path) {
    navigate("Report", { title: rep.title, path: rep.path });
  }
}
