/**
 * Knowing when the connection is gone, and forgetting a session's data.
 *
 * The read cache already survives on disk. What was missing is anything that
 * *tells* React Query the connection went — without it a request on a farm
 * with no signal spins and fails instead of falling back to what was kept.
 */
const listeners: ((s: unknown) => void)[] = [];

jest.mock("@react-native-community/netinfo", () => ({
  __esModule: true,
  default: {
    addEventListener: (cb: (s: unknown) => void) => {
      listeners.push(cb);
      return () => undefined;
    },
  },
}));

import { onlineManager } from "@tanstack/react-query";

import { startOnlineWatch } from "./online";

/** Push a NetInfo state through whatever the watcher subscribed. */
const emit = (state: Record<string, unknown>) =>
  listeners.forEach((cb) => cb(state));

beforeEach(() => {
  listeners.length = 0;
  startOnlineWatch();
});

describe("startOnlineWatch", () => {
  it("reports offline when there is no connection", () => {
    emit({ isConnected: false, isInternetReachable: false });
    expect(onlineManager.isOnline()).toBe(false);
  });

  it("reports online again when it comes back", () => {
    emit({ isConnected: false, isInternetReachable: false });
    emit({ isConnected: true, isInternetReachable: true });
    expect(onlineManager.isOnline()).toBe(true);
  });

  it("trusts reachability over the radio", () => {
    // A phone joins the shed's wifi and shows full bars with nothing behind
    // it. That is exactly when the app must not claim to be online.
    emit({ isConnected: true, isInternetReachable: false });
    expect(onlineManager.isOnline()).toBe(false);
  });

  it("believes the radio even when reachability is stale", () => {
    // How this first went in: on web isInternetReachable can sit at true while
    // the connection has plainly gone, so trusting it alone reported online
    // with the network pulled.
    emit({ isConnected: false, isInternetReachable: true });
    expect(onlineManager.isOnline()).toBe(false);
  });

  it("treats an unanswered probe as online", () => {
    // isInternetReachable is null until the first probe returns. Failing
    // closed there would block the app for the seconds it takes; the request
    // itself is a better test than a guess.
    emit({ isConnected: true, isInternetReachable: null });
    expect(onlineManager.isOnline()).toBe(true);
  });
});
