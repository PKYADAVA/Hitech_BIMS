import { useQuery } from "@tanstack/react-query";

import { http } from "./client";
import { Envelope } from "./types";

/**
 * The sideload update check.
 *
 * This app has no store behind it — installing a new build is a manual
 * "download the APK, tap it" step, so nothing tells an already-installed
 * copy a newer one exists unless it asks. `/app-version` is deliberately
 * open (no auth required): the client that most needs to hear about an
 * update is the one furthest behind, and a breaking API change is exactly
 * the case where an old build might not even be able to log in to ask.
 */

export interface AppVersionInfo {
  latest_version: string | null;
  latest_version_code: number | null;
  download_url: string | null;
  force_update: boolean;
  notes: string;
}

export async function fetchAppVersion(): Promise<AppVersionInfo> {
  const resp = await http.get<Envelope<AppVersionInfo>>("/app-version");
  return resp.data.data;
}

export function useAppVersion() {
  return useQuery({
    queryKey: ["app-version"],
    queryFn: fetchAppVersion,
    // Always refetched, deliberately: this app persists its React Query
    // cache to disk across restarts (see App.tsx), so a long staleTime here
    // does not just skip a poll within one session — it can leave the app
    // showing a stale "no update" answer for its whole maxAge, across
    // restarts, exactly while a force_update release is waiting. A version
    // check is cheap and rare enough that there is no cost to asking fresh
    // every time the app is opened or returned to.
    staleTime: 0,
    refetchOnMount: "always",
    refetchOnWindowFocus: true,
    retry: false,
  });
}