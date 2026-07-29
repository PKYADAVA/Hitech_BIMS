import { createBottomTabNavigator } from "@react-navigation/bottom-tabs";
import { DarkTheme, DefaultTheme, NavigationContainer } from "@react-navigation/native";
import { createNativeStackNavigator } from "@react-navigation/native-stack";
import React from "react";
import { Pressable, Text, View } from "react-native";

import { AppIcon } from "@/components/AppIcon";
import { Loading } from "@/components/ui";
import { MODULES, ModuleKey, RESOURCES } from "@/config/catalog";
import { isEditable } from "@/config/forms";
import { openRecordForm } from "@/navigation/openForm";
import { BirdSaleFormScreen } from "@/screens/BirdSaleFormScreen";
import { DocumentFormScreen } from "@/screens/DocumentFormScreen";
import { FormScreen } from "@/screens/FormScreen";
import { HomeScreen } from "@/screens/HomeScreen";
import { LoginScreen } from "@/screens/LoginScreen";
import { ModuleHubScreen } from "@/screens/ModuleHubScreen";
import { ProfileScreen } from "@/screens/ProfileScreen";
import { RecordDetailScreen } from "@/screens/RecordDetailScreen";
import { ManageAccessScreen } from "@/screens/ManageAccessScreen";
import { ReportScreen } from "@/screens/ReportScreen";
import { ResourceListScreen } from "@/screens/ResourceListScreen";
import { SmsSendScreen } from "@/screens/SmsSendScreen";
import { useAuthStore } from "@/store/authStore";
import { usePermissionsStore } from "@/store/permissionsStore";
import { colors, shadow, useTheme } from "@/theme";
import { ModuleStackParams, TabParams } from "./types";

const Root = createNativeStackNavigator();
const Tab = createBottomTabNavigator<TabParams>();
const ModuleStack = createNativeStackNavigator<ModuleStackParams>();

function tabIcon(icon: string) {
  return ({ focused, color }: { focused: boolean; color: string }) => (
    <AppIcon emoji={icon} size={24} color={color} style={{ opacity: focused ? 1 : 0.9 }} />
  );
}

/** Native header title that leads with the screen's icon, then its name. */
function headerTitleWithIcon(icon: string, title: string) {
  return () => (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
      <AppIcon emoji={icon} size={19} color={colors.onDark} />
      <Text style={{ color: colors.onDark, fontSize: 17, fontWeight: "800" }}>{title}</Text>
    </View>
  );
}

/**
 * One native stack per module (Hub → List → Detail), branded in the module
 * color, with an icon-led header. Used both by bottom-tab modules and by the
 * Root-presented ones (Accounts, Inventory), which return via the swipe/back
 * gesture rather than a header button.
 */
function ModuleStackScreen({ moduleKey }: { moduleKey: ModuleKey }) {
  const { colors } = useTheme();
  const mod = MODULES[moduleKey];
  return (
    <ModuleStack.Navigator
      screenOptions={{
        headerStyle: { backgroundColor: mod.color },
        headerTintColor: colors.onDark,
        headerTitleStyle: { fontWeight: "800" },
        headerShadowVisible: false,
        headerBackVisible: false,
        contentStyle: { backgroundColor: colors.bg },
      }}
    >
      <ModuleStack.Screen
        name="Hub"
        options={{
          title: mod.title,
          headerTitle: headerTitleWithIcon(mod.icon, mod.title),
          // Root-presented modules (Accounts/Inventory) otherwise get a native
          // back button on this first screen — hide it; return via swipe/back.
          headerBackVisible: false,
        }}
      >
        {(props) => <ModuleHubScreen {...props} moduleKey={moduleKey} />}
      </ModuleStack.Screen>
      <ModuleStack.Screen
        name="List"
        component={ResourceListScreen}
        options={({ route, navigation }) => {
          const key = route.params.resourceKey;
          return {
            title: RESOURCES[key].title,
            headerTitle: headerTitleWithIcon(RESOURCES[key].icon, RESOURCES[key].title),
            headerRight:
              isEditable(key) &&
              usePermissionsStore.getState().canAction(RESOURCES[key].module, "add")
              ? () => (
                  <Pressable
                    hitSlop={12}
                    onPress={() => openRecordForm(navigation, key, "create")}
                  >
                    <AppIcon name="plus" size={24} color={colors.onDark} />
                  </Pressable>
                )
              : undefined,
          };
        }}
      />
      <ModuleStack.Screen name="Detail" component={RecordDetailScreen} options={{ title: "" }} />
      <ModuleStack.Screen name="Form" component={FormScreen} />
      <ModuleStack.Screen name="BirdSaleForm" component={BirdSaleFormScreen} />
      <ModuleStack.Screen name="DocumentForm" component={DocumentFormScreen} />
      <ModuleStack.Screen name="SmsSend" component={SmsSendScreen} />
      <ModuleStack.Screen name="Report" component={ReportScreen} />
      <ModuleStack.Screen name="ManageAccess" component={ManageAccessScreen} />
    </ModuleStack.Navigator>
  );
}

