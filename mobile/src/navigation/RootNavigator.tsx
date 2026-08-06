import { createBottomTabNavigator } from "@react-navigation/bottom-tabs";
import { DarkTheme, DefaultTheme, NavigationContainer, useNavigation } from "@react-navigation/native";
import { createNativeStackNavigator } from "@react-navigation/native-stack";
import React from "react";
import { Pressable, Text, View } from "react-native";

import { AppIcon } from "@/components/AppIcon";
import { SideNav, SideNavButton } from "@/components/SideNav";
import { useSideNav } from "@/store/sideNavStore";
import { Loading } from "@/components/ui";
import { MODULES, ModuleKey, RESOURCES } from "@/config/catalog";
import { isEditable } from "@/config/forms";
import { ModuleTabBar } from "@/components/ModuleTabBar";
import { MODULE_ICON, MODULE_PRIMARY } from "@/config/modulePrimary";
import { openRecordForm } from "@/navigation/openForm";
import { BatchFormScreen } from "@/screens/BatchFormScreen";
import { BirdSaleFormScreen } from "@/screens/BirdSaleFormScreen";
import { BirdSaleReceiptFormScreen } from "@/screens/BirdSaleReceiptFormScreen";
import { DailyEntryGridScreen } from "@/screens/DailyEntryGridScreen";
import { DocumentFormScreen } from "@/screens/DocumentFormScreen";
import { FarmCaptureFormScreen } from "@/screens/FarmCaptureFormScreen";
import { FormScreen } from "@/screens/FormScreen";
import { HomeScreen } from "@/screens/HomeScreen";
import { LoginScreen } from "@/screens/LoginScreen";
import { MedicineEntryFormScreen } from "@/screens/MedicineEntryFormScreen";
import { ModuleHubScreen } from "@/screens/ModuleHubScreen";
import { ProfileScreen } from "@/screens/ProfileScreen";
import { RecordDetailScreen } from "@/screens/RecordDetailScreen";
import { ManageAccessScreen } from "@/screens/ManageAccessScreen";
import { ReportScreen } from "@/screens/ReportScreen";
import { ReportsHubScreen, ReportsStackParams } from "@/screens/ReportsHubScreen";
import { ResourceListScreen } from "@/screens/ResourceListScreen";
import { SmsSendScreen } from "@/screens/SmsSendScreen";
import { SupervisorTripFormScreen } from "@/screens/SupervisorTripFormScreen";
import { useAuthStore } from "@/store/authStore";
import { usePermissionsStore } from "@/store/permissionsStore";
import { colors, shadow, useTheme } from "@/theme";
import { ModuleStackParams, TabParams } from "./types";

const Root = createNativeStackNavigator();
const Tab = createBottomTabNavigator<TabParams>();
const ModuleStack = createNativeStackNavigator<ModuleStackParams>();

/**
 * Bottom-tab icon with a clear "selected" affordance: the active tab gets a
 * filled pill behind its icon (Material-style), so the current tab reads at a
 * glance even in dark mode where the active/inactive tints are close.
 */
function TabBarIcon({ icon, focused, color }: { icon: string; focused: boolean; color: string }) {
  const { colors } = useTheme();
  return (
    <View
      style={{
        minWidth: 56,
        height: 30,
        borderRadius: 999,
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: focused ? colors.primaryLight : "transparent",
      }}
    >
      <AppIcon emoji={icon} size={24} color={color} />
    </View>
  );
}

function tabIcon(icon: string) {
  return ({ focused, color }: { focused: boolean; color: string }) => (
    <TabBarIcon icon={icon} focused={focused} color={color} />
  );
}

/** Native header title that leads with the screen's icon, then its name. */
/** Header title with a glyph, for the module chrome (see MODULE_ICON). */
function headerTitleWithIconName(icon: string, title: string) {
  return () => (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
      <AppIcon name={icon as any} size={19} color={colors.onDark} />
      <Text style={{ color: colors.onDark, fontSize: 17, fontWeight: "800" }}>{title}</Text>
    </View>
  );
}

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
/** The module header's create button, or nothing. */
function ModulePrimaryButton({ moduleKey }: { moduleKey: ModuleKey }) {
  const navigation = useNavigation<any>();
  const { colors } = useTheme();
  const primary = MODULE_PRIMARY[moduleKey];
  const canResource = usePermissionsStore((s) => s.canResource);
  if (!primary || !isEditable(primary.resourceKey)) return null;
  if (!canResource(primary.resourceKey, moduleKey, "add")) return null;
  return (
    <Pressable
      hitSlop={12}
      onPress={() => openRecordForm(navigation, primary.resourceKey, "create")}
      accessibilityRole="button"
      accessibilityLabel={primary.label}
      style={{ flexDirection: "row", alignItems: "center", gap: 4 }}
    >
      <AppIcon name="plus" size={18} color={colors.onDark} />
      <Text style={{ color: colors.onDark, fontWeight: "700" }}>{primary.label}</Text>
    </Pressable>
  );
}

