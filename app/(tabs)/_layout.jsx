import { Tabs, usePathname, router } from 'expo-router';
import { TabBar } from '../../src/balanceai_frontend/components';

const ROUTE_TO_TAB = {
  '/':              'chat',
  '/(tabs)':        'chat',
  '/(tabs)/':       'chat',
  '/journal':       'ledger',
  '/(tabs)/journal':       'ledger',
  '/reports':              'reports',
  '/(tabs)/reports':       'reports',
};

const TAB_TO_ROUTE = {
  chat:    '/(tabs)/',
  ledger:  '/(tabs)/journal',
  reports: '/(tabs)/reports',
};

function CustomTabBar() {
  const pathname = usePathname();
  const current = ROUTE_TO_TAB[pathname] || 'chat';
  return (
    <TabBar
      current={current}
      onChange={(id) => router.navigate(TAB_TO_ROUTE[id])}
    />
  );
}

export default function TabLayout() {
  return (
    <Tabs tabBar={() => <CustomTabBar />} screenOptions={{ headerShown: false }}>
      <Tabs.Screen name="index" />
      <Tabs.Screen name="journal" />
      <Tabs.Screen name="reports" />
    </Tabs>
  );
}
