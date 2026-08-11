import { useEffect } from 'react';
import { Stack } from 'expo-router';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { useFonts } from 'expo-font';
import * as SplashScreen from 'expo-splash-screen';
import {
  SourceSerif4_400Regular,
  SourceSerif4_600SemiBold,
  SourceSerif4_400Regular_Italic,
} from '@expo-google-fonts/source-serif-4';
import { ThemeContext, BROADSHEET } from '../src/balanceai_frontend/theme';
import { LedgerProvider } from '../src/balanceai_frontend/state/ledgerStore';

SplashScreen.preventAutoHideAsync();

export default function RootLayout() {
  const [fontsLoaded] = useFonts({
    SourceSerif4_400Regular,
    SourceSerif4_600SemiBold,
    SourceSerif4_400Regular_Italic,
  });

  useEffect(() => {
    if (fontsLoaded) SplashScreen.hideAsync();
  }, [fontsLoaded]);

  if (!fontsLoaded) return null;

  return (
    <SafeAreaProvider>
      <ThemeContext.Provider value={BROADSHEET}>
        <LedgerProvider>
          <Stack screenOptions={{ headerShown: false }} />
        </LedgerProvider>
      </ThemeContext.Provider>
    </SafeAreaProvider>
  );
}
