import { NavigationContainer } from "@react-navigation/native";
import { createBottomTabNavigator } from "@react-navigation/bottom-tabs";
import { createNativeStackNavigator } from "@react-navigation/native-stack";
import React from "react";
import { Text } from "react-native";

import { Loading } from "@/components/ui";
import { DailyEntriesScreen } from "@/screens/DailyEntriesScreen";
import { EggPurchasesScreen } from "@/screens/EggPurchasesScreen";
import { HomeScreen } from "@/screens/HomeScreen";
import { LoginScreen } from "@/screens/LoginScreen";
import { useAuthStore } from "@/store/authStore";
import { colors } from "@/theme";

const Tab = createBottomTabNavigator();
const Stack = createNativeStackNavigator();

/** Emoji tab icons keep the first build dependency-free (swap for vector icons later). */
function tabIcon(icon: string) {
  return ({ color }: { color: string }) => <Text style={{ fontSize: 18, color }}>{icon}</Text>;
}

function AppTabs() {
  return (
    <Tab.Navigator
      screenOptions={{
        headerStyle: { backgroundColor: colors.primary },
        headerTintColor: "#fff",
        tabBarActiveTintColor: colors.primary,
      }}
    >
      <Tab.Screen name="Home" component={HomeScreen} options={{ tabBarIcon: tabIcon("🏠") }} />
      <Tab.Screen
        name="DailyEntries"
        component={DailyEntriesScreen}
        options={{ title: "Daily Entries", tabBarLabel: "Broiler", tabBarIcon: tabIcon("🐔") }}
      />
      <Tab.Screen
        name="EggPurchases"
        component={EggPurchasesScreen}
        options={{ title: "Egg Purchases", tabBarLabel: "Hatchery", tabBarIcon: tabIcon("🥚") }}
      />
    </Tab.Navigator>
  );
}

export function RootNavigator() {
  const status = useAuthStore((s) => s.status);

  if (status === "loading") return <Loading label="Starting…" />;

  return (
    <NavigationContainer>
      <Stack.Navigator screenOptions={{ headerShown: false }}>
        {status === "signedIn" ? (
          <Stack.Screen name="App" component={AppTabs} />
        ) : (
          <Stack.Screen name="Login" component={LoginScreen} />
        )}
      </Stack.Navigator>
    </NavigationContainer>
  );
}
