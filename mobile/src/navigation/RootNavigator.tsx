import { createBottomTabNavigator } from "@react-navigation/bottom-tabs";
import { NavigationContainer } from "@react-navigation/native";
import { createNativeStackNavigator } from "@react-navigation/native-stack";
import React from "react";
import { Pressable, Text } from "react-native";

import { Loading } from "@/components/ui";
import { MODULES, ModuleKey, RESOURCES } from "@/config/catalog";
import { isEditable } from "@/config/forms";
import { FormScreen } from "@/screens/FormScreen";
import { HomeScreen } from "@/screens/HomeScreen";
import { LoginScreen } from "@/screens/LoginScreen";
import { ModuleHubScreen } from "@/screens/ModuleHubScreen";
import { ProfileScreen } from "@/screens/ProfileScreen";
import { RecordDetailScreen } from "@/screens/RecordDetailScreen";
import { ResourceListScreen } from "@/screens/ResourceListScreen";
import { useAuthStore } from "@/store/authStore";
import { colors, shadow } from "@/theme";
import { ModuleStackParams, TabParams } from "./types";

const Root = createNativeStackNavigator();
const Tab = createBottomTabNavigator<TabParams>();
const ModuleStack = createNativeStackNavigator<ModuleStackParams>();

function tabIcon(icon: string) {
  return ({ focused }: { focused: boolean }) => (
    <Text style={{ fontSize: 20, opacity: focused ? 1 : 0.5 }}>{icon}</Text>
  );
}

/** One native stack per module (Hub → List → Detail), branded in the module color. */
function ModuleStackScreen({ moduleKey }: { moduleKey: ModuleKey }) {
  const mod = MODULES[moduleKey];
  return (
    <ModuleStack.Navigator
      screenOptions={{
        headerStyle: { backgroundColor: mod.color },
        headerTintColor: colors.onDark,
        headerTitleStyle: { fontWeight: "800" },
        headerShadowVisible: false,
        contentStyle: { backgroundColor: colors.bg },
      }}
    >
      <ModuleStack.Screen name="Hub" options={{ title: mod.title }}>
        {(props) => <ModuleHubScreen {...props} moduleKey={moduleKey} />}
      </ModuleStack.Screen>
      <ModuleStack.Screen
        name="List"
        component={ResourceListScreen}
        options={({ route, navigation }) => {
          const key = route.params.resourceKey;
          return {
            title: RESOURCES[key].title,
            headerRight: isEditable(key)
              ? () => (
                  <Pressable
                    hitSlop={12}
                    onPress={() => navigation.navigate("Form", { resourceKey: key, mode: "create" })}
                  >
                    <Text style={{ color: colors.onDark, fontSize: 26, fontWeight: "700" }}>＋</Text>
                  </Pressable>
                )
              : undefined,
          };
        }}
      />
      <ModuleStack.Screen name="Detail" component={RecordDetailScreen} options={{ title: "" }} />
      <ModuleStack.Screen name="Form" component={FormScreen} />
    </ModuleStack.Navigator>
  );
}

const BroilerStack = () => <ModuleStackScreen moduleKey="broiler" />;
const HatcheryStack = () => <ModuleStackScreen moduleKey="hatchery" />;

function AppTabs() {
  return (
    <Tab.Navigator
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: colors.primary,
        tabBarInactiveTintColor: colors.textFaint,
        tabBarStyle: {
          backgroundColor: colors.surface,
          borderTopColor: colors.border,
          ...shadow(1),
        },
        tabBarLabelStyle: { fontSize: 11, fontWeight: "600" },
      }}
    >
      <Tab.Screen name="Home" component={HomeScreen} options={{ tabBarIcon: tabIcon("🏠") }} />
      <Tab.Screen name="Broiler" component={BroilerStack} options={{ tabBarIcon: tabIcon("🐔") }} />
      <Tab.Screen name="Hatchery" component={HatcheryStack} options={{ tabBarIcon: tabIcon("🥚") }} />
      <Tab.Screen name="Profile" component={ProfileScreen} options={{ tabBarIcon: tabIcon("👤") }} />
    </Tab.Navigator>
  );
}

export function RootNavigator() {
  const status = useAuthStore((s) => s.status);

  if (status === "loading") return <Loading label="Starting…" />;

  return (
    <NavigationContainer>
      <Root.Navigator screenOptions={{ headerShown: false }}>
        {status === "signedIn" ? (
          <Root.Screen name="App" component={AppTabs} />
        ) : (
          <Root.Screen name="Login" component={LoginScreen} />
        )}
      </Root.Navigator>
    </NavigationContainer>
  );
}