const BroilerStack = () => <ModuleStackScreen moduleKey="broiler" />;
const HatcheryStack = () => <ModuleStackScreen moduleKey="hatchery" />;
const SmsStack = () => <ModuleStackScreen moduleKey="sms" />;
const AccountStack = () => <ModuleStackScreen moduleKey="account" />;
const InventoryStack = () => <ModuleStackScreen moduleKey="inventory" />;
const SalesStack = () => <ModuleStackScreen moduleKey="sales" />;
const PurchaseStack = () => <ModuleStackScreen moduleKey="purchase" />;
const HrStack = () => <ModuleStackScreen moduleKey="hr" />;
const UserStack = () => <ModuleStackScreen moduleKey="user" />;

function AppTabs() {
  const { colors } = useTheme();
  const canModule = usePermissionsStore((s) => s.canModule);
  const permsLoaded = usePermissionsStore((s) => s.loaded);
  const show = (m: string) => !permsLoaded || canModule(m);
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
      {show("broiler") && (
        <Tab.Screen name="Broiler" component={BroilerStack} options={{ tabBarIcon: tabIcon("🐔") }} />
      )}
      {show("hatchery") && (
        <Tab.Screen name="Hatchery" component={HatcheryStack} options={{ tabBarIcon: tabIcon("🥚") }} />
      )}
      {show("sms") && (
        <Tab.Screen name="SMS" component={SmsStack} options={{ tabBarIcon: tabIcon("💬") }} />
      )}
      <Tab.Screen name="Profile" component={ProfileScreen} options={{ tabBarIcon: tabIcon("👤") }} />
    </Tab.Navigator>
  );
}

export function RootNavigator() {
  const status = useAuthStore((s) => s.status);
  const { scheme, colors } = useTheme();

  if (status === "loading") return <Loading label="Starting…" />;

  // Theme the container so screen backgrounds (and transition flashes) match
  // the active palette instead of React Navigation's default white.
  const navTheme =
    scheme === "dark"
      ? { ...DarkTheme, colors: { ...DarkTheme.colors, background: colors.bg, card: colors.surface, border: colors.border, primary: colors.primary, text: colors.text } }
      : { ...DefaultTheme, colors: { ...DefaultTheme.colors, background: colors.bg, card: colors.surface, border: colors.border, primary: colors.primary, text: colors.text } };

  return (
    <NavigationContainer theme={navTheme}>
      <Root.Navigator screenOptions={{ headerShown: false }}>
        {status === "signedIn" ? (
          <>
            <Root.Screen name="App" component={AppTabs} />
            {/* Modules reached from Home tiles (not bottom tabs) — presented as cards. */}
            <Root.Screen name="AccountModule" component={AccountStack} />
            <Root.Screen name="InventoryModule" component={InventoryStack} />
            <Root.Screen name="SalesModule" component={SalesStack} />
            <Root.Screen name="PurchaseModule" component={PurchaseStack} />
            <Root.Screen name="HrModule" component={HrStack} />
            <Root.Screen name="UserModule" component={UserStack} />
          </>
        ) : (
          <Root.Screen name="Login" component={LoginScreen} />
        )}
      </Root.Navigator>
    </NavigationContainer>
  );
}
