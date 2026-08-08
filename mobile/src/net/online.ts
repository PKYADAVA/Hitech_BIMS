import NetInfo from "@react-native-community/netinfo";
import { Platform } from "react-native";
import { onlineManager } from "@tanstack/react-query";

/**
 * Whether the device can reach the network, and telling React Query about it.
 *
 * The cache is already persisted to disk (see App.tsx), so a register opened
 * yesterday is still on the phone. What was missing is anything that *knows*
 * the connection is gone: React Query assumed it was always online, so a
 * request on a farm with no signal spun and then failed rather than falling
 * back to what had been kept, and a mutation could never be paused for later.
 */

/**
 * Either signal saying "no" means no, and only "unknown" means yes.
 *
 * Neither alone is enough. `isConnected` misses the phone that joins the
 * shed's wifi and shows full bars with nothing behind it. `isInternetReachable`
 * is null until the first probe answers, and unknown is treated as online on
 * purpose — the request itself is a better test than a guess, and failing
 * closed would block the app for the seconds before the probe returns.
 */
const reachable = (state: {
  isConnected: boolean | null;
  isInternetReachable: boolean | null;
}): boolean => state.isConnected !== false && state.isInternetReachable !== false;

/**
 * NetInfo cannot carry this on web, so the window does.
 *
 * Its web build looks for `navigator.connection` and, finding it in Chrome,
 * subscribes to that alone — never to `window.online`/`offline`. Chrome's
 * NetworkInformation does not raise `change` when connectivity drops, so
 * pulling the network moved `navigator.onLine` and nothing else: the app went
 * on believing it was online. Listening to the window directly is what the
 * browser actually reports.
 */
function watchBrowser(setOnline: (online: boolean) => void): () => void {
  const update = (): void => setOnline(window.navigator.onLine);
  window.addEventListener("online", update, false);
  window.addEventListener("offline", update, false);
  update(); // Seed it; the events only mark changes from here on.
  return () => {
    window.removeEventListener("online", update);
    window.removeEventListener("offline", update);
  };
}

export function startOnlineWatch(): void {
  // React Query owns the subscription's lifetime — it tears the previous
  // listener down when a new one is set, so there is nothing to return here.
  onlineManager.setEventListener((setOnline) =>
    Platform.OS === "web"
      ? watchBrowser(setOnline)
      : NetInfo.addEventListener((state) => setOnline(reachable(state)))
  );
}
