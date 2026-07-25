import { QueryClientProvider } from "@tanstack/react-query";
import { StatusBar } from "expo-status-bar";
import React, { useEffect } from "react";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { RootNavigator } from "@/navigation/RootNavigator";
import { queryClient } from "@/query/queryClient";
import { useAuthStore } from "@/store/authStore";

/**
 * App root: hydrate persisted tokens (deciding Login vs. app tabs) once on
 * mount, then render the navigator inside the Query + SafeArea providers.
 */
export default function App() {
  const bootstrap = useAuthStore((s) => s.bootstrap);

  useEffect(() => {
    bootstrap();
  }, [bootstrap]);

  return (
    <SafeAreaProvider>
      <QueryClientProvider client={queryClient}>
        <StatusBar style="light" />
        <RootNavigator />
      </QueryClientProvider>
    </SafeAreaProvider>
  );
}
