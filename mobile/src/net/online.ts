import NetInfo from "@react-native-community/netinfo";
import { onlineManager } from "@tanstack/react-query";

/**
 * Whether the device can reach the network, and telling React Query about it.
 *
 * The cache is already persisted to disk (see App.tsx), so a register opened
 * yesterday is still on the phone. What was missing is anything that *knows*
 * the connection is gone: React Query assumed it was always online, so a
 * request on a farm with no signal spun and then failed rather than falling
 * back to what had been kept, and a mutation could never be paused for later.
 *
 * `isInternetReachable` rather than `isConnected`: a supervisor's phone joins
 * the shed's wifi and shows full bars with nothing behind it, which is exactly
 * the case where the app must not pretend it is online. It is null until the
 * first reachability probe answers, and unknown is treated as online — the
 * request itself is a better test than a guess, and failing closed would block
 * the app for the seconds before the probe returns.
 */
export function startOnlineWatch(): void {
  // React Query owns the subscription's lifetime — it tears the previous
  // listener down when a new one is set, so there is nothing to return here.
  onlineManager.setEventListener((setOnline) =>
    NetInfo.addEventListener((state) => {
      setOnline(state.isInternetReachable ?? state.isConnected ?? true);
    })
  );
}
