import AsyncStorage from "@react-native-async-storage/async-storage";
import { createAsyncStoragePersister } from "@tanstack/query-async-storage-persister";
import { PersistQueryClientProvider } from "@tanstack/react-query-persist-client";
import { StatusBar } from "expo-status-bar";
import React, { useEffect } from "react";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { LockGate } from "@/components/LockGate";
import { RootNavigator } from "@/navigation/RootNavigator";
import { registerForPush } from "@/push";
import { queryClient } from "@/query/queryClient";
import { useAuthStore } from "@/store/authStore";
import { useSettingsStore } from "@/store/settingsStore";

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

  useEffect(() => {
    bootstrap();
    hydrateSettings();
  }, [bootstrap, hydrateSettings]);

  // Register this device for push once signed in (no-op on Expo Go / simulators).
  useEffect(() => {
    if (status === "signedIn") registerForPush();
  }, [status]);

  return (
    <SafeAreaProvider>
      <PersistQueryClientProvider
        client={queryClient}
        persistOptions={{ persister, maxAge: 1000 * 60 * 60 * 24 }}
      >
        <StatusBar style="light" />
        <LockGate>
          <RootNavigator />
        </LockGate>
      </PersistQueryClientProvider>
    </SafeAreaProvider>
  );
}
