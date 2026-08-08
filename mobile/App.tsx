import AsyncStorage from "@react-native-async-storage/async-storage";
import { createAsyncStoragePersister } from "@tanstack/query-async-storage-persister";
import { PersistQueryClientProvider } from "@tanstack/react-query-persist-client";
import { StatusBar } from "expo-status-bar";
import React, { useEffect } from "react";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { LockGate } from "@/components/LockGate";
import { OfflineBar } from "@/components/OfflineBar";
import { startOnlineWatch } from "@/net/online";
import { enqueue, flushOutbox, outboxState, pendingWrites } from "@/net/outbox";
import { writeThrough } from "@/net/writeThrough";
import { RootNavigator } from "@/navigation/RootNavigator";
import { registerForPush } from "@/push";
import { queryClient } from "@/query/queryClient";
import { useAuthStore } from "@/store/authStore";
import { usePermissionsStore } from "@/store/permissionsStore";
import { useSettingsStore } from "@/store/settingsStore";
import { ThemeProvider } from "@/theme";

// Persist the React Query cache to disk so lists/details show last-known data
// offline (read cache). Cursor/page feeds restore instantly on next launch.
const persister = createAsyncStoragePersister({ storage: AsyncStorage });

/**
 * App root: hydrate persisted tokens + local settings once on mount, then render
 * the navigator inside the (persisted) Query + SafeArea providers, gated by the
 * optional biometric App Lock.
 */
export default function App() {
  const bootstrap = useAuthStore((s) => s.bootstrap);
  const hydrateSettings = useSettingsStore((s) => s.hydrate);
  const status = useAuthStore((s) => s.status);
  const loadPermissions = usePermissionsStore((s) => s.load);
  const resetPermissions = usePermissionsStore((s) => s.reset);

  useEffect(() => {
    bootstrap();
    hydrateSettings();
  }, [bootstrap, hydrateSettings]);

  // Tell React Query when the connection comes and goes. Without this it
  // assumes it is always online, so a request on a farm with no signal spins
  // and fails instead of falling back to the cache already on disk.
  useEffect(() => { startOnlineWatch(); }, []);

  // A handle on the write path for the browser test that pulls the network and
  // checks the save is neither lost nor made twice. Development builds only —
  // there is nothing here a release should hand to the page.
  useEffect(() => {
    if (!__DEV__) return;
    (globalThis as Record<string, unknown>).__bimsOffline = {
      writeThrough, flushOutbox, pendingWrites, outboxState, enqueue,
    };
  }, []);

  // Once signed in: register for push + load this user's module permissions.
  // On sign-out: clear permissions so the next user starts fresh.
  useEffect(() => {
    if (status === "signedIn") {
      registerForPush();
      loadPermissions();
    } else if (status === "signedOut") {
      resetPermissions();
    }
  }, [status, loadPermissions, resetPermissions]);

  return (
    <SafeAreaProvider>
      <ThemeProvider>
        <PersistQueryClientProvider
          client={queryClient}
          persistOptions={{ persister, maxAge: 1000 * 60 * 60 * 24 }}
        >
          <StatusBar style="light" />
          <LockGate>
            {/* Above the navigator, so it is on every screen: cached data
                looks exactly like live data, and that is worth saying. */}
            <OfflineBar />
            <RootNavigator />
          </LockGate>
        </PersistQueryClientProvider>
      </ThemeProvider>
    </SafeAreaProvider>
  );
}