function ModuleStackScreen({ moduleKey }: { moduleKey: ModuleKey }) {
  const { colors } = useTheme();
  const mod = MODULES[moduleKey];
  return (
    <View style={{ flex: 1 }}>
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
        listeners={{ focus: () => useSideNav.getState().setActive(moduleKey) }}
        options={{
          title: mod.title,
          headerTitle: headerTitleWithIconName(MODULE_ICON[moduleKey], mod.title),
          // Root-presented modules (Accounts/Inventory) otherwise get a native
          // back button on this first screen — hide it; the bar below is the
          // way out, and swipe/back still works.
          //
          // No hamburger here: this screen already carries a module bar with
          // Menu on it, and two buttons opening the same sidebar is one too
          // many. Home and Reports have no such bar and keep theirs.
          headerBackVisible: false,
          // The module's one create action, beside its title as the reference
          // has it — hidden when the user may not add, and absent for modules
          // with nothing obvious to create.
          headerRight: () => <ModulePrimaryButton moduleKey={moduleKey} />,
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
              usePermissionsStore.getState().canResource(key, RESOURCES[key].module, "add")
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
      <ModuleStack.Screen name="BatchForm" component={BatchFormScreen} />
      <ModuleStack.Screen name="BirdSaleForm" component={BirdSaleFormScreen} />
      <ModuleStack.Screen name="BirdSaleReceiptForm" component={BirdSaleReceiptFormScreen} />
      <ModuleStack.Screen name="DailyEntryGrid" component={DailyEntryGridScreen} />
      <ModuleStack.Screen name="MedicineEntryForm" component={MedicineEntryFormScreen} />
      <ModuleStack.Screen name="FarmCaptureForm" component={FarmCaptureFormScreen} />
      <ModuleStack.Screen name="SupervisorTripForm" component={SupervisorTripFormScreen} />
      <ModuleStack.Screen name="DocumentForm" component={DocumentFormScreen} />
      <ModuleStack.Screen name="SmsSend" component={SmsSendScreen} />
      <ModuleStack.Screen name="Report" component={ReportScreen} />
      <ModuleStack.Screen name="ManageAccess" component={ManageAccessScreen} />
    </ModuleStack.Navigator>
    {/* One bar for the whole module, so pushing a list or a form keeps it. */}
    <ModuleTabBar moduleKey={moduleKey} />
    </View>
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
const ChangeRequestStack = () => <ModuleStackScreen moduleKey="change_requests" />;

/** Reports & Analytics: the index, and whichever report is opened from it. */
const ReportsStackNav = createNativeStackNavigator<ReportsStackParams>();
function ReportsStack() {
  const { colors } = useTheme();
  return (
    <ReportsStackNav.Navigator
      screenOptions={{
        headerStyle: { backgroundColor: colors.tint },
        headerTintColor: colors.onDark,
        headerTitleStyle: { fontWeight: "800" },
        headerShadowVisible: false,
        contentStyle: { backgroundColor: colors.bg },
      }}
    >
      <ReportsStackNav.Screen
        name="ReportsHub"
        component={ReportsHubScreen}
        options={{
          title: "Reports & Analytics",
          headerLeft: () => <SideNavButton tint={colors.onDark} />,
        }}
      />
      <ReportsStackNav.Screen
        name="Report"
        component={ReportScreen}
        options={({ route }) => ({ title: (route.params as any)?.title ?? "Report" })}
      />
    </ReportsStackNav.Navigator>
  );
}

function AppTabs() {
  const { colors } = useTheme();
  const canModule = usePermissionsStore((s) => s.canModule);
  const permsLoaded = usePermissionsStore((s) => s.loaded);
  const show = (m: string) => !permsLoaded || canModule(m);
  return (
    <Tab.Navigator
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: colors.tint,
        tabBarInactiveTintColor: colors.textMuted,
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
        <Tab.Screen name="Broiler" component={BroilerStack} options={{ tabBarIcon: tabIcon("🐔"), tabBarStyle: { display: "none" } }} />
      )}
      {show("hatchery") && (
        <Tab.Screen name="Hatchery" component={HatcheryStack} options={{ tabBarIcon: tabIcon("🥚"), tabBarStyle: { display: "none" } }} />
      )}
      {show("sms") && (
        <Tab.Screen name="SMS" component={SmsStack} options={{ tabBarIcon: tabIcon("💬"), tabBarStyle: { display: "none" } }} />
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
      ? { ...DarkTheme, colors: { ...DarkTheme.colors, background: colors.bg, card: colors.surface, border: colors.border, primary: colors.tint, text: colors.text } }
      : { ...DefaultTheme, colors: { ...DefaultTheme.colors, background: colors.bg, card: colors.surface, border: colors.border, primary: colors.tint, text: colors.text } };

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
            <Root.Screen name="ChangeRequestModule" component={ChangeRequestStack} />
            <Root.Screen name="ReportsModule" component={ReportsStack} />
          </>
        ) : (
          <Root.Screen name="Login" component={LoginScreen} />
        )}
      </Root.Navigator>
      {/* Rendered inside the container so it can navigate, and outside the
          navigator so it floats over whatever screen is showing. */}
      {status === "signedIn" ? <SideNav /> : null}
    </NavigationContainer>
  );
}
