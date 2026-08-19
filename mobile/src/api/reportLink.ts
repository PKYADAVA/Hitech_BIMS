import { http } from "./client";
import { Envelope } from "./types";

/**
 * The in-app browser's login bridge.
 *
 * The app itself logs in with a JWT; the web reports run on Django session
 * cookies, a different system entirely. Rather than ask a second time inside
 * the embedded browser, this mints a short-lived, single-purpose link that
 * logs the same user into a normal session and lands them straight on the
 * report — see user.api.MobileReportLinkView / user.views.mobile_login_link.
 * Minted fresh on every open: it expires in ~60 seconds, so there is no
 * point caching it.
 */
export async function fetchReportWebLink(webReportName: string): Promise<string> {
  const resp = await http.get<Envelope<{ url: string }>>("/mobile-report-link", {
    params: { report: webReportName },
  });
  return resp.data.data.url;
}
